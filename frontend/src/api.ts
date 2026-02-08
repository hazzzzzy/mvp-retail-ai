import axios from "axios";

const baseURL = "http://127.0.0.1:8000";

const client = axios.create({
  baseURL,
  timeout: 30000
});

type ChatDonePayload = {
  intent?: string;
  answer?: string;
  report?: { columns: string[]; rows: Record<string, unknown>[] };
  plan?: Record<string, unknown>;
  debug?: Record<string, unknown>;
};

export type ActionLogSummary = {
  summary: string;
  metrics: {
    total: number;
    success: number;
    failed: number;
    success_rate: number;
    last_created_at: string | null;
  };
  items: Array<{
    id: number;
    idempotency_key: string;
    action_type: string;
    status: string;
    request_json: string | null;
    error_message: string | null;
    created_at: string;
  }>;
};

export async function chat(query: string) {
  const { data } = await client.post("/api/chat", { query });
  return data;
}

export async function chatStream(
  query: string,
  handlers: {
    onToken?: (token: string) => void;
    onDone?: (result: ChatDonePayload) => void;
    onError?: (message: string) => void;
  } = {}
) {
  const response = await fetch(`${baseURL}/api/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream"
    },
    body: JSON.stringify({ query })
  });

  if (!response.ok || !response.body) {
    throw new Error(`流式请求失败: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  const dispatchEvent = (payload: string) => {
    const cleaned = payload.trim();
    if (!cleaned) return;
    try {
      const event = JSON.parse(cleaned) as
        | { type: "start" }
        | { type: "token"; content: string }
        | { type: "done"; result: ChatDonePayload }
        | { type: "error"; message: string };

      if (event.type === "token") handlers.onToken?.(event.content || "");
      if (event.type === "done") handlers.onDone?.(event.result || {});
      if (event.type === "error") handlers.onError?.(event.message || "未知错误");
    } catch {
      // 容错：忽略单条坏事件，继续消费后续流。
    }
  };

  const parseEventBlock = (block: string) => {
    const lines = block.split("\n");
    const dataLines: string[] = [];
    for (const line of lines) {
      if (!line.startsWith("data:")) continue;
      dataLines.push(line.slice(5).trimStart());
    }
    if (!dataLines.length) return;
    dispatchEvent(dataLines.join("\n"));
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    buffer = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

    while (true) {
      const sep = buffer.indexOf("\n\n");
      if (sep < 0) break;
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      parseEventBlock(block);
    }
  }

  if (buffer.trim()) {
    parseEventBlock(buffer);
  }
}

export async function executePlan(plan: Record<string, unknown>) {
  const { data } = await client.post("/api/execute", { plan });
  return data;
}

export async function getActionLogsSummary(limit = 20): Promise<ActionLogSummary> {
  const { data } = await client.get("/api/action-logs/summary", { params: { limit } });
  return data;
}
