export type Platform = "web" | "tg" | "qq";

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

export interface TokenUsageSummary {
  request_count: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  average_elapsed_ms: number;
  latest_created_at: string | null;
}

export interface TokenUsageByModelItem {
  model: string;
  request_count: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface TokenUsageRecordItem {
  id: number;
  model: string;
  request_path: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  status_code: number;
  elapsed_ms: number;
  created_at: string;
}

export interface TokenUsageData {
  summary: TokenUsageSummary;
  by_model: TokenUsageByModelItem[];
  recent: TokenUsageRecordItem[];
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

export interface MemoryItem {
  id: number;
  namespace: string;
  kind: string;
  key: string;
  content: string;
  source: string;
  confidence: number;
  importance: number;
  expires_at: string | null;
  last_accessed_at: string | null;
  access_count: number;
  created_at: string;
  updated_at: string;
}

export interface MemorySettings {
  enabled: boolean;
  auto_extract: boolean;
  use_chat_history: boolean;
  updated_at: string;
}

export interface DashboardQueryParams {
  platform: Platform;
  platformUserId: string;
  conversationLimit: number;
  messageLimit: number;
}

export interface TokenUsageQueryParams {
  platform: Platform;
  platformUserId: string;
  recentLimit: number;
}
