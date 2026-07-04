import {
  type FormEvent,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  AlertCircle,
  Bot,
  Clock3,
  Copy,
  History,
  KeyRound,
  Link2,
  LogOut,
  MessageCircle,
  RefreshCcw,
  Rss,
  Search,
  Shield,
} from "lucide-react";
import { toast } from "sonner";

import {
  fetchAdminBindings,
  fetchCurrentWebUser,
  fetchDashboardData,
  issueLinkCode,
  logoutWebUser,
  type DashboardData,
  type LinkCode,
  type PlatformBindingItem,
  type WebUser,
} from "@/lib/api";
import { webTokenStorageKey } from "@/lib/auth";
import {
  clampNumber,
  formatPlatform,
  formatTime,
} from "@/lib/format";
import { showResourceToast } from "@/lib/resourceToast";
import { cn } from "@/lib/utils";

import {
  ConversationsPanel,
  Overview,
  SubscriptionsPanel,
} from "@/components/dashboard/ResourcePanels";
import { BindingAccountButton } from "@/components/shared/BindingAccountButton";
import { LoadingScreen } from "@/components/shared/LoadingScreen";
import { LoginGate } from "@/components/shared/LoginGate";
import { PageBackdrop } from "@/components/shared/PageBackdrop";
import {
  ListSkeleton,
  OverviewSkeleton,
} from "@/components/shared/SkeletonPanels";
import { StatusPill } from "@/components/shared/StatusPill";
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
import { Toaster } from "@/components/ui/sonner";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";

interface HistoryQuery {
  conversationLimit: number;
  messageLimit: number;
}

const defaultQuery: HistoryQuery = {
  conversationLimit: 20,
  messageLimit: 100,
};

export function AdminDashboard() {
  const [token, setToken] = useState<string | null>(() =>
    localStorage.getItem(webTokenStorageKey),
  );
  const [user, setUser] = useState<WebUser | null>(null);
  const [isCheckingSession, setIsCheckingSession] = useState(Boolean(token));
  const [bindings, setBindings] = useState<PlatformBindingItem[]>([]);
  const [maxPerPlatform, setMaxPerPlatform] = useState(2);
  const [selectedBindingId, setSelectedBindingId] = useState<number | null>(null);
  const [query, setQuery] = useState<HistoryQuery>(defaultQuery);
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingBindings, setIsLoadingBindings] = useState(false);
  const [isIssuingLinkCode, setIsIssuingLinkCode] = useState(false);
  const [linkCode, setLinkCode] = useState<LinkCode | null>(null);
  const [lastLoadedAt, setLastLoadedAt] = useState<Date | null>(null);

  const selectedBinding = useMemo(
    () => bindings.find((binding) => binding.id === selectedBindingId) ?? null,
    [bindings, selectedBindingId],
  );

  const summary = useMemo(() => {
    const subscriptions = data?.subscriptions.length ?? 0;
    const conversations = data?.conversations.length ?? 0;
    const messages = data?.conversations.reduce(
      (total, conversation) => total + conversation.messages.length,
      0,
    ) ?? 0;
    return { subscriptions, conversations, messages };
  }, [data]);

  useEffect(() => {
    // admin 页面不展示任何平台数据，直到本地 token 通过后端校验。
    if (!token) {
      setIsCheckingSession(false);
      setUser(null);
      setBindings([]);
      return;
    }

    const activeToken = token;
    let cancelled = false;
    async function loadSession() {
      setIsCheckingSession(true);
      try {
        const [currentUser, bindingPayload] = await Promise.all([
          fetchCurrentWebUser(activeToken),
          fetchAdminBindings(activeToken),
        ]);
        if (cancelled) {
          return;
        }
        setUser(currentUser);
        applyBindings(bindingPayload.bindings, bindingPayload.max_per_platform);
      } catch (requestError) {
        if (cancelled) {
          return;
        }
        localStorage.removeItem(webTokenStorageKey);
        setToken(null);
        setUser(null);
        setBindings([]);
        setData(null);
        toast.error("登录已失效", {
          description: requestError instanceof Error ? requestError.message : "请重新登录。",
        });
      } finally {
        if (!cancelled) {
          setIsCheckingSession(false);
        }
      }
    }

    void loadSession();
    return () => {
      cancelled = true;
    };
  }, [token]);

  function applyBindings(
    nextBindings: PlatformBindingItem[],
    nextMaxPerPlatform: number,
  ) {
    setBindings(nextBindings);
    setMaxPerPlatform(nextMaxPerPlatform);
    setSelectedBindingId((current) => {
      if (current !== null && nextBindings.some((binding) => binding.id === current)) {
        return current;
      }
      return nextBindings[0]?.id ?? null;
    });
  }

  async function refreshBindings() {
    if (!token) {
      return;
    }

    setIsLoadingBindings(true);
    try {
      const bindingPayload = await fetchAdminBindings(token);
      applyBindings(bindingPayload.bindings, bindingPayload.max_per_platform);
      toast.success("绑定列表已刷新");
    } catch (requestError) {
      toast.error("刷新绑定失败", {
        description: requestError instanceof Error ? requestError.message : "请稍后再试。",
      });
    } finally {
      setIsLoadingBindings(false);
    }
  }

  async function handleIssueLinkCode() {
    if (!token) {
      return;
    }

    setIsIssuingLinkCode(true);
    try {
      const payload = await issueLinkCode(token);
      setLinkCode(payload);
      toast.success("绑定码已生成", {
        description: `请在 Telegram 或 QQ Bot 发送 /link ${payload.code}`,
      });
    } catch (requestError) {
      toast.error("生成绑定码失败", {
        description: requestError instanceof Error ? requestError.message : "请稍后再试。",
      });
    } finally {
      setIsIssuingLinkCode(false);
    }
  }

  async function copyLinkCommand() {
    if (!linkCode) {
      return;
    }

    try {
      await navigator.clipboard.writeText(`/link ${linkCode.code}`);
      toast.success("已复制绑定命令");
    } catch {
      toast.error("复制失败");
    }
  }

  async function loadDashboard(nextQuery = query, binding = selectedBinding) {
    if (!token) {
      return;
    }
    if (!binding) {
      const message = "请先绑定并选择一个 Bot 账号。";
      setError(message);
      toast.warning("缺少查询条件", {
        description: message,
      });
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      const payload = await fetchDashboardData(
        {
          ...nextQuery,
          platform: binding.platform,
          platformUserId: binding.platform_user_id,
        },
        token,
      );
      setData(payload);
      setLastLoadedAt(new Date());
      showResourceToast(binding.platform, binding.platform_user_id, payload);
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

  async function handleLogout() {
    if (token) {
      try {
        await logoutWebUser(token);
      } catch {
        // token 已失效时也继续做本地退出，避免 admin 页面停留在过期登录态。
      }
    }
    localStorage.removeItem(webTokenStorageKey);
    setToken(null);
    setUser(null);
    setBindings([]);
    setData(null);
    setLinkCode(null);
  }

  function updateQuery<Key extends keyof HistoryQuery>(key: Key, value: HistoryQuery[Key]) {
    setQuery((current) => ({ ...current, [key]: value }));
  }

  if (isCheckingSession) {
    return <LoadingScreen label="正在验证登录" />;
  }

  if (!token || !user) {
    return (
      <LoginGate
        description="登录 Web 用户后才能进入管理后台。"
        title="需要登录"
      />
    );
  }

  const selectedLabel = selectedBinding
    ? `${formatPlatform(selectedBinding.platform)} / ${selectedBinding.platform_user_id}`
    : "未选择";

  return (
    <PageBackdrop>
      <div className="container relative z-10 py-6 md:py-8">
        <header className="mb-6 flex flex-col gap-4 border-b-2 border-foreground pb-5 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="mb-2 flex items-center gap-2 text-sm font-medium text-primary">
              <Bot className="h-4 w-4" />
              Moegal Agent Web
            </div>
            <h1 className="text-2xl font-semibold tracking-normal md:text-3xl">
              用户订阅与对话记录
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {user.username} / ID {user.id}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill icon={Rss} label="订阅" value={summary.subscriptions} />
            <StatusPill icon={History} label="会话" value={summary.conversations} />
            <StatusPill icon={MessageCircle} label="消息" value={summary.messages} />
            <Button asChild aria-label="Token 用量" size="icon" variant="outline">
              <a href="/usage">
                <KeyRound />
              </a>
            </Button>
            <Button asChild aria-label="Web 聊天" size="icon" variant="outline">
              <a href="/">
                <Bot />
              </a>
            </Button>
            <Button
              aria-label="退出登录"
              onClick={() => void handleLogout()}
              size="icon"
              type="button"
              variant="outline"
            >
              <LogOut />
            </Button>
          </div>
        </header>

        <div className="grid gap-5 lg:grid-cols-[360px_minmax(0,1fr)]">
          <Card className="h-fit">
            <CardHeader>
              <CardTitle>可查看账号</CardTitle>
              <CardDescription>
                Web 账号默认可查看，Bot 账号需要绑定；每个平台最多绑定 {maxPerPlatform} 个。
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="mb-5 space-y-2">
                <Button
                  className="w-full"
                  disabled={isIssuingLinkCode}
                  onClick={() => void handleIssueLinkCode()}
                  type="button"
                  variant="outline"
                >
                  {isIssuingLinkCode ? (
                    <RefreshCcw className="animate-spin" />
                  ) : (
                    <KeyRound />
                  )}
                  生成绑定码
                </Button>
                <p className="text-xs leading-5 text-muted-foreground">
                  同一个绑定码可发送给 Telegram 或 QQ Bot，平台由收到 /link 的 bot 决定。
                </p>
              </div>

              {linkCode ? (
                <div className="mb-5 pixel-inset bg-background p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <div>
                      <p className="text-xs text-muted-foreground">通用绑定码</p>
                      <p className="mt-1 font-mono text-lg font-semibold tracking-normal">
                        {linkCode.code}
                      </p>
                    </div>
                    <Button
                      aria-label="复制绑定命令"
                      onClick={() => void copyLinkCommand()}
                      size="icon"
                      type="button"
                      variant="outline"
                    >
                      <Copy />
                    </Button>
                  </div>
                  <p className="break-all text-sm text-muted-foreground">
                    在 Telegram 或 QQ Bot 发送：/link {linkCode.code}
                  </p>
                  <p className="mt-2 text-xs text-muted-foreground">
                    有效期至 {formatTime(linkCode.expires_at)}
                  </p>
                </div>
              ) : null}

              <div className="mb-5 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <Label>账号列表</Label>
                  <Button
                    disabled={isLoadingBindings}
                    onClick={() => void refreshBindings()}
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    <RefreshCcw className={cn(isLoadingBindings && "animate-spin")} />
                    刷新
                  </Button>
                </div>
                {bindings.length === 0 ? (
                  <div className="border-2 border-dashed border-foreground bg-background p-4 text-sm text-muted-foreground">
                    暂无可查看账号。
                  </div>
                ) : (
                  <div className="space-y-2">
                    {bindings.map((binding) => (
                      <BindingAccountButton
                        active={binding.id === selectedBindingId}
                        binding={binding}
                        key={binding.id}
                        onClick={() => {
                          setSelectedBindingId(binding.id);
                          setData(null);
                          setError(null);
                        }}
                      />
                    ))}
                  </div>
                )}
              </div>

              <form className="space-y-5" onSubmit={handleSubmit}>
                <div className="pixel-inset bg-background p-3 text-sm">
                  <div className="flex items-center gap-2 text-muted-foreground">
                    <Link2 className="h-4 w-4" />
                    当前账号
                  </div>
                  <p className="mt-1 break-all font-medium">{selectedLabel}</p>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-2">
                    <Label htmlFor="conversation-limit">会话数</Label>
                    <Input
                      id="conversation-limit"
                      max={100}
                      min={1}
                      onChange={(event) =>
                        updateQuery(
                          "conversationLimit",
                          clampNumber(event.target.value, 1, 100),
                        )
                      }
                      type="number"
                      value={query.conversationLimit}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="message-limit">消息数</Label>
                    <Input
                      id="message-limit"
                      max={500}
                      min={1}
                      onChange={(event) =>
                        updateQuery("messageLimit", clampNumber(event.target.value, 1, 500))
                      }
                      type="number"
                      value={query.messageLimit}
                    />
                  </div>
                </div>

                {error ? (
                  <div className="flex gap-2 border-2 border-foreground bg-destructive p-3 text-sm font-bold text-destructive-foreground">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>{error}</span>
                  </div>
                ) : null}

                <div className="flex gap-2">
                  <Button className="flex-1" disabled={isLoading || !selectedBinding} type="submit">
                    {isLoading ? (
                      <RefreshCcw className="animate-spin" />
                    ) : (
                      <Search />
                    )}
                    查询
                  </Button>
                  <Button
                    aria-label="刷新"
                    disabled={isLoading || !data || !selectedBinding}
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
    </PageBackdrop>
  );
}
