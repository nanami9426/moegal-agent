export type Platform = "web" | "tg" | "qq";
export type ChatRole = "user" | "assistant";

export interface SubscriptionItem {
  id: number;
  type: string;
  target: string;
  display_name: string | null;
  delivery_mode: string;
  created_at: string;
  updated_at: string;
  last_checked_at: string | null;
}

export interface MessageItem {
  id: number;
  role: string;
  content: string | null;
  created_at: string;
}

export interface ConversationHistory {
  id: number;
  version: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  ended_at: string | null;
  messages: MessageItem[];
}

export interface DashboardData {
  subscriptions: SubscriptionItem[];
  conversations: ConversationHistory[];
}

export interface PlatformBindingItem {
  id: number;
  platform: Platform;
  platform_user_id: string;
  username: string | null;
  display_name: string | null;
  bound_at: string;
}

export interface AdminBindingsResponse {
  bindings: PlatformBindingItem[];
  max_per_platform: number;
}

export interface LinkCode {
  code: string;
  expires_at: string;
}

export interface WebUser {
  id: number;
  username: string;
}

export interface AuthResponse {
  token: string;
  user: WebUser;
}

export interface QueryParams {
  platform: Platform;
  platformUserId: string;
  conversationLimit: number;
  messageLimit: number;
}

const apiBaseUrl = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL);

export async function fetchDashboardData(params: QueryParams, token: string): Promise<DashboardData> {
  const search = new URLSearchParams({
    platform: params.platform,
    platform_user_id: params.platformUserId,
  });
  const chatSearch = new URLSearchParams(search);
  chatSearch.set("conversation_limit", String(params.conversationLimit));
  chatSearch.set("message_limit", String(params.messageLimit));

  const [subscriptions, chatHistory] = await Promise.all([
    getJson<{ subscriptions: SubscriptionItem[] }>(`/api/subscriptions?${search}`, token),
    getJson<{ conversations: ConversationHistory[] }>(`/api/chat-history?${chatSearch}`, token),
  ]);

  return {
    subscriptions: subscriptions.subscriptions,
    conversations: chatHistory.conversations,
  };
}

export async function fetchAdminBindings(token: string): Promise<AdminBindingsResponse> {
  return getJson<AdminBindingsResponse>("/api/admin/bindings", token);
}

export async function issueLinkCode(token: string): Promise<LinkCode> {
  return postJson<LinkCode>("/api/admin/link-codes", undefined, token);
}

export async function registerWebUser(username: string, password: string): Promise<AuthResponse> {
  return postJson<AuthResponse>("/api/auth/register", {
    username,
    password,
  });
}

export async function loginWebUser(userId: string, password: string): Promise<AuthResponse> {
  return postJson<AuthResponse>("/api/auth/login", {
    user_id: userId,
    password,
  });
}

export async function fetchCurrentWebUser(token: string): Promise<WebUser> {
  const payload = await getJson<{ user: WebUser }>("/api/auth/me", token);
  return payload.user;
}

export async function logoutWebUser(token: string): Promise<void> {
  await postJson<{ revoked: boolean }>("/api/auth/logout", undefined, token);
}

export async function fetchWebChatHistory(token: string): Promise<ConversationHistory[]> {
  const payload = await getJson<{ conversations: ConversationHistory[] }>(
    "/api/web-chat/history?conversation_limit=10&message_limit=100",
    token,
  );
  return payload.conversations;
}

export async function sendWebChatMessage(token: string, message: string): Promise<string> {
  const payload = await postJson<{ reply: string }>(
    "/api/web-chat/messages",
    { message },
    token,
  );
  return payload.reply;
}

export async function startNewWebChat(token: string): Promise<{ created: boolean; message: string }> {
  return postJson<{ created: boolean; message: string }>("/api/web-chat/new", undefined, token);
}

async function getJson<T>(path: string, token?: string): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    headers: buildHeaders(token),
  });
  return parseJsonResponse<T>(response);
}

async function postJson<T>(path: string, body?: unknown, token?: string): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method: "POST",
    headers: buildHeaders(token, body),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return parseJsonResponse<T>(response);
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
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
  return response.json() as Promise<T>;
}

function buildHeaders(token?: string, body?: unknown): HeadersInit {
  // Web 聊天和管理后台都用 Bearer token，后端再按绑定关系做数据隔离。
  const headers: Record<string, string> = {};
  if (body !== undefined) {
    headers["content-type"] = "application/json";
  }
  if (token) {
    headers.authorization = `Bearer ${token}`;
  }
  return headers;
}

function normalizeBaseUrl(value: string | undefined): string {
  if (!value) {
    return "";
  }
  return value.replace(/\/$/, "");
}
