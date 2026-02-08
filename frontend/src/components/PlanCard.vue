<template>
  <el-card class="plan-card" shadow="never">
    <template #header>
      <div class="head">
        <strong>活动方案</strong>
        <el-button type="success" @click="$emit('execute')">执行上架（场景D）</el-button>
      </div>
    </template>
    <div class="content markdown-body" v-html="planSummaryHtml"></div>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { renderMarkdown } from "../utils/markdown";

const props = defineProps<{ plan: Record<string, any> }>();
defineEmits<{ (e: "execute"): void }>();

const planSummaryHtml = computed(() => {
  const p = props.plan || {};
  const target = p.target_segment || {};
  const offer = p.offer || {};
  const kpi = p.kpi || {};
  const channels = Array.isArray(p.channels) ? p.channels.join("、") : "App Push、短信、企业微信";
  const rules = Array.isArray(target.rules) && target.rules.length ? target.rules.slice(0, 4).map((x: string) => `- ${x}`).join("\n") : "- 近30天高价值老客";
  const targets = Array.isArray(kpi.targets) && kpi.targets.length ? kpi.targets.slice(0, 3).map((x: string) => `- ${x}`).join("\n") : "- 7天复购率提升";

  const md = [
    `### 目标与预算`,
    `- 目标：${p.goal || "提升复购"}`,
    `- 周期：${p.duration_days || 7} 天`,
    `- 预算：${p.budget || 30000} 元`,
    "",
    `### 人群策略`,
    `- 人群定义：${target.definition || "近30天高价值老客"}`,
    rules,
    "",
    `### 优惠策略`,
    `- 类型：${offer.type || "full_reduction"}`,
    `- 门槛：满 ${offer.threshold || 99} 元`,
    `- 面额/折扣：${offer.value || 20}`,
    `- 发放上限：${offer.max_redemptions || 1000}`,
    `- 触达渠道：${channels}`,
    "",
    `### KPI`,
    `- 主指标：${kpi.primary || "repeat_rate"}`,
    targets
  ].join("\n");

  return renderMarkdown(md);
});
</script>

<style scoped>
.plan-card {
  margin-top: 10px;
}

.head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.content {
  line-height: 1.65;
}

.markdown-body :deep(h3) {
  margin: 8px 0;
}

.markdown-body :deep(ul),
.markdown-body :deep(p) {
  margin: 6px 0;
}
</style>
