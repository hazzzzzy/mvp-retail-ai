<template>
  <div v-if="report.rows.length" class="table-wrap">
    <table>
      <thead>
        <tr>
          <th v-for="c in report.columns" :key="c">{{ c }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(r, idx) in report.rows" :key="idx">
          <td v-for="c in report.columns" :key="c">{{ r[c] }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
defineProps<{ report: { columns: string[]; rows: Record<string, any>[] } }>();
</script>

<style scoped>
.table-wrap {
  margin-top: 10px;
  overflow: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th, td {
  border: 1px solid #e5e7eb;
  padding: 6px;
  font-size: 12px;
}
</style>
