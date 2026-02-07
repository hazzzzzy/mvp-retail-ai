<template>
  <div class="wrap">
    <h1>门店经营助手 AI</h1>
    <div class="examples">
      <button v-for="s in samples" :key="s" @click="input = s">{{ s }}</button>
    </div>

    <div class="messages-panel">
      <MessageList :messages="messages" @execute="onExecute" />
    </div>

    <div class="input-row">
      <input v-model="input" placeholder="请输入问题..." @keyup.enter="onSend" />
      <button :disabled="loading" @click="onSend">发送</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { chatStream, executePlan } from "../api";
import MessageList from "../components/MessageList.vue";

type Msg = {
  role: "user" | "assistant";
  text?: string;
  report?: { columns: string[]; rows: Record<string, unknown>[] };
  plan?: Record<string, unknown>;
  execution?: Record<string, unknown>;
  debug?: Record<string, unknown>;
};

const input = ref("");
const loading = ref(false);
const messages = ref<Msg[]>([]);

const samples = [
  "最近7天各门店GMV、客单价、订单数，按天趋势",
  "这周复购率下降了，可能原因是什么？用数据验证",
  "给高价值老客做一个促复购活动，预算3万，7天",
  "（先生成方案，再点“执行上架”）"
];

async function onSend() {
  const query = input.value.trim();
  if (!query || loading.value) return;

  loading.value = true;
  messages.value.push({ role: "user", text: query });
  messages.value.push({ role: "assistant", text: "" });
  const assistantIndex = messages.value.length - 1;

  try {
    await chatStream(query, {
      onToken: (token) => {
        const current = messages.value[assistantIndex];
        current.text = (current.text || "") + token;
      },
      onDone: (result) => {
        const current = messages.value[assistantIndex];
        current.text = result.answer ?? current.text;
        current.report = result.report;
        current.plan = result.plan;
        current.debug = result.debug;
      },
      onError: (message) => {
        const current = messages.value[assistantIndex];
        current.text = `请求失败: ${message}`;
      }
    });
  } catch (error: any) {
    const current = messages.value[assistantIndex];
    current.text = `请求失败: ${error.message}`;
  } finally {
    input.value = "";
    loading.value = false;
  }
}

async function onExecute(plan: Record<string, unknown>) {
  try {
    const resp = await executePlan(plan);
    messages.value.push({
      role: "assistant",
      text: "执行完成",
      execution: resp.execution,
      debug: resp.debug
    });
  } catch (error: any) {
    messages.value.push({ role: "assistant", text: `执行失败: ${error.message}` });
  }
}
</script>

<style scoped>
.wrap {
  max-width: 1000px;
  margin: 0 auto;
  padding: 24px;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

h1 {
  margin: 0 0 16px;
}

.examples {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px;
  margin: 0 0 16px;
}

.examples button {
  border: 1px solid #cbd5e1;
  background: #fff;
  border-radius: 10px;
  padding: 10px;
  cursor: pointer;
  text-align: left;
}

.messages-panel {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
}

.input-row {
  display: flex;
  gap: 8px;
  margin-top: 16px;
  padding: 12px 0 0;
  background: #f8fafccc;
  backdrop-filter: blur(6px);
}

.input-row input {
  flex: 1;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 12px;
}

.input-row button {
  border: none;
  background: #0f766e;
  color: #fff;
  border-radius: 10px;
  padding: 0 18px;
  cursor: pointer;
}
</style>
