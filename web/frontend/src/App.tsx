import { FormEvent, useMemo, useState } from "react";
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  Clock3,
  History,
  MessageCircle,
  RefreshCcw,
  Rss,
  Search,
  User,
} from "lucide-react";

import {
  fetchDashboardData,
  type ConversationHistory,
  type DashboardData,
  type Platform,
  type QueryParams,
  type SubscriptionItem,
} from "@/lib/api";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Toaster } from "@/components/ui/sonner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const defaultQuery: QueryParams = {
  platform: "tg",
  platformUserId: "",
  conversationLimit: 20,
  messageLimit: 100,
};

const numberFormatter = new Intl.NumberFormat("zh-CN");

function App() {
  const [query, setQuery] = useState<QueryParams>(defaultQuery);
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [lastLoadedAt, setLastLoadedAt] = useState<Date | null>(null);

  const summary = useMemo(() => {
    const subscriptions = data?.subscriptions.length ?? 0;
    const conversations = data?.conversations.length ?? 0;
    const messages = data?.conversations.reduce(
      (total, conversation) => total + conversation.messages.length,
      0,
    ) ?? 0;
    return { subscriptions, conversations, messages };
  }, [data]);

  async function loadDashboard(nextQuery = query) {
    const platformUserId = nextQuery.platformUserId.trim();
    if (!platformUserId) {
      const message = "请输入平台用户 ID。";
      setError(message);
      toast.warning("缺少查询条件", {
        description: message,
      });
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      const payload = await fetchDashboardData({
        ...nextQuery,
        platformUserId,
      });
      setData(payload);
      setLastLoadedAt(new Date());
      showResourceToast(nextQuery.platform, platformUserId, payload);
    } catch (requestError) {
      const message =
        requestError instanceof Error ? requestError.message : "请求失败，请稍后再试。";
      setError(message);
      toast.error("查询失败", {
        description: message,
      });
    } finally {
      setIsLoading(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void loadDashboard();
  }

  function updateQuery<Key extends keyof QueryParams>(key: Key, value: QueryParams[Key]) {
    setQuery((current) => ({ ...current, [key]: value }));
  }

  return (
    <main className="relative min-h-screen overflow-hidden">
      <div className="surface-grid pointer-events-none absolute inset-x-0 top-0 h-80" />
      <div className="container relative z-10 py-6 md:py-8">
        <header className="mb-6 flex flex-col gap-4 border-b pb-5 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="mb-2 flex items-center gap-2 text-sm font-medium text-primary">
              <Bot className="h-4 w-4" />
              Moegal Agent Web
            </div>
            <h1 className="text-2xl font-semibold tracking-normal md:text-3xl">
              用户订阅与对话记录
            </h1>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill icon={Rss} label="订阅" value={summary.subscriptions} />
            <StatusPill icon={History} label="会话" value={summary.conversations} />
            <StatusPill icon={MessageCircle} label="消息" value={summary.messages} />
          </div>
        </header>

        <div className="grid gap-5 lg:grid-cols-[360px_minmax(0,1fr)]">
          <Card className="h-fit">
            <CardHeader>
              <CardTitle>查询用户</CardTitle>
              <CardDescription>按 Bot 平台身份读取现有数据。</CardDescription>
            </CardHeader>
            <CardContent>
              <form className="space-y-5" onSubmit={handleSubmit}>
                <div className="space-y-2">
                  <Label>平台</Label>
                  <div className="grid grid-cols-2 gap-2">
                    <PlatformButton
                      active={query.platform === "tg"}
                      label="Telegram"
                      onClick={() => updateQuery("platform", "tg")}
                    />
                    <PlatformButton
                      active={query.platform === "qq"}
                      label="QQ"
                      onClick={() => updateQuery("platform", "qq")}
                    />
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="platform-user-id">平台用户 ID</Label>
                  <Input
                    id="platform-user-id"
                    placeholder={query.platform === "tg" ? "例如：42" : "例如：qq-42"}
                    value={query.platformUserId}
                    onChange={(event) => updateQuery("platformUserId", event.target.value)}
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-2">
                    <Label htmlFor="conversation-limit">会话数</Label>
                    <Input
                      id="conversation-limit"
                      type="number"
                      min={1}
                      max={100}
                      value={query.conversationLimit}
                      onChange={(event) =>
                        updateQuery("conversationLimit", clampNumber(event.target.value, 1, 100))
                      }
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="message-limit">消息数</Label>
                    <Input
                      id="message-limit"
                      type="number"
                      min={1}
                      max={500}
                      value={query.messageLimit}
                      onChange={(event) =>
                        updateQuery("messageLimit", clampNumber(event.target.value, 1, 500))
                      }
                    />
                  </div>
                </div>

                {error ? (
                  <div className="flex gap-2 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>{error}</span>
                  </div>
                ) : null}

                <div className="flex gap-2">
                  <Button className="flex-1" disabled={isLoading} type="submit">
                    {isLoading ? (
                      <RefreshCcw className="animate-spin" />
                    ) : (
                      <Search />
                    )}
                    查询
                  </Button>
                  <Button
                    aria-label="刷新"
                    disabled={isLoading || !data}
                    onClick={() => void loadDashboard()}
                    size="icon"
                    type="button"
                    variant="outline"
                  >
                    <RefreshCcw className={cn(isLoading && "animate-spin")} />
                  </Button>
                </div>
              </form>

              {lastLoadedAt ? (
                <div className="mt-5 flex items-center gap-2 text-xs text-muted-foreground">
                  <Clock3 className="h-3.5 w-3.5" />
                  最近加载：{formatTime(lastLoadedAt.toISOString())}
                </div>
              ) : null}
            </CardContent>
          </Card>

          <section className="min-w-0">
            <Tabs defaultValue="overview" className="space-y-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <TabsList className="grid w-full grid-cols-3 sm:w-[420px]">
                  <TabsTrigger value="overview">总览</TabsTrigger>
                  <TabsTrigger value="subscriptions">订阅</TabsTrigger>
                  <TabsTrigger value="conversations">会话</TabsTrigger>
                </TabsList>
              </div>

              <TabsContent value="overview">
                {isLoading ? <OverviewSkeleton /> : <Overview data={data} />}
              </TabsContent>
              <TabsContent value="subscriptions">
                {isLoading ? (
                  <ListSkeleton />
                ) : (
                  <SubscriptionsPanel subscriptions={data?.subscriptions ?? []} />
                )}
              </TabsContent>
              <TabsContent value="conversations">
                {isLoading ? (
                  <ListSkeleton />
                ) : (
                  <ConversationsPanel conversations={data?.conversations ?? []} />
                )}
              </TabsContent>
            </Tabs>
          </section>
        </div>
      </div>
      <Toaster />
    </main>
  );
}

function PlatformButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <Button
      aria-pressed={active}
      className={cn(active && "border-primary bg-primary/10 text-primary hover:bg-primary/15")}
      onClick={onClick}
      type="button"
      variant="outline"
    >
      {label}
    </Button>
  );
}

function StatusPill({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Rss;
  label: string;
  value: number;
}) {
  return (
    <div className="flex h-10 items-center gap-2 rounded-md border bg-card px-3 text-sm shadow-sm">
      <Icon className="h-4 w-4 text-primary" />
      <span className="text-muted-foreground">{label}</span>
      <span className="font-semibold">{numberFormatter.format(value)}</span>
    </div>
  );
}

function Overview({ data }: { data: DashboardData | null }) {
  if (!data) {
    return <EmptyState title="等待查询" description="输入平台用户 ID 后查看订阅和聊天记录。" />;
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <SubscriptionsPanel subscriptions={data.subscriptions} compact />
      <ConversationsPanel conversations={data.conversations} compact />
    </div>
  );
}

function SubscriptionsPanel({
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
    <div className="rounded-md border bg-background p-4">
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

function ConversationsPanel({
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
              className="rounded-md border px-4"
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
                        {formatTime(conversation.updated_at)} 更新，{conversation.messages.length} 条消息
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
        return (
          <div
            className={cn(
              "flex gap-3 rounded-md border p-3",
              isUser ? "bg-background" : "bg-muted/55",
            )}
            key={message.id}
          >
            <div
              className={cn(
                "flex h-8 w-8 shrink-0 items-center justify-center rounded-md",
                isUser ? "bg-primary text-primary-foreground" : "bg-accent text-accent-foreground",
              )}
            >
              {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
            </div>
            <div className="min-w-0 flex-1">
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <Badge variant={isUser ? "outline" : "warning"}>{message.role}</Badge>
                <span className="text-xs text-muted-foreground">{formatTime(message.created_at)}</span>
              </div>
              <p className="whitespace-pre-wrap break-words text-sm leading-6">
                {message.content || "空消息"}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function EmptyState({
  title,
  description,
  dense = false,
}: {
  title: string;
  description: string;
  dense?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-md border border-dashed bg-card text-center",
        dense ? "min-h-40 p-6" : "min-h-[420px] p-8",
      )}
    >
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-md bg-muted">
        <Search className="h-5 w-5 text-muted-foreground" />
      </div>
      <h2 className="text-base font-semibold">{title}</h2>
      <p className="mt-2 max-w-sm text-sm text-muted-foreground">{description}</p>
    </div>
  );
}

function OverviewSkeleton() {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <ListSkeleton />
      <ListSkeleton />
    </div>
  );
}

function ListSkeleton() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-4 w-48" />
      </CardHeader>
      <CardContent className="space-y-3">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton className="h-20 w-full" key={index} />
        ))}
      </CardContent>
    </Card>
  );
}

function clampNumber(value: string, min: number, max: number) {
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) {
    return min;
  }
  return Math.min(max, Math.max(min, parsed));
}

function showResourceToast(platform: Platform, platformUserId: string, payload: DashboardData) {
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

function formatPlatform(platform: Platform) {
  return platform === "tg" ? "Telegram" : "QQ";
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

export default App;
