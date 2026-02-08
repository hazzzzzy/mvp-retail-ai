<template>
  <div class="wrap">
    <el-card class="panel" shadow="never">
      <template #header>
        <div class="header">
          <h1>执行日志总览</h1>
          <el-button :loading="loading" @click="load">刷新</el-button>
        </div>
      </template>

      <el-alert
        v-if="summaryText"
        :title="summaryText"
        type="info"
        show-icon
        :closable="false"
        class="summary"
      />

      <div class="metrics">
        <el-card shadow="never">
          <div class="k">总执行数</div>
          <div class="v">{{ metrics.total }}</div>
        </el-card>
        <el-card shadow="never">
          <div class="k">成功数</div>
          <div class="v">{{ metrics.success }}</div>
        </el-card>
        <el-card shadow="never">
          <div class="k">失败数</div>
          <div class="v">{{ metrics.failed }}</div>
        </el-card>
        <el-card shadow="never">
          <div class="k">成功率</div>
          <div class="v">{{ metrics.success_rate.toFixed(2) }}%</div>
        </el-card>
      </div>

      <el-table :data="items" border stripe size="small" max-height="460">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="action_type" label="动作类型" width="130" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'success' ? 'success' : 'danger'">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" min-width="180" />
        <el-table-column prop="idempotency_key" label="幂等键" min-width="280" show-overflow-tooltip />
        <el-table-column prop="request_json" label="请求参数" min-width="160" align="center">
          <template #default="{ row }">
            <el-button
              type="primary"
              link
              :disabled="!row.request_json"
              @click="openRequestDetail(row)"
            >
              显示具体内容
            </el-button>
          </template>
        </el-table-column>
        <el-table-column prop="error_message" label="错误信息" min-width="220" show-overflow-tooltip />
      </el-table>
    </el-card>
  </div>

  <el-dialog
    v-model="detailDialogVisible"
    title="请求参数详情"
    width="900px"
    destroy-on-close
  >
    <el-alert
      v-if="detailParseError"
      type="warning"
      :closable="false"
      show-icon
      title="该字段不是合法 JSON，已按原始文本展示。"
      class="dialog-alert"
    />

    <el-table v-if="detailRows.length" :data="detailRows" border stripe size="small" max-height="420">
      <el-table-column prop="field" label="字段路径" min-width="240" show-overflow-tooltip />
      <el-table-column prop="value" label="字段值" min-width="300">
        <template #default="{ row }">
          <pre class="json-pre">{{ row.value }}</pre>
        </template>
      </el-table-column>
      <el-table-column prop="meaning" label="字段含义" min-width="220" show-overflow-tooltip />
    </el-table>

    <el-empty v-else description="无可展示字段" />
  </el-dialog>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getActionLogsSummary, type ActionLogSummary } from "../api";

const loading = ref(false);
const summaryText = ref("");
const metrics = ref<ActionLogSummary["metrics"]>({
  total: 0,
  success: 0,
  failed: 0,
  success_rate: 0,
  last_created_at: null
});
const items = ref<ActionLogSummary["items"]>([]);
const detailDialogVisible = ref(false);
const detailRows = ref<Array<{ field: string; value: string; meaning: string }>>([]);
const detailParseError = ref(false);

const fieldMeaningMap: Record<string, string> = {
  query: "用户输入的问题文本",
  plan: "待执行的方案对象",
  action_type: "执行动作类型",
  idempotency_key: "幂等键，用于防止重复执行",
  member_id: "会员ID",
  store_id: "门店ID",
  product_id: "商品ID",
  campaign_id: "活动ID",
  budget: "预算金额",
  start_date: "开始日期",
  end_date: "结束日期",
  channel: "投放渠道",
  reason: "原因说明",
  payload: "请求载荷主体",
  params: "请求参数对象",
  filters: "过滤条件",
  sql: "生成的SQL语句"
};

function inferFieldMeaning(path: string): string {
  const key = path.split(".").pop() || path;
  return fieldMeaningMap[key] || "业务请求字段";
}

function primitiveToString(v: unknown): string {
  if (v === null) return "null";
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v, null, 2);
}

function flattenJson(
  value: unknown,
  basePath = "",
  output: Array<{ field: string; value: string; meaning: string }> = []
) {
  if (value === null || typeof value !== "object") {
    output.push({
      field: basePath || "$",
      value: primitiveToString(value),
      meaning: inferFieldMeaning(basePath || "$")
    });
    return output;
  }

  if (Array.isArray(value)) {
    if (!value.length) {
      output.push({
        field: basePath || "$",
        value: "[]",
        meaning: inferFieldMeaning(basePath || "$")
      });
      return output;
    }
    value.forEach((item, idx) => {
      const path = basePath ? `${basePath}[${idx}]` : `[${idx}]`;
      flattenJson(item, path, output);
    });
    return output;
  }

  const entries = Object.entries(value as Record<string, unknown>);
  if (!entries.length) {
    output.push({
      field: basePath || "$",
      value: "{}",
      meaning: inferFieldMeaning(basePath || "$")
    });
    return output;
  }

  for (const [k, v] of entries) {
    const path = basePath ? `${basePath}.${k}` : k;
    if (v !== null && typeof v === "object") {
      flattenJson(v, path, output);
    } else {
      output.push({
        field: path,
        value: primitiveToString(v),
        meaning: inferFieldMeaning(path)
      });
    }
  }
  return output;
}

function openRequestDetail(row: ActionLogSummary["items"][number]) {
  detailRows.value = [];
  detailParseError.value = false;
  if (!row.request_json) {
    detailDialogVisible.value = true;
    return;
  }

  try {
    const parsed = JSON.parse(row.request_json);
    detailRows.value = flattenJson(parsed);
  } catch {
    detailParseError.value = true;
    detailRows.value = [
      {
        field: "raw",
        value: row.request_json,
        meaning: "原始请求文本"
      }
    ];
  }
  detailDialogVisible.value = true;
}

async function load() {
  loading.value = true;
  try {
    const data = await getActionLogsSummary(30);
    summaryText.value = data.summary || "";
    metrics.value = data.metrics;
    items.value = data.items || [];
  } catch (error: any) {
    ElMessage.error(`加载日志失败: ${error.message}`);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.wrap {
  max-width: 1180px;
  margin: 0 auto;
  padding: 16px;
  height: 100%;
  overflow: hidden;
}

.panel {
  height: 100%;
  display: flex;
  flex-direction: column;
}

:deep(.el-card__body) {
  height: calc(100% - 65px);
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: hidden;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header h1 {
  margin: 0;
  font-size: 20px;
}

.summary {
  flex-shrink: 0;
}

.metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(120px, 1fr));
  gap: 10px;
  flex-shrink: 0;
}

.k {
  font-size: 12px;
  color: #64748b;
}

.v {
  margin-top: 4px;
  font-size: 22px;
  font-weight: 700;
  color: #0f172a;
}

.json-pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.4;
}

.dialog-alert {
  margin-bottom: 10px;
}
</style>
