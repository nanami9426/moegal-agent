import type { ConversationHistory } from "@/lib/api";

export interface ChatMessageView {
  id: string;
  role: "user" | "assistant";
  content: string;
  pending?: boolean;
  failed?: boolean;
}

export function messagesFromConversations(
  conversations: ConversationHistory[],
): ChatMessageView[] {
  // 聊天页只展示当前活跃会话；历史会话仍可在 /admin 查看。
  const activeConversation = conversations.find((conversation) => conversation.is_active)
    ?? conversations[0];
  if (!activeConversation) {
    return [];
  }

  return activeConversation.messages
    .filter(isVisibleChatMessage)
    .map((message) => ({
      id: String(message.id),
      role: message.role,
      content: message.content || "",
    }));
}

function isVisibleChatMessage(
  message: ConversationHistory["messages"][number],
): message is ConversationHistory["messages"][number] & Pick<ChatMessageView, "role"> {
  return message.role === "user" || message.role === "assistant";
}
