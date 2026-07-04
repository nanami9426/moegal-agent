import { getJson } from "./http";
import type {
  ConversationHistory,
  DashboardData,
  DashboardQueryParams,
  SubscriptionItem,
} from "./types";

export async function fetchDashboardData(
  params: DashboardQueryParams,
  token: string,
): Promise<DashboardData> {
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
