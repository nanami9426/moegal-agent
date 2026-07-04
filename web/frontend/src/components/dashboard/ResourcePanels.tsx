import {
  Bot,
  CheckCircle2,
  MessageCircle,
  Rss,
  User,
} from "lucide-react";

import type {
  ConversationHistory,
  DashboardData,
  SubscriptionItem,
} from "@/lib/api";
import { formatTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { MarkdownMessage } from "@/components/chat/MarkdownMessage";
import { EmptyState } from "@/components/shared/EmptyState";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

export function Overview({ data }: { data: DashboardData | null }) {
  if (!data) {
    return <EmptyState title="等待查询" description="选择账号后查看订阅和聊天记录。" />;
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <SubscriptionsPanel subscriptions={data.subscriptions} compact />
      <ConversationsPanel conversations={data.conversations} compact />
    </div>
  );
}

export function SubscriptionsPanel({
  subscriptions,
  compact = false,
}: {
  subscriptions: SubscriptionItem[];
  compact?: boolean;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>启用订阅</CardTitle>
          <CardDescription>{subscriptions.length} 条记录</CardDescription>
        </div>
        <Rss className="h-5 w-5 text-primary" />
      </CardHeader>
      <CardContent className="space-y-3">
        {subscriptions.length === 0 ? (
          <EmptyState title="没有启用订阅" description="该用户当前没有可展示的订阅。" dense />
        ) : (
          subscriptions.slice(0, compact ? 6 : undefined).map((subscription) => (
            <SubscriptionRow key={subscription.id} subscription={subscription} />
          ))
        )}
        {compact && subscriptions.length > 6 ? (
          <p className="text-sm text-muted-foreground">
            另有 {subscriptions.length - 6} 条订阅可在订阅页查看。
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function SubscriptionRow({ subscription }: { subscription: SubscriptionItem }) {
  return (
    <div className="pixel-inset bg-background p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-medium">
            {subscription.display_name || subscription.target}
          </p>
          <p className="mt-1 break-all text-sm text-muted-foreground">{subscription.target}</p>
        </div>
        <Badge variant="success">
          <CheckCircle2 className="mr-1 h-3 w-3" />
          启用
        </Badge>
      </div>
      <Separator className="my-3" />
      <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-3">
        <span>类型：{subscription.type}</span>
        <span>投递：{subscription.delivery_mode}</span>
        <span>更新：{formatTime(subscription.updated_at)}</span>
      </div>
    </div>
  );
}

export function ConversationsPanel({
  conversations,
  compact = false,
}: {
  conversations: ConversationHistory[];
  compact?: boolean;
}) {
  const visible = compact ? conversations.slice(0, 4) : conversations;

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>聊天历史</CardTitle>
          <CardDescription>{conversations.length} 个会话</CardDescription>
        </div>
        <MessageCircle className="h-5 w-5 text-primary" />
      </CardHeader>
      <CardContent>
        {conversations.length === 0 ? (
          <EmptyState title="没有聊天记录" description="该用户当前没有可展示的会话。" dense />
        ) : (
          <>
            <Accordion
              className="border-2 border-foreground bg-background px-4"
              collapsible
              defaultValue={visible[0]?.id ? `conversation-${visible[0].id}` : undefined}
              type="single"
            >
              {visible.map((conversation) => (
                <AccordionItem
                  key={conversation.id}
                  value={`conversation-${conversation.id}`}
                >
                  <AccordionTrigger>
                    <div className="mr-3 flex min-w-0 flex-1 flex-col gap-1 text-left">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold">会话 v{conversation.version}</span>
                        <Badge variant={conversation.is_active ? "success" : "secondary"}>
                          {conversation.is_active ? "活跃" : "已结束"}
                        </Badge>
                      </div>
                      <span className="truncate text-xs text-muted-foreground">
                        {formatTime(conversation.updated_at)} 更新，
                        {conversation.messages.length} 条消息
                      </span>
                    </div>
                  </AccordionTrigger>
                  <AccordionContent>
                    <MessageList messages={conversation.messages} />
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
            {compact && conversations.length > visible.length ? (
              <p className="mt-3 text-sm text-muted-foreground">
                另有 {conversations.length - visible.length} 个会话可在会话页查看。
              </p>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function MessageList({ messages }: { messages: ConversationHistory["messages"] }) {
  if (messages.length === 0) {
    return <p className="text-sm text-muted-foreground">该会话没有消息。</p>;
  }

  return (
    <div className="space-y-3">
      {messages.map((message) => {
        const isUser = message.role === "user";
        const isAssistant = message.role === "assistant";
        return (
          <div
            className={cn(
              "flex gap-3 border-2 border-foreground p-3",
              isUser ? "bg-background" : "bg-muted/55",
            )}
            key={message.id}
          >
            <div
              className={cn(
                "flex h-8 w-8 shrink-0 items-center justify-center border-2 border-foreground",
                isUser ? "bg-primary text-primary-foreground" : "bg-accent text-accent-foreground",
              )}
            >
              {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
            </div>
            <div className="min-w-0 flex-1">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <Badge variant={isUser ? "outline" : "warning"}>{message.role}</Badge>
                <span className="text-xs text-muted-foreground">
                  {formatTime(message.created_at)}
                </span>
              </div>
              {isAssistant ? (
                <MarkdownMessage content={message.content || "空消息"} />
              ) : (
                <p className="whitespace-pre-wrap break-words text-sm leading-6">
                  {message.content || "空消息"}
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
