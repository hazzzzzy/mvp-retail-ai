<template>
  <div class="wrap">
    <el-card class="shell" shadow="never">
      <template #header>
        <div class="header">
          <h1>门店经营助手 AI</h1>
        </div>
      </template>

      <div class="examples">
        <el-button v-for="s in samples" :key="s" text bg @click="input = s">{{
          s
        }}</el-button>
      </div>

      <div ref="messagesPanelRef" class="messages-panel">
        <MessageList :messages="messages" @execute="onExecute" />
      </div>

      <div class="input-row">
        <el-input
          v-model="input"
          placeholder="请输入问题..."
          :disabled="loading"
          @keyup.enter="onSend"
        />
        <el-button type="primary" :loading="loading" @click="onSend"
          >发送</el-button
        >
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref } from "vue";
import { ElMessage } from "element-plus";
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
const messagesPanelRef = ref<HTMLElement | null>(null);
let scrollRaf = 0;

function scrollMessagesToBottom() {
  if (scrollRaf) return;
  scrollRaf = window.requestAnimationFrame(async () => {
    await nextTick();
    const panel = messagesPanelRef.value;
    if (panel) {
      panel.scrollTop = panel.scrollHeight;
    }
    scrollRaf = 0;
  });
}

const samples = [
  "最近7天各门店GMV",
  "这周复购率下降了，可能原因是什么？用数据验证",
  "给高价值老客做一个促复购活动，预算3万，7天",
];

async function onSend() {
  const query = input.value.trim();
  if (!query || loading.value) return;

  loading.value = true;
  messages.value.push({ role: "user", text: query });
  messages.value.push({ role: "assistant", text: "" });
  scrollMessagesToBottom();
  const assistantIndex = messages.value.length - 1;

  try {
    await chatStream(query, {
      onToken: (token) => {
        const current = messages.value[assistantIndex];
        current.text = (current.text || "") + token;
        scrollMessagesToBottom();
      },
      onDone: (result) => {
        const current = messages.value[assistantIndex];
        current.text = result.answer ?? current.text;
        current.report = result.report;
        current.plan = result.plan;
        current.debug = result.debug;
        scrollMessagesToBottom();
      },
      onError: (message) => {
        const current = messages.value[assistantIndex];
        current.text = `请求失败: ${message}`;
        scrollMessagesToBottom();
      },
    });
  } catch (error: any) {
    const current = messages.value[assistantIndex];
    current.text = `请求失败: ${error.message}`;
    ElMessage.error(`请求失败: ${error.message}`);
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
      debug: resp.debug,
    });
    scrollMessagesToBottom();
    ElMessage.success("执行完成");
  } catch (error: any) {
    messages.value.push({
      role: "assistant",
      text: `执行失败: ${error.message}`,
    });
    scrollMessagesToBottom();
    ElMessage.error(`执行失败: ${error.message}`);
  }
}
</script>

<style scoped>
.wrap {
  max-width: 1100px;
  margin: 0 auto;
  padding: 16px;
  height: 100%;
  overflow: hidden;
}

.shell {
  height: 100%;
  display: flex;
  flex-direction: column;
}

:deep(.el-card__body) {
  height: calc(100% - 65px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.header h1 {
  margin: 0;
  font-size: 20px;
}

.examples {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.messages-panel {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
}

.input-row {
  margin-top: 12px;
  display: grid;
  grid-template-columns: 1fr 100px;
  gap: 8px;
}
</style>
