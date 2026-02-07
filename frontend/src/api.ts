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

  const parseEventBlock = (block: string) => {
    const normalized = block
      .replace(/\r\n/g, "\n")
      .replace(/\r/g, "\n")
      .replace(/\\n\\n\s*(?=data:)/g, "\n\n");
    const chunks = normalized.split("\n\n");

    for (const chunk of chunks) {
      const lines = chunk.split("\n");
      for (const line of lines) {
        if (!line.startsWith("data:")) continue;
        const raw = line.slice(5).trim();
        const cleaned = raw.replace(/(?:\\n)+$/g, "").trim();
        if (!cleaned) continue;

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
      }
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    // 兼容后端错误输出字面量 "\\n\\n" 的场景，避免事件无法切分
    buffer = buffer.replace(/\\n\\n(?=data:)/g, "\n\n");
    const normalized = buffer.replace(/\r\n/g, "\n");
    const parts = normalized.split("\n\n");
    buffer = parts.pop() || "";

    for (const part of parts) {
      parseEventBlock(part);
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
