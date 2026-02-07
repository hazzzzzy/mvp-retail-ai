# 门店经营助手 AI MVP（本地异步版）

## 1. 项目简介
本项目实现 4 个场景：
- A：一句话出报表（Text-to-SQL）
- B：业务诊断（数据 + RAG）
- C：自动生成活动方案（结构化 JSON）
- D：一键上架（调用 mock CRM，含幂等）

后端技术：FastAPI async、SQLAlchemy async、LangGraph `ainvoke`、DeepSeek、Chroma、本地 bge-base-zh-v1.5。  
前端技术：Vue3 + Vite 单页 Chat。

## 2. 目录结构
- `backend/` 后端
- `frontend/` 前端
- `backend/models/bge-base-zh-v1.5` 本地 embedding 模型

## 3. 环境变量
复制并填写：
```bash
cd backend
cp .env.example .env
```
关键变量：
- `MYSQL_HOST` `MYSQL_PORT` `MYSQL_DB` `MYSQL_USER` `MYSQL_PASSWORD`
- `DEEPSEEK_API_KEY` `DEEPSEEK_BASE_URL` `DEEPSEEK_MODEL`
- `CHROMA_DIR`
- `EMBED_MODEL_PATH=./models/bge-base-zh-v1.5`

## 4. 本地运行（不使用 Docker）
### 4.1 准备数据库
```bash
mysql -uroot -proot -e "CREATE DATABASE IF NOT EXISTS mvp_retail_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

### 4.2 启动后端
```bash
cd backend
python -m venv .venv
# Windows
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m app.db.seed
python -m app.rag.kb_seed
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 4.3 启动前端
```bash
cd frontend
npm i
npm run dev -- --host 127.0.0.1 --port 5173
```

访问地址：
- 前端：`http://127.0.0.1:5173`
- 后端：`http://127.0.0.1:8000`

## 5. 接口示例（curl）
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
curl -X POST http://127.0.0.1:8000/api/execute \
  -H "Content-Type: application/json" \
  -d '{"plan": {}}'
```

## 6. 前端触发场景 D
在前端先发起场景 C 获取 `plan`，然后点击方案卡片上的“执行上架（场景D）”按钮。

## 7. 冒烟测试
先确保后端已启动：
```bash
cd backend
.\.venv\Scripts\python -m app.tests.smoke_test
```

## 8. 常见报错与处理
- MySQL 连接失败：检查 `.env` 中账号密码、数据库名、服务是否启动
- 本地模型路径不存在：检查 `backend/models/bge-base-zh-v1.5`
- torch 安装失败：先升级 pip，必要时改用 CPU 轮子源
- chroma 目录权限错误：检查 `CHROMA_DIR` 目录读写权限
