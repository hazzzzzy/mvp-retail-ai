<template>
  <div class="list">
    <div v-for="(m, idx) in messages" :key="idx" :class="['item', m.role]">
      <div class="role">{{ m.role === "user" ? "你" : "助手" }}</div>
      <div v-if="m.text" class="text markdown-body" v-html="toHtml(m.text)"></div>
      <ReportTable v-if="m.report" :report="m.report" />
      <PlanCard v-if="m.plan" :plan="m.plan" @execute="$emit('execute', m.plan)" />
      <div v-if="m.execution" class="text markdown-body" v-html="toHtml(executionText(m.execution))"></div>
      <details v-if="m.debug">
        <summary>debug</summary>
        <pre class="json">{{ JSON.stringify(m.debug, null, 2) }}</pre>
      </details>
    </div>
  </div>
</template>

<script setup lang="ts">
import PlanCard from "./PlanCard.vue";
import ReportTable from "./ReportTable.vue";
import { renderMarkdown } from "../utils/markdown";

defineProps<{ messages: any[] }>();
defineEmits<{ (e: "execute", plan: Record<string, unknown>): void }>();

function toHtml(text: string): string {
  return renderMarkdown(text || "");
}

function executionText(execution: Record<string, unknown>): string {
  return [
    "### 执行结果",
    `- 状态：${execution.publish_status ?? "unknown"}`,
    `- 优惠券ID：${execution.coupon_id ?? "-"}`,
    `- 幂等键：${execution.idempotency_key ?? "-"}`,
    execution.error ? `- 错误：${execution.error}` : "- 错误：无"
  ].join("\n");
}
</script>

<style scoped>
.list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.item {
  border: 1px solid #d1d5db;
  border-radius: 12px;
  padding: 12px;
  background: #fff;
}

.item.user {
  border-color: #0f766e;
}

.role {
  font-weight: 600;
  margin-bottom: 6px;
}

.text {
  line-height: 1.65;
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) {
  margin: 8px 0;
}

.markdown-body :deep(p),
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 6px 0;
}

.json {
  background: #f8fafc;
  border-radius: 8px;
  padding: 8px;
  overflow: auto;
}
</style>
