import {
  apiBaseUrl,
  buildHeaders,
  deleteJson,
  getJson,
  patchJson,
  postJson,
} from "./http";
import type {
  ConversationHistory,
  MemoryItem,
  MemorySettings,
} from "./types";

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
  temporary = false,
  temporaryThreadId?: string,
): Promise<string> {
  const response = await fetch(`${apiBaseUrl}/api/web-chat/messages/stream`, {
    method: "POST",
    headers: buildHeaders(token, { message, temporary, temporary_thread_id: temporaryThreadId }),
    body: JSON.stringify({ message, temporary, temporary_thread_id: temporaryThreadId }),
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

export async function fetchWebMemories(token: string): Promise<MemoryItem[]> {
  const payload = await getJson<{ memories: MemoryItem[] }>(
    "/api/web-chat/memories?limit=50",
    token,
  );
  return payload.memories;
}

export function fetchMemorySettings(token: string): Promise<MemorySettings> {
  return getJson<MemorySettings>("/api/web-chat/memory-settings", token);
}

export function updateMemorySettings(
  token: string,
  updates: Partial<Pick<MemorySettings, "enabled" | "auto_extract" | "use_chat_history">>,
): Promise<MemorySettings> {
  return patchJson<MemorySettings>("/api/web-chat/memory-settings", updates, token);
}

export function updateWebMemory(
  token: string,
  memoryId: number,
  updates: Pick<MemoryItem, "content">,
): Promise<MemoryItem> {
  return patchJson<MemoryItem>(`/api/web-chat/memories/${memoryId}`, updates, token);
}

export function deleteWebMemory(token: string, memoryId: number): Promise<{ deleted: boolean }> {
  return deleteJson<{ deleted: boolean }>(`/api/web-chat/memories/${memoryId}`, token);
}

export function clearWebMemories(token: string): Promise<{ deleted_count: number }> {
  return deleteJson<{ deleted_count: number }>("/api/web-chat/memories", token);
}
