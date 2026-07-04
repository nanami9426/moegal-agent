import {
  Bot,
  RefreshCcw,
  User,
} from "lucide-react";

import { cn } from "@/lib/utils";

import type { ChatMessageView } from "./chatMessages";
import { MarkdownMessage } from "./MarkdownMessage";

export function ChatBubble({ message }: { message: ChatMessageView }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex gap-3", isUser && "flex-row-reverse")}>
      <div
        className={cn(
          "flex h-9 w-9 shrink-0 items-center justify-center border-2 border-foreground",
          isUser ? "bg-primary text-primary-foreground" : "bg-accent text-accent-foreground",
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>
      <div
        className={cn(
          "max-w-[min(720px,calc(100%-3rem))] border-2 border-foreground px-4 py-3 shadow-[3px_3px_0_hsl(var(--foreground))]",
          isUser ? "bg-primary text-primary-foreground" : "bg-background",
          message.failed && "bg-destructive text-destructive-foreground",
        )}
      >
        {message.pending && !message.content ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <RefreshCcw className="h-3.5 w-3.5 animate-spin" />
            生成中
          </div>
        ) : isUser || message.failed ? (
          <p className="whitespace-pre-wrap break-words text-sm leading-6">
            {message.content}
            {message.pending ? (
              <RefreshCcw className="ml-2 inline h-3.5 w-3.5 animate-spin text-muted-foreground" />
            ) : null}
          </p>
        ) : (
          <>
            <MarkdownMessage content={message.content} />
            {message.pending ? (
              <RefreshCcw className="ml-2 mt-2 inline h-3.5 w-3.5 animate-spin text-muted-foreground" />
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
