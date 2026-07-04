import { toast } from "sonner";

import type { DashboardData, Platform } from "@/lib/api";
import { formatPlatform } from "@/lib/format";

export function showResourceToast(
  platform: Platform,
  platformUserId: string,
  payload: DashboardData,
) {
  const hasSubscriptions = payload.subscriptions.length > 0;
  const hasConversations = payload.conversations.length > 0;

  if (!hasSubscriptions && !hasConversations) {
    toast.warning("未找到对应用户或资源", {
      description: `${formatPlatform(platform)} / ${platformUserId} 没有启用订阅或聊天记录。`,
    });
    return;
  }

  if (!hasSubscriptions) {
    toast.info("没有启用订阅", {
      description: `${formatPlatform(platform)} / ${platformUserId} 暂无订阅资源。`,
    });
  }

  if (!hasConversations) {
    toast.info("没有聊天记录", {
      description: `${formatPlatform(platform)} / ${platformUserId} 暂无会话资源。`,
    });
  }
}
