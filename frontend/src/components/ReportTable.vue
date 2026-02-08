<template>
  <div v-if="report.rows.length" class="table-wrap">
    <el-table :data="report.rows" border stripe size="small" max-height="360">
      <el-table-column
        v-for="c in report.columns"
        :key="c"
        :prop="c"
        :label="toZhLabel(c)"
        min-width="120"
        show-overflow-tooltip
      />
    </el-table>
  </div>
</template>

<script setup lang="ts">
defineProps<{ report: { columns: string[]; rows: Record<string, any>[] } }>();

const COLUMN_LABEL_MAP: Record<string, string> = {
  date: "日期",
  day: "日期",
  month: "月份",
  week: "周",
  store_id: "门店ID",
  store_name: "门店",
  gmv: "GMV",
  total_amount: "销售额",
  amount: "金额",
  avg_order_amount: "客单价",
  unit_price: "客单价",
  order_count: "订单数",
  success_order_count: "成功订单数",
  pay_order_count: "支付订单数",
  member_count: "会员数",
  user_count: "用户数",
  new_user_count: "新客数",
  old_user_count: "老客数",
  repurchase_count: "复购人数",
  repurchase_rate: "复购率",
  conversion_rate: "转化率",
  channel: "渠道",
  category: "品类",
  sku: "商品",
  coupon_count: "发券数",
  redeem_count: "核销数",
  roi: "ROI"
};

function toZhLabel(column: string): string {
  const key = (column || "").trim();
  if (!key) return "字段";
  if (COLUMN_LABEL_MAP[key]) return COLUMN_LABEL_MAP[key];
  // 兜底：snake_case/camelCase 转可读中文风格标题
  return key
    .replace(/([a-z])([A-Z])/g, "$1_$2")
    .split("_")
    .filter(Boolean)
    .map((x) => x.toUpperCase())
    .join(" ");
}
</script>

<style scoped>
.table-wrap {
  margin-top: 10px;
}
</style>
