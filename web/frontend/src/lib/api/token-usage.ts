import { getJson } from "./http";
import type { TokenUsageData, TokenUsageQueryParams } from "./types";

export async function fetchTokenUsage(
  params: TokenUsageQueryParams,
  token: string,
): Promise<TokenUsageData> {
  const search = new URLSearchParams({
    platform: params.platform,
    platform_user_id: params.platformUserId,
    recent_limit: String(params.recentLimit),
  });
  return getJson<TokenUsageData>(`/api/token-usage?${search}`, token);
}
