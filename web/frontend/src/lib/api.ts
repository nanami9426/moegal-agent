export type Platform = "tg" | "qq";

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

export interface QueryParams {
  platform: Platform;
  platformUserId: string;
  conversationLimit: number;
  messageLimit: number;
}

const apiBaseUrl = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL);

export async function fetchDashboardData(params: QueryParams): Promise<DashboardData> {
  const search = new URLSearchParams({
    platform: params.platform,
    platform_user_id: params.platformUserId,
  });
  const chatSearch = new URLSearchParams(search);
  chatSearch.set("conversation_limit", String(params.conversationLimit));
  chatSearch.set("message_limit", String(params.messageLimit));

  const [subscriptions, chatHistory] = await Promise.all([
    getJson<{ subscriptions: SubscriptionItem[] }>(`/api/subscriptions?${search}`),
    getJson<{ conversations: ConversationHistory[] }>(`/api/chat-history?${chatSearch}`),
  ]);

  return {
    subscriptions: subscriptions.subscriptions,
    conversations: chatHistory.conversations,
  };
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") {
        detail = payload.detail;
      }
    } catch {
      // Fall back to HTTP status text.
    }
    throw new Error(`请求失败：${response.status} ${detail}`);
  }
  return response.json() as Promise<T>;
}

function normalizeBaseUrl(value: string | undefined): string {
  if (!value) {
    return "";
  }
  return value.replace(/\/$/, "");
}
