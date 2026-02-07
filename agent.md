# 门店经营助手 AI 大脑（本地异步可跑通 MVP v2）

目标：用 **FastAPI(Async) + Vue3 + MySQL + LangGraph(ainvoke) + DeepSeek** 做一个前后端 MVP，能跑通以下 4 个演示场景（数据全部为 mock）：

- **场景 A：一句话出报表（Text-to-SQL）**  
  输入自然语言 → 生成只读 SQL → 异步执行 MySQL → 返回报表表格 + 简单解释（含口径说明）。
- **场景 B：业务诊断（数据 + 经营知识 RAG）**  
  输入“指标下降/异常” → 先取数验证 → 再用知识库（RAG）给出可能原因 + 验证结果 + 下一步动作建议（只产出文本/要点）。
- **场景 C：自动生成活动方案（营销策划）**  
  输入目标/预算/周期 → 输出结构化方案 JSON（券类型、人群、预算拆分、KPI、风险）。
- **场景 D：一键上架（动作闭环：创建券并上架到CRM Mock）**  
  前端对场景 C 的方案点击“执行上架” → 后端调用 mock CRM API（异步 httpx）→ 写入执行日志 → 返回执行回执（coupon_id、publish 状态、幂等 key、失败原因）。

约束（必须严格遵守）：

- **不使用 Docker**。全部本地启动。
- **全程使用异步**：FastAPI、SQLAlchemy(Async)、httpx(Async)、LangGraph `ainvoke`、节点 `async def`。  
  允许对 _阻塞库_（如 `sentence-transformers`、`chromadb`）用 `anyio.to_thread.run_sync(...)` 包装到线程池，保证调用端不阻塞事件循环。
- DeepSeek 使用 **API Key**（环境变量读取）。
- 向量库尽量简单：选择 **Chroma 本地目录持久化**。
- Embedding 模型：**本地 bge-base-zh-v1.5**，路径固定为 `backend/models/bge-base-zh-v1.5`（不要联网下载）。
- 必须创建 MySQL 表结构并填充 mock 数据（固定随机种子，可重复生成）。
- SQL 安全：只允许 **SELECT**；强制 LIMIT；超时控制；不允许多语句。

---

## 1. 技术栈与目录结构（必须按此落地）

### 后端（Python 3.11+）

- FastAPI
- SQLAlchemy 2.x（async）
- aiomysql
- langgraph
- openai（用 OpenAI 兼容方式调用 DeepSeek）
- chromadb
- sentence-transformers（本地加载 bge-base-zh-v1.5）
- torch（CPU 版即可）
- sqlglot（SQL AST 校验 + 强制 LIMIT）
- httpx（异步调用 mock CRM）
- anyio（线程池包装阻塞调用）
- pydantic-settings（环境变量管理）
- faker（mock 数据）

### 前端

- Vue 3 + Vite
- axios
- （可选）ECharts：用于趋势图；没有也可以仅表格

### 项目目录（根目录）

```
mvp-retail-ai/
  backend/
    app/
      main.py
      core/
        config.py
        logging.py
      db/
        engine.py
        models.py
        seed.py
        crud.py
      rag/
        chroma_store.py
        kb_seed.py
      llm/
        deepseek_client.py
        prompts.py
      integrations/
        crm_client.py         # httpx.AsyncClient 调用 mock CRM
      graph/
        graph.py
        nodes.py
        state.py
      api/
        routes.py
        mock_crm_routes.py    # 提供 mock CRM endpoints
      tests/
        smoke_test.py
    requirements.txt
    .env.example
    models/
      bge-base-zh-v1.5/       # 本地模型目录（已存在或由你手动放入）
  frontend/
    index.html
    vite.config.ts
    package.json
    src/
      main.ts
      api.ts
      App.vue
      pages/
        Chat.vue
      components/
        MessageList.vue
        ReportTable.vue
        PlanCard.vue          # 显示方案+“执行上架”按钮
  README.md
```

---

## 2. 本地运行方式（必须可复现，不使用 Docker）

### 2.1 准备 MySQL

要求：本机已安装 MySQL 8.x，并能创建数据库与用户。示例（按你本机实际情况执行）：

- 创建数据库：`mvp_retail_ai`
- 用户：`root` / `123456`（示例）

### 2.2 启动后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # 填写你的 MySQL 与 DEEPSEEK_API_KEY

# 1) 创建表 + 填充 mock 数据（固定种子，可重复）
python -m app.db.seed

# 2) 初始化知识库向量（Chroma）
python -m app.rag.kb_seed

# 3) 启动 API
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 2.3 启动前端

```bash
cd frontend
npm i
npm run dev
```

访问：

- 前端：`http://127.0.0.1:5173`
- 后端：`http://127.0.0.1:8000`

---

## 3. 环境变量（已在 backend/.env 中提供）

---

## 4. MySQL 表结构（必须实现 + SQLAlchemy Async Model）

### 4.1 业务表（最小可用）

必须包含以下表（字段可按需要补充，但不能少核心字段）：

1. `stores`

- id (pk)
- name
- city

2. `members`

- id (pk)
- store_id (fk)
- created_at
- level (int)
- total_spent (decimal)

3. `orders`

- id (pk)
- store_id (fk)
- member_id (fk, nullable=允许游客)
- paid_at (datetime)
- pay_status (int：0失败 1成功)
- channel (varchar：offline / online / delivery)
- amount (decimal) # 实付
- original_amount (decimal) # 原价

4. `order_items`

- id (pk)
- order_id (fk)
- sku
- category
- qty
- price

### 4.2 活动与执行闭环（场景 D 必须）

5. `coupons`

- id (pk)
- name
- type (varchar：full_reduction/discount/points)
- threshold (decimal)
- value (decimal)
- start_at (datetime)
- end_at (datetime)
- status (varchar：draft/published)

6. `campaigns`

- id (pk)
- name
- goal
- budget (decimal)
- duration_days (int)
- plan_json (json/text)
- created_at

7. `action_logs`（审计与幂等）

- id (pk)
- idempotency_key (varchar unique)
- action_type (varchar：create_coupon/publish_coupon)
- request_json (json/text)
- response_json (json/text)
- status (varchar：success/failed)
- error_message (text nullable)
- created_at

---

## 5. Mock 数据生成（必须可复现 + 有“故事”）

实现 `backend/app/db/seed.py`：

- 固定随机种子（如 `SEED=42`）
- 生成：
    - stores: 10
    - members: 3000（分布到门店）
    - orders: 40000（覆盖最近 90 天）
    - order_items: 每单 1-5 条
- **制造可诊断趋势（必须）**：
    - 最近 7 天：老客（历史成功订单>=2）下单概率下降 30%，让复购率下降明显
    - 同期：新客订单上升，但客单价下降（降低 amount）
    - 某个门店（例如 store_id=3）：支付成功率下降（pay_status=0 增多）

seed 脚本执行后打印校验：

- 总订单数/成功订单数
- 最近 7 天 GMV、订单数、客单价
- 最近 7 天复购率 vs 上一周期复购率

---

## 6. 知识库（RAG）最小实现（Chroma + 本地 bge-base-zh-v1.5）

### 6.1 知识库内容（写死一批文档即可）

实现 `backend/app/rag/kb_seed.py` 初始化文档：

- 指标口径解释：GMV、客单价、复购率、支付成功率
- 复购率下降常见原因与验证路径（券到期、触达下降、供给变化、价格变化、支付失败上升、外卖占比变化）
- 常用活动玩法：满减券、折扣券、第二件半价、会员日、积分兑换
- 风险提醒：预算爆炸、核销率过低、羊毛党、券叠加规则

每条文档包含：

- `title`
- `content`
- `tags`（metric / diagnosis / campaign / risk）

### 6.2 向量库配置（必须按此实现）

- 目录：`${CHROMA_DIR}`
- collection 名称：`retail_kb`
- embedding：使用本地 **bge-base-zh-v1.5**（离线、可复现）
    - 模型路径：`backend/models/bge-base-zh-v1.5`
    - 实现：后端封装 `async embed(texts)->List[List[float]]`，用 `sentence-transformers` 从本地路径加载并编码
        - `SentenceTransformer(EMBED_MODEL_PATH)`
        - `encode(texts, normalize_embeddings=True)`（便于余弦相似度）
    - 异步要求：`sentence-transformers` 是阻塞库，必须用 `anyio.to_thread.run_sync` 包装

> 优先：能跑通。embedding 固定来自本地 bge-base-zh-v1.5，结果稳定，不依赖外部 embedding 服务。

---

## 7. LangGraph 编排（必须 async：ainvoke）

### 7.1 State 定义（backend/app/graph/state.py）

State 至少包含：

- user_query: str
- intent: Literal["report","diagnose","plan","execute"]
- sql: str | None
- rows: list[dict] | None
- knowledge: list[dict] | None
- answer: str | None
- plan: dict | None
- execution: dict | None
- debug: dict（记录 token/耗时/节点路径/SQL 校验信息）

### 7.2 节点（backend/app/graph/nodes.py，全为 async def）

必须实现节点（最小）：

1. `route_intent`

- 输入：user_query + optional plan_from_client
- 输出：intent（report/diagnose/plan/execute）
- 规则：LLM 分类 + 兜底：
    - 包含 “报表/趋势/GMV/订单数/客单价” → report
    - 包含 “下降/原因/怎么回事/诊断/为什么” → diagnose
    - 包含 “活动/优惠券/预算/策划/方案” → plan
    - 如果请求体里带 `plan` 且动作关键词 “执行/上架/创建/发布” → execute

2. `gen_sql`

- 仅在 report/diagnose 分支运行
- 产出：sql（必须是 SELECT）
- system prompt 包含简化 schema（写死字符串）
- 输出格式严格：只输出 SQL，不要解释/markdown/代码块

3. `guard_sql`

- sqlglot 解析
- 只允许 SELECT
- 拒绝多语句（`;`）
- 强制 `LIMIT <= SQL_MAX_ROWS`（没有 LIMIT 就加；有就取 min）
- 记录 debug.guard

4. `run_sql`

- 异步执行 MySQL（SQLAlchemy Async）
- 超时：SQL_TIMEOUT_SECONDS（用 `asyncio.wait_for` 包装）
- 返回 rows（list[dict]），最多 SQL_MAX_ROWS

5. `retrieve_kb`

- 仅 diagnose/plan 需要
- 从 chroma 检索 top_k=5
- 输出 knowledge（title/content/tags）
- 异步要求：chroma 客户端阻塞 → `anyio.to_thread.run_sync`

6. `compose_report_answer`（场景A）

- 输入 rows + 口径
- 输出 answer + report_payload（columns/rows）
- 口径来源：内置字典或从 KB 里检索到的 metric 文档

7. `compose_diagnosis_answer`（场景B）

- 输入：rows（验证数据）+ knowledge
- 输出：answer（必须包含：发现(data)、原因假设(kb)、验证(data)、下一步(kb+data)）
- 每条结论必须标注来源（例如：`(data)` / `(kb)`）

8. `gen_campaign_plan`（场景C）

- 输入：user_query + knowledge
- 输出：plan（严格 JSON，schema 见下）

9. `execute_campaign`（场景D）

- 输入：plan（来自场景C返回或前端传入）+ optional user_query（补充）
- 动作：
    - 调用 `crm_client.create_coupon(plan.offer, plan.duration_days, ...)`
    - 再调用 `crm_client.publish_coupon(coupon_id)`
    - 写入 `action_logs`（幂等 key：对 plan JSON 做 hash）
- 输出：execution（回执：coupon_id、publish_status、idempotency_key、error）

### 7.3 活动方案 JSON Schema（场景 C）

```json
{
    "goal": "string",
    "duration_days": 7,
    "budget": 30000,
    "target_segment": {
        "definition": "string",
        "rules": ["..."]
    },
    "offer": {
        "type": "full_reduction|discount|points",
        "threshold": 0,
        "value": 0,
        "max_redemptions": 0
    },
    "channels": ["app_push", "sms", "wechat"],
    "kpi": {
        "primary": "repeat_rate",
        "targets": ["..."]
    },
    "risk_controls": ["..."],
    "sql_preview": "optional string: how to estimate target size"
}
```

### 7.4 Graph（backend/app/graph/graph.py）

使用 LangGraph：

- entry：route_intent
- 条件分支：
    - report: gen_sql → guard_sql → run_sql → compose_report_answer → END
    - diagnose: gen_sql → guard_sql → run_sql → retrieve_kb → compose_diagnosis_answer → END
    - plan: retrieve_kb → gen_campaign_plan → END
    - execute: execute_campaign → END

必须提供：

- `get_graph()`：返回编译后的 graph
- `async ainvoke(query, plan=None)`：内部调用 `graph.ainvoke(...)`

---

## 8. DeepSeek LLM 客户端（OpenAI 兼容，异步调用）

实现 `backend/app/llm/deepseek_client.py`：

- 使用 `openai` 的 async client（或 `AsyncOpenAI`），base_url 指向 DeepSeek
- 统一封装：
    - `async chat(...) -> str`
- prompts 集中在 `backend/app/llm/prompts.py`

---

## 9. Mock CRM（同一 FastAPI 内提供 mock endpoints + async 调用）

### 9.1 Mock CRM Routes（backend/app/api/mock_crm_routes.py）

提供接口：

- `POST /mock/crm/coupons`：创建券 → 返回 `{coupon_id}`
- `POST /mock/crm/coupons/{coupon_id}/publish`：发布券 → 返回 `{status:"published"}`
  实现要求：
- 写入 `coupons` 表（创建时 status=draft；发布后 status=published）
- 模拟网络/处理耗时：`await asyncio.sleep(0.1)`（可选）

### 9.2 CRM Client（backend/app/integrations/crm_client.py）

- 用 `httpx.AsyncClient(base_url=CRM_BASE_URL)` 调用上面的 mock 接口
- 必须超时与异常处理（将错误写入 action_logs）

---

## 10. FastAPI 接口（必须清晰）

实现 `backend/app/api/routes.py`：

1. `POST /api/chat`
   请求：

```json
{ "query": "string" }
```

响应（统一格式）：

```json
{
    "intent": "report|diagnose|plan",
    "answer": "string",
    "report": { "columns": ["..."], "rows": [{ "k": "v" }] },
    "plan": { "...": "..." },
    "debug": { "...": "..." }
}
```

2. `POST /api/execute`
   请求（前端从 plan 里直接传）：

```json
{
    "plan": { "...": "..." }
}
```

响应：

```json
{
    "intent": "execute",
    "execution": {
        "idempotency_key": "string",
        "coupon_id": 123,
        "publish_status": "published",
        "error": null
    },
    "debug": { "...": "..." }
}
```

3. `GET /api/health`

- 返回 `{ "ok": true }`

要求：

- 允许 CORS（localhost:5173）
- 所有 handler 均 async
- `/api/chat` 内部使用 LangGraph `ainvoke`

---

## 11. 前端（Vue3）最小要求

页面：单页 Chat

- 一个输入框 + 发送按钮
- 消息列表（用户/助手）
- 助手消息展示：
    - answer 文本
    - 如果有 report：渲染表格
    - 如果有 plan：以卡片展示 JSON，并提供按钮 **“执行上架（场景D）”**
        - 点击后 POST `/api/execute`，请求体带 plan
        - 显示 execution 回执
    - debug：用开关显示（默认隐藏）

预置 4 个示例按钮（点击填充输入框即可）：

- A 示例：`最近7天各门店GMV、客单价、订单数，按天趋势`
- B 示例：`这周复购率下降了，可能原因是什么？用数据验证`
- C 示例：`给高价值老客做一个促复购活动，预算3万，7天`
- D 示例（可选，仅提示用户执行方式）：`（先生成方案，再点“执行上架”）`

---

## 12. 关键实现细节（必须落地）

### 12.1 Schema 提供方式（给 SQL 生成用）

在 `gen_sql` 的 system prompt 中提供简化 schema 文本（写死即可）：

- stores(id, name, city)
- members(id, store_id, created_at, level, total_spent)
- orders(id, store_id, member_id, paid_at, pay_status, channel, amount, original_amount)
- order_items(id, order_id, sku, category, qty, price)

### 12.2 SQL 安全

- sqlglot `parse_one(sql, read='mysql')`
- 仅允许 `exp.Select`
- 拒绝包含 `;`
- 强制 `LIMIT SQL_MAX_ROWS`
- 超时：`asyncio.wait_for(execute_sql(), timeout=SQL_TIMEOUT_SECONDS)`

### 12.3 阻塞库异步化（必须）

- Embedding：`SentenceTransformer.encode` 用 `anyio.to_thread.run_sync`
- Chroma add/query 用 `anyio.to_thread.run_sync`

### 12.4 幂等（场景D必须）

- `idempotency_key = sha256(json.dumps(plan, sort_keys=True))`
- action_logs 先查是否存在同 key 且 success → 直接返回历史回执
- 失败则记录 error_message，允许再次执行

### 12.5 输出可解释性（debug）

debug 至少包含：

- route_intent: raw result
- sql: final sql（report/diagnose）
- guard: {passed, reason, limit_applied}
- timings_ms: {route, gen_sql, run_sql, retrieve_kb, compose, execute}
- model: deepseek model name

---

## 13. Smoke Test（必须提供）

`backend/app/tests/smoke_test.py`（异步运行）：

- 前提：数据库已 seed，知识库已 seed
- 直接调用 graph `ainvoke` 三次 + 执行一次：
    - A：断言 intent=report 且 report.rows 非空
    - B：断言 intent=diagnose 且 answer 含 `(data)` 与 `(kb)` 标注
    - C：断言 intent=plan 且 plan.budget==30000
    - D：调用 execute endpoint 或 execute node：
        - 断言 execution.publish_status=="published"
        - 再次执行同 plan 断言命中幂等（同 idempotency_key）

---

## 14. requirements.txt（必须可安装）

后端 `backend/requirements.txt`（建议）：

- fastapi
- uvicorn[standard]
- sqlalchemy>=2
- aiomysql
- pydantic>=2
- pydantic-settings
- openai
- langgraph
- chromadb
- sentence-transformers
- torch
- sqlglot
- python-dotenv
- faker
- httpx
- anyio

前端：

- vue
- axios
- （可选）echarts

---

## 15. README 必须包含

- 项目简介（A/B/C/D）
- 本地运行步骤（不使用 Docker）
- .env 配置
- 初始化命令（seed db + seed kb）
- 接口示例（curl）
- 前端如何触发 D（生成 plan 后按钮执行）
- 常见报错与处理：
    - MySQL 连接参数不对
    - 本地模型路径不存在
    - torch 安装失败（建议 CPU 版）
    - chroma 目录权限

---

## 16. 提示词（必须写进 prompts.py）

### 16.1 路由分类 system

- 你是意图分类器，只能输出：report / diagnose / plan / execute（单词，小写）

### 16.2 SQL 生成 system（必须严格）

- 你是 MySQL 报表 SQL 生成器
- 只允许 SELECT
- 不要解释，不要 markdown，不要代码块
- 仅输出 SQL

### 16.3 诊断生成 system（输出结构固定）

- 输出四段：
    1. 发现（必须引用 data）
    2. 原因假设（必须引用 kb）
    3. 验证（必须引用 data）
    4. 下一步（引用 kb 或 data）

### 16.4 活动方案生成 system

- 只输出 JSON，必须符合 schema
- 从输入提取预算与周期（默认 budget=30000, duration=7）
- offer 参数必须给出 threshold/value/max_redemptions

### 16.5 执行节点 system（可选）

- 如果 plan 缺字段，允许用极少量 LLM 补齐默认值，但必须写入 debug.plan_fixed=true

---

## 17. 最小 cURL 示例（写进 README）

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"最近7天各门店GMV、客单价、订单数，按天趋势"}'
```

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"这周复购率下降了，可能原因是什么？用数据验证"}'
```

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"给高价值老客做一个促复购活动，预算3万，7天"}'
```

```bash
# 场景D：把上一步返回的 plan 原样贴到这里
curl -X POST http://127.0.0.1:8000/api/execute \
  -H "Content-Type: application/json" \
  -d '{"plan": {}}'
```

---

## 18. 交付标准（完成判定）

满足以下即可判定完成：

1. 后端启动：`GET /api/health` 返回 `{ok:true}`
2. 前端页面能聊天并展示 report/plan/execution
3. 场景 A：返回表格数据（rows>0），answer 有口径说明
4. 场景 B：诊断文本含 `(data)` 与 `(kb)`，且有数据验证
5. 场景 C：返回结构化 JSON plan（字段齐全），预算/周期可从输入解析
6. 场景 D：点击“执行上架”返回 coupon_id 与 published 状态，并写 action_logs；同 plan 重复执行命中幂等
7. 所有调用链路异步：LangGraph 使用 `ainvoke`，阻塞库用 `to_thread` 包装
