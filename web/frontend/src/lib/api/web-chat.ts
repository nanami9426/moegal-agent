import { apiBaseUrl, buildHeaders, getJson, postJson } from "./http";
import type { ConversationHistory } from "./types";

export async function fetchWebChatHistory(token: string): Promise<ConversationHistory[]> {
  const payload = await getJson<{ conversations: ConversationHistory[] }>(
    "/api/web-chat/history?conversation_limit=10&message_limit=100",
    token,
  );
  return payload.conversations;
}

export async function streamWebChatMessage(
  token: string,
  message: string,
  onDelta: (delta: string) => void,
): Promise<string> {
  const response = await fetch(`${apiBaseUrl}/api/web-chat/messages/stream`, {
    method: "POST",
    headers: buildHeaders(token, { message }),
    body: JSON.stringify({ message }),
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") {
        detail = payload.detail;
      }
    } catch {
      // 响应体不是 JSON 时退回使用 HTTP 状态文本。
    }
    throw new Error(`请求失败：${response.status} ${detail}`);
  }
  if (!response.body) {
    throw new Error("浏览器不支持流式响应。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalReply = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      let eventName = "message";
      const dataLines: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) {
          eventName = line.slice("event:".length).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice("data:".length).trimStart());
        }
      }
      if (dataLines.length > 0) {
        const eventData = JSON.parse(dataLines.join("\n")) as Record<string, string>;
        if (eventName === "error") {
          throw new Error(eventData.detail || "发送失败，请稍后再试。");
        }
        if (eventData.delta) {
          onDelta(eventData.delta);
        }
        if (eventName === "done") {
          finalReply = eventData.reply || finalReply;
        }
      }
      boundary = buffer.indexOf("\n\n");
    }

    if (done) {
      break;
    }
  }

  return finalReply;
}

export async function startNewWebChat(token: string): Promise<{ created: boolean; message: string }> {
  return postJson<{ created: boolean; message: string }>("/api/web-chat/new", undefined, token);
}
