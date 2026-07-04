import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  Clock3,
  Copy,
  History,
  KeyRound,
  Link2,
  LogIn,
  LogOut,
  MessageCircle,
  Plus,
  RefreshCcw,
  Rss,
  Search,
  Send,
  Shield,
  User,
  UserPlus,
} from "lucide-react";

import {
  fetchAdminBindings,
  fetchCurrentWebUser,
  fetchDashboardData,
  fetchTokenUsage,
  fetchWebChatHistory,
  issueLinkCode,
  type ConversationHistory,
  type DashboardData,
  type LinkCode,
  loginWebUser,
  logoutWebUser,
  type PlatformBindingItem,
  type Platform,
  registerWebUser,
  startNewWebChat,
  streamWebChatMessage,
  type SubscriptionItem,
  type TokenUsageByModelItem,
  type TokenUsageData,
  type TokenUsageRecordItem,
  type WebUser,
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

interface HistoryQuery {
  conversationLimit: number;
  messageLimit: number;
}

const defaultQuery: HistoryQuery = {
  conversationLimit: 20,
  messageLimit: 100,
};

const webTokenStorageKey = "moegal-web-token";

const numberFormatter = new Intl.NumberFormat("zh-CN");

function App() {
  // 简单前端路由：根路径是 Web 聊天，/admin 和 /usage 使用同一套登录态。
  const route = window.location.pathname.replace(/\/+$/, "") || "/";
  if (route === "/admin") {
    return <AdminDashboard />;
  }
  if (route === "/usage") {
    return <TokenUsagePage />;
  }
  return <WebChatApp />;
}

function AdminDashboard() {
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

  function applyBindings(nextBindings: PlatformBindingItem[], nextMaxPerPlatform: number) {
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
      const payload = await fetchDashboardData({
        ...nextQuery,
        platform: binding.platform,
        platformUserId: binding.platform_user_id,
      }, token);
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
    return (
      <main className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <RefreshCcw className="h-4 w-4 animate-spin" />
          正在验证登录
        </div>
        <Toaster />
      </main>
    );
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
                <div className="mb-5 rounded-md border bg-background p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <div>
                      <p className="text-xs text-muted-foreground">
                        通用绑定码
                      </p>
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
                  <div className="rounded-md border border-dashed bg-background p-4 text-sm text-muted-foreground">
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
                <div className="rounded-md border bg-background p-3 text-sm">
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
    </main>
  );
}

function TokenUsagePage() {
  const [token, setToken] = useState<string | null>(() =>
    localStorage.getItem(webTokenStorageKey),
  );
  const [user, setUser] = useState<WebUser | null>(null);
  const [isCheckingSession, setIsCheckingSession] = useState(Boolean(token));
  const [bindings, setBindings] = useState<PlatformBindingItem[]>([]);
  const [selectedBindingId, setSelectedBindingId] = useState<number | null>(null);
  const [usage, setUsage] = useState<TokenUsageData | null>(null);
  const [recentLimit, setRecentLimit] = useState(20);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [lastLoadedAt, setLastLoadedAt] = useState<Date | null>(null);

  const selectedBinding = useMemo(
    () => bindings.find((binding) => binding.id === selectedBindingId) ?? null,
    [bindings, selectedBindingId],
  );

  useEffect(() => {
    if (!token) {
      setIsCheckingSession(false);
      setUser(null);
      setBindings([]);
      setUsage(null);
      return;
    }

    const activeToken = token;
    let cancelled = false;

    async function loadSession() {
      setIsCheckingSession(true);
      setError(null);
      try {
        const [currentUser, bindingPayload] = await Promise.all([
          fetchCurrentWebUser(activeToken),
          fetchAdminBindings(activeToken),
        ]);
        if (cancelled) {
          return;
        }

        const firstBinding = bindingPayload.bindings[0] ?? null;
        let initialUsage: TokenUsageData | null = null;
        let initialUsageError: string | null = null;
        if (firstBinding) {
          try {
            initialUsage = await fetchTokenUsage({
              platform: firstBinding.platform,
              platformUserId: firstBinding.platform_user_id,
              recentLimit,
            }, activeToken);
          } catch (requestError) {
            initialUsageError =
              requestError instanceof Error ? requestError.message : "请求失败，请稍后再试。";
          }
        }
        if (cancelled) {
          return;
        }

        setUser(currentUser);
        setBindings(bindingPayload.bindings);
        setSelectedBindingId(firstBinding?.id ?? null);
        setUsage(initialUsage);
        setLastLoadedAt(initialUsage ? new Date() : null);
        if (initialUsageError) {
          setError(initialUsageError);
          toast.error("读取用量失败", { description: initialUsageError });
        }
      } catch (requestError) {
        if (cancelled) {
          return;
        }
        localStorage.removeItem(webTokenStorageKey);
        setToken(null);
        setUser(null);
        setBindings([]);
        setUsage(null);
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

  async function loadUsage(
    binding: PlatformBindingItem | null = selectedBinding,
    activeToken = token,
  ): Promise<boolean> {
    if (!activeToken) {
      return false;
    }
    if (!binding) {
      const message = "请先选择一个可查看账号。";
      setError(message);
      toast.warning("缺少账号", { description: message });
      return false;
    }

    setIsLoading(true);
    setError(null);
    try {
      const payload = await fetchTokenUsage({
        platform: binding.platform,
        platformUserId: binding.platform_user_id,
        recentLimit,
      }, activeToken);
      setUsage(payload);
      setLastLoadedAt(new Date());
      return true;
    } catch (requestError) {
      const message =
        requestError instanceof Error ? requestError.message : "请求失败，请稍后再试。";
      setError(message);
      toast.error("读取用量失败", { description: message });
      return false;
    } finally {
      setIsLoading(false);
    }
  }

  async function refreshBindings() {
    if (!token) {
      return;
    }

    setIsLoading(true);
    try {
      const bindingPayload = await fetchAdminBindings(token);
      setBindings(bindingPayload.bindings);
      const nextBinding = selectedBindingId === null
        ? bindingPayload.bindings[0] ?? null
        : bindingPayload.bindings.find((binding) => binding.id === selectedBindingId)
          ?? bindingPayload.bindings[0]
          ?? null;
      setSelectedBindingId(nextBinding?.id ?? null);
      if (nextBinding) {
        const loaded = await loadUsage(nextBinding, token);
        if (loaded) {
          toast.success("用量已刷新");
        }
      } else {
        setUsage(null);
        setLastLoadedAt(null);
        toast.success("账号列表已刷新");
      }
    } catch (requestError) {
      toast.error("刷新失败", {
        description: requestError instanceof Error ? requestError.message : "请稍后再试。",
      });
    } finally {
      setIsLoading(false);
    }
  }

  async function handleLogout() {
    if (token) {
      try {
        await logoutWebUser(token);
      } catch {
        // token 已失效时也继续做本地退出，避免用量页停留在过期登录态。
      }
    }
    localStorage.removeItem(webTokenStorageKey);
    setToken(null);
    setUser(null);
    setBindings([]);
    setUsage(null);
  }

  if (isCheckingSession) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <RefreshCcw className="h-4 w-4 animate-spin" />
          正在读取用量
        </div>
        <Toaster />
      </main>
    );
  }

  if (!token || !user) {
    return (
      <LoginGate
        description="登录 Web 用户后才能查看 token 用量。"
        title="需要登录"
      />
    );
  }

  const summary = usage?.summary;
  const selectedLabel = selectedBinding
    ? `${formatPlatform(selectedBinding.platform)} / ${selectedBinding.platform_user_id}`
    : "未选择";

  return (
    <main className="relative min-h-screen overflow-hidden">
      <div className="surface-grid pointer-events-none absolute inset-x-0 top-0 h-80" />
      <div className="container relative z-10 py-6 md:py-8">
        <header className="mb-6 flex flex-col gap-4 border-b pb-5 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="mb-2 flex items-center gap-2 text-sm font-medium text-primary">
              <KeyRound className="h-4 w-4" />
              Moegal Agent Web
            </div>
            <h1 className="text-2xl font-semibold tracking-normal md:text-3xl">
              用户 token 用量
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {user.username} / ID {user.id}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill icon={KeyRound} label="总 token" value={summary?.total_tokens ?? 0} />
            <StatusPill icon={History} label="请求" value={summary?.request_count ?? 0} />
            <StatusPill icon={Bot} label="模型" value={usage?.by_model.length ?? 0} />
            <Button asChild aria-label="管理后台" size="icon" variant="outline">
              <a href="/admin">
                <Shield />
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
              <CardTitle>账号</CardTitle>
              <CardDescription>{selectedLabel}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <Label>可查看账号</Label>
                  <Button
                    disabled={isLoading}
                    onClick={() => void refreshBindings()}
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    <RefreshCcw className={cn(isLoading && "animate-spin")} />
                    刷新
                  </Button>
                </div>
                {bindings.length === 0 ? (
                  <div className="rounded-md border border-dashed bg-background p-4 text-sm text-muted-foreground">
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
                          void loadUsage(binding);
                        }}
                      />
                    ))}
                  </div>
                )}
              </div>

              <form
                className="space-y-4"
                onSubmit={(event) => {
                  event.preventDefault();
                  void loadUsage();
                }}
              >
                <div className="space-y-2">
                  <Label htmlFor="recent-limit">最近记录</Label>
                  <Input
                    id="recent-limit"
                    max={100}
                    min={1}
                    onChange={(event) =>
                      setRecentLimit(clampNumber(event.target.value, 1, 100))
                    }
                    type="number"
                    value={recentLimit}
                  />
                </div>

                {error ? (
                  <div className="flex gap-2 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    <span>{error}</span>
                  </div>
                ) : null}

                <Button className="w-full" disabled={isLoading || !selectedBinding} type="submit">
                  {isLoading ? (
                    <RefreshCcw className="animate-spin" />
                  ) : (
                    <Search />
                  )}
                  查询用量
                </Button>
              </form>

              {lastLoadedAt ? (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Clock3 className="h-3.5 w-3.5" />
                  最近加载：{formatTime(lastLoadedAt.toISOString())}
                </div>
              ) : null}
            </CardContent>
          </Card>

          <section className="min-w-0 space-y-4">
            {isLoading && !usage ? (
              <OverviewSkeleton />
            ) : (
              <>
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                  <UsageMetricCard
                    icon={KeyRound}
                    label="总 token"
                    value={numberFormatter.format(summary?.total_tokens ?? 0)}
                    detail={`${numberFormatter.format(summary?.request_count ?? 0)} 次请求`}
                  />
                  <UsageMetricCard
                    icon={Search}
                    label="Prompt"
                    value={numberFormatter.format(summary?.prompt_tokens ?? 0)}
                    detail="输入 token"
                  />
                  <UsageMetricCard
                    icon={MessageCircle}
                    label="Completion"
                    value={numberFormatter.format(summary?.completion_tokens ?? 0)}
                    detail="输出 token"
                  />
                  <UsageMetricCard
                    icon={Clock3}
                    label="平均耗时"
                    value={formatMilliseconds(summary?.average_elapsed_ms ?? 0)}
                    detail={summary?.latest_created_at
                      ? `最近 ${formatTime(summary.latest_created_at)}`
                      : "暂无调用"}
                  />
                </div>

                <div className="grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
                  <ModelUsagePanel models={usage?.by_model ?? []} />
                  <RecentUsagePanel records={usage?.recent ?? []} />
                </div>
              </>
            )}
          </section>
        </div>
      </div>
      <Toaster />
    </main>
  );
}

interface ChatMessageView {
  id: string;
  role: "user" | "assistant";
  content: string;
  pending?: boolean;
  failed?: boolean;
}

function WebChatApp() {
  const [token, setToken] = useState<string | null>(() =>
    localStorage.getItem(webTokenStorageKey),
  );
  const [user, setUser] = useState<WebUser | null>(null);
  const [messages, setMessages] = useState<ChatMessageView[]>([]);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authForm, setAuthForm] = useState({
    userId: "",
    username: "",
    password: "",
  });
  const [authError, setAuthError] = useState<string | null>(null);
  const [isCheckingSession, setIsCheckingSession] = useState(Boolean(token));
  const [isAuthenticating, setIsAuthenticating] = useState(false);
  const [draft, setDraft] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isStartingNew, setIsStartingNew] = useState(false);

  useEffect(() => {
    // 刷新页面后先用本地 token 向后端校验身份，再恢复当前活跃会话。
    if (!token) {
      setIsCheckingSession(false);
      return;
    }

    const activeToken = token;
    let cancelled = false;
    async function loadSession() {
      setIsCheckingSession(true);
      try {
        const [currentUser, conversations] = await Promise.all([
          fetchCurrentWebUser(activeToken),
          fetchWebChatHistory(activeToken),
        ]);
        if (cancelled) {
          return;
        }
        setUser(currentUser);
        setMessages(messagesFromConversations(conversations));
      } catch (error) {
        if (cancelled) {
          return;
        }
        localStorage.removeItem(webTokenStorageKey);
        setToken(null);
        setUser(null);
        setMessages([]);
        toast.error("登录已失效", {
          description: error instanceof Error ? error.message : "请重新登录。",
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

  async function handleAuthSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsAuthenticating(true);
    setAuthError(null);

    try {
      const response = authMode === "login"
        ? await loginWebUser(authForm.userId.trim(), authForm.password)
        : await registerWebUser(authForm.username.trim(), authForm.password);

      localStorage.setItem(webTokenStorageKey, response.token);
      setToken(response.token);
      setUser(response.user);
      setMessages([]);
      setAuthForm((current) => ({
        ...current,
        userId: String(response.user.id),
        password: "",
      }));
      toast.success(authMode === "login" ? "已登录" : "已注册并登录", {
        description: `用户 ID：${response.user.id}`,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "认证失败，请稍后再试。";
      setAuthError(message);
      toast.error(authMode === "login" ? "登录失败" : "注册失败", {
        description: message,
      });
    } finally {
      setIsAuthenticating(false);
    }
  }

  async function handleLogout() {
    if (token) {
      try {
        await logoutWebUser(token);
      } catch {
        // token 已失效时也继续做本地退出，避免用户卡在登录态。
      }
    }
    localStorage.removeItem(webTokenStorageKey);
    setToken(null);
    setUser(null);
    setMessages([]);
    setDraft("");
  }

  async function handleStartNewChat() {
    if (!token) {
      return;
    }

    setIsStartingNew(true);
    try {
      const result = await startNewWebChat(token);
      if (result.created) {
        setMessages([]);
      }
      toast.success(result.message);
    } catch (error) {
      toast.error("新建会话失败", {
        description: error instanceof Error ? error.message : "请稍后再试。",
      });
    } finally {
      setIsStartingNew(false);
    }
  }

  async function handleSendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || isSending) {
      return;
    }

    const message = draft.trim();
    if (!message) {
      return;
    }

    const assistantMessageId = `assistant-${Date.now()}`;
    setDraft("");
    setIsSending(true);
    // 先乐观插入用户消息和助手占位，后端返回后再替换占位内容。
    setMessages((current) => [
      ...current,
      {
        id: `user-${Date.now()}`,
        role: "user",
        content: message,
      },
      {
        id: assistantMessageId,
        role: "assistant",
        content: "",
        pending: true,
      },
    ]);

    try {
      const reply = await streamWebChatMessage(token, message, (delta) => {
        setMessages((current) =>
          current.map((item) =>
            item.id === assistantMessageId
              ? {
                  ...item,
                  content: item.content + delta,
                }
              : item,
          ),
        );
      });
      setMessages((current) =>
        current.map((item) =>
          item.id === assistantMessageId
            ? {
                ...item,
                content: reply || item.content,
                pending: false,
              }
            : item,
        ),
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "发送失败，请稍后再试。";
      setMessages((current) =>
        current.map((item) =>
          item.id === assistantMessageId
            ? {
                ...item,
                content: message,
                pending: false,
                failed: true,
              }
            : item,
        ),
      );
      toast.error("发送失败", { description: message });
    } finally {
      setIsSending(false);
    }
  }

  if (isCheckingSession) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-background">
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <RefreshCcw className="h-4 w-4 animate-spin" />
          正在恢复登录
        </div>
        <Toaster />
      </main>
    );
  }

  if (!token || !user) {
    return (
      <main className="relative min-h-screen overflow-hidden">
        <div className="surface-grid pointer-events-none absolute inset-x-0 top-0 h-80" />
        <div className="container relative z-10 flex min-h-screen max-w-5xl items-center py-8">
          <div className="grid w-full gap-6 lg:grid-cols-[minmax(0,0.95fr)_420px] lg:items-center">
            <section className="space-y-4">
              <div className="flex items-center gap-2 text-sm font-medium text-primary">
                <Bot className="h-4 w-4" />
                Moegal Agent Web
              </div>
              <h1 className="text-3xl font-semibold tracking-normal md:text-4xl">
                Web 聊天
              </h1>
              <p className="max-w-xl text-sm leading-6 text-muted-foreground">
                使用 Web 账号继续和 Moegal Agent 对话，订阅工具与聊天上下文会独立保存。
              </p>
              <Button asChild variant="outline">
                <a href="/admin">
                  <Shield />
                  管理后台
                </a>
              </Button>
            </section>

            <Card>
              <CardHeader>
                <CardTitle>{authMode === "login" ? "登录" : "注册"}</CardTitle>
                <CardDescription>
                  {authMode === "login"
                    ? "输入平台分配的 10 位用户 ID 和密码。"
                    : "填写用户名和密码，平台会分配 10 位用户 ID。"}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="mb-5 grid grid-cols-2 gap-2">
                  <Button
                    className={cn(authMode === "login" && "border-primary bg-primary/10 text-primary")}
                    onClick={() => setAuthMode("login")}
                    type="button"
                    variant="outline"
                  >
                    <LogIn />
                    登录
                  </Button>
                  <Button
                    className={cn(authMode === "register" && "border-primary bg-primary/10 text-primary")}
                    onClick={() => setAuthMode("register")}
                    type="button"
                    variant="outline"
                  >
                    <UserPlus />
                    注册
                  </Button>
                </div>

                <form className="space-y-4" onSubmit={handleAuthSubmit}>
                  {authMode === "login" ? (
                    <div className="space-y-2">
                      <Label htmlFor="web-user-id">用户 ID</Label>
                      <Input
                        autoComplete="off"
                        id="web-user-id"
                        inputMode="numeric"
                        maxLength={10}
                        value={authForm.userId}
                        onChange={(event) =>
                          setAuthForm((current) => ({
                            ...current,
                            userId: event.target.value,
                          }))
                        }
                      />
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <Label htmlFor="web-username">用户名</Label>
                      <Input
                        autoComplete="username"
                        id="web-username"
                        value={authForm.username}
                        onChange={(event) =>
                          setAuthForm((current) => ({
                            ...current,
                            username: event.target.value,
                          }))
                        }
                      />
                    </div>
                  )}

                  <div className="space-y-2">
                    <Label htmlFor="web-password">密码</Label>
                    <Input
                      autoComplete={authMode === "login" ? "current-password" : "new-password"}
                      id="web-password"
                      type="password"
                      value={authForm.password}
                      onChange={(event) =>
                        setAuthForm((current) => ({
                          ...current,
                          password: event.target.value,
                        }))
                      }
                    />
                  </div>

                  {authError ? (
                    <div className="flex gap-2 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>{authError}</span>
                    </div>
                  ) : null}

                  <Button className="w-full" disabled={isAuthenticating} type="submit">
                    {isAuthenticating ? (
                      <RefreshCcw className="animate-spin" />
                    ) : authMode === "login" ? (
                      <LogIn />
                    ) : (
                      <UserPlus />
                    )}
                    {authMode === "login" ? "登录" : "注册"}
                  </Button>
                </form>
              </CardContent>
            </Card>
          </div>
        </div>
        <Toaster />
      </main>
    );
  }

  return (
    <main className="flex min-h-screen flex-col bg-background">
      <header className="border-b bg-card">
        <div className="container flex min-h-16 flex-wrap items-center justify-between gap-3 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <Bot className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-lg font-semibold">Moegal Agent</h1>
              <p className="truncate text-xs text-muted-foreground">
                {user.username} / ID {user.id}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button
              aria-label="新会话"
              disabled={isStartingNew || isSending}
              onClick={() => void handleStartNewChat()}
              size="icon"
              type="button"
              variant="outline"
            >
              {isStartingNew ? <RefreshCcw className="animate-spin" /> : <Plus />}
            </Button>
            <Button asChild aria-label="管理后台" size="icon" variant="outline">
              <a href="/admin">
                <Shield />
              </a>
            </Button>
            <Button asChild aria-label="Token 用量" size="icon" variant="outline">
              <a href="/usage">
                <KeyRound />
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
        </div>
      </header>

      <section className="container flex min-h-0 flex-1 flex-col py-5">
        <div className="min-h-0 flex-1 overflow-y-auto rounded-md border bg-card p-4">
          {messages.length === 0 ? (
            <div className="flex min-h-[52vh] items-center justify-center text-center">
              <div>
                <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-md bg-muted">
                  <MessageCircle className="h-5 w-5 text-muted-foreground" />
                </div>
                <h2 className="text-base font-semibold">暂无消息</h2>
                <p className="mt-2 text-sm text-muted-foreground">发送第一条消息开始对话。</p>
              </div>
            </div>
          ) : (
            <div className="flex w-full flex-col gap-4">
              {messages.map((message) => (
                <ChatBubble key={message.id} message={message} />
              ))}
            </div>
          )}
        </div>

        <form className="mt-4 flex gap-2" onSubmit={handleSendMessage}>
          <textarea
            className="min-h-12 flex-1 resize-none rounded-md border border-input bg-background px-3 py-3 text-sm leading-5 ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={isSending}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="输入消息"
            rows={1}
            value={draft}
          />
          <Button
            aria-label="发送"
            className="h-12 w-12 shrink-0"
            disabled={isSending || !draft.trim()}
            size="icon"
            type="submit"
          >
            {isSending ? <RefreshCcw className="animate-spin" /> : <Send />}
          </Button>
        </form>
      </section>
      <Toaster />
    </main>
  );
}

function ChatBubble({ message }: { message: ChatMessageView }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex gap-3", isUser && "flex-row-reverse")}>
      <div
        className={cn(
          "flex h-9 w-9 shrink-0 items-center justify-center rounded-md",
          isUser ? "bg-primary text-primary-foreground" : "bg-accent text-accent-foreground",
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>
      <div
        className={cn(
          "max-w-[min(720px,calc(100%-3rem))] rounded-md border px-4 py-3",
          isUser ? "bg-primary text-primary-foreground" : "bg-background",
          message.failed && "border-destructive/50 bg-destructive/10 text-destructive",
        )}
      >
        {message.pending && !message.content ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <RefreshCcw className="h-3.5 w-3.5 animate-spin" />
            生成中
          </div>
        ) : (
          <p className="whitespace-pre-wrap break-words text-sm leading-6">
            {message.content}
            {message.pending ? (
              <RefreshCcw className="ml-2 inline h-3.5 w-3.5 animate-spin text-muted-foreground" />
            ) : null}
          </p>
        )}
      </div>
    </div>
  );
}

function messagesFromConversations(conversations: ConversationHistory[]): ChatMessageView[] {
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

function LoginGate({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <main className="relative min-h-screen overflow-hidden">
      <div className="surface-grid pointer-events-none absolute inset-x-0 top-0 h-80" />
      <div className="container relative z-10 flex min-h-screen max-w-3xl items-center justify-center py-8">
        <Card className="w-full max-w-md">
          <CardHeader>
            <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <Shield className="h-5 w-5" />
            </div>
            <CardTitle>{title}</CardTitle>
            <CardDescription>{description}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Button asChild className="w-full">
              <a href="/">
                <LogIn />
                去登录
              </a>
            </Button>
          </CardContent>
        </Card>
      </div>
      <Toaster />
    </main>
  );
}

function BindingAccountButton({
  active,
  binding,
  onClick,
}: {
  active: boolean;
  binding: PlatformBindingItem;
  onClick: () => void;
}) {
  const title = binding.display_name || binding.username || binding.platform_user_id;
  return (
    <button
      aria-pressed={active}
      className={cn(
        "w-full rounded-md border bg-background p-3 text-left text-sm transition-colors hover:bg-accent",
        active && "border-primary bg-primary/10 text-primary",
      )}
      onClick={onClick}
      type="button"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-medium">{title}</span>
        <Badge variant={active ? "success" : "secondary"}>{formatPlatform(binding.platform)}</Badge>
      </div>
      <div className="mt-1 break-all text-xs text-muted-foreground">
        {binding.platform_user_id}
      </div>
      <div className="mt-2 text-xs text-muted-foreground">
        绑定：{formatTime(binding.bound_at)}
      </div>
    </button>
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

function UsageMetricCard({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: typeof Rss;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="text-sm text-muted-foreground">{label}</CardTitle>
        <Icon className="h-4 w-4 text-primary" />
      </CardHeader>
      <CardContent>
        <div className="break-words text-2xl font-semibold tracking-normal">{value}</div>
        <p className="mt-1 text-xs text-muted-foreground">{detail}</p>
      </CardContent>
    </Card>
  );
}

function ModelUsagePanel({ models }: { models: TokenUsageByModelItem[] }) {
  const maxTokens = Math.max(...models.map((model) => model.total_tokens), 0);

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>模型用量</CardTitle>
          <CardDescription>{models.length} 个模型</CardDescription>
        </div>
        <Bot className="h-5 w-5 text-primary" />
      </CardHeader>
      <CardContent className="space-y-3">
        {models.length === 0 ? (
          <EmptyState title="暂无 token 用量" description="该账号还没有 LLM 调用记录。" dense />
        ) : (
          models.map((model) => {
            const percent = maxTokens > 0 ? (model.total_tokens / maxTokens) * 100 : 0;
            return (
              <div className="rounded-md border bg-background p-4" key={model.model}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="break-all font-medium">{model.model}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {numberFormatter.format(model.request_count)} 次请求
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-lg font-semibold tracking-normal">
                      {numberFormatter.format(model.total_tokens)}
                    </p>
                    <p className="text-xs text-muted-foreground">tokens</p>
                  </div>
                </div>
                <div className="mt-3 h-2 overflow-hidden rounded-md bg-muted">
                  <div
                    className="h-full rounded-md bg-primary"
                    style={{ width: `${percent}%` }}
                  />
                </div>
                <div className="mt-3 grid gap-2 text-xs text-muted-foreground sm:grid-cols-2">
                  <span>Prompt：{numberFormatter.format(model.prompt_tokens)}</span>
                  <span>Completion：{numberFormatter.format(model.completion_tokens)}</span>
                </div>
              </div>
            );
          })
        )}
      </CardContent>
    </Card>
  );
}

function RecentUsagePanel({ records }: { records: TokenUsageRecordItem[] }) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>最近调用</CardTitle>
          <CardDescription>{records.length} 条记录</CardDescription>
        </div>
        <History className="h-5 w-5 text-primary" />
      </CardHeader>
      <CardContent className="space-y-3">
        {records.length === 0 ? (
          <EmptyState title="暂无调用记录" description="该账号最近没有 LLM token 记录。" dense />
        ) : (
          records.map((record) => (
            <div className="rounded-md border bg-background p-4" key={record.id}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={record.status_code >= 400 ? "destructive" : "success"}>
                      {record.status_code}
                    </Badge>
                    <span className="break-all text-sm font-medium">{record.model}</span>
                  </div>
                  <p className="mt-2 break-all text-xs text-muted-foreground">
                    {record.request_path}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-lg font-semibold tracking-normal">
                    {numberFormatter.format(record.total_tokens)}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {formatMilliseconds(record.elapsed_ms)}
                  </p>
                </div>
              </div>
              <Separator className="my-3" />
              <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-3">
                <span>Prompt：{numberFormatter.format(record.prompt_tokens)}</span>
                <span>Completion：{numberFormatter.format(record.completion_tokens)}</span>
                <span>{formatTime(record.created_at)}</span>
              </div>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}

function Overview({ data }: { data: DashboardData | null }) {
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
  if (platform === "web") {
    return "Web";
  }
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

function formatMilliseconds(value: number) {
  if (value >= 1000) {
    const seconds = value / 1000;
    return `${seconds >= 10 ? seconds.toFixed(0) : seconds.toFixed(1)} 秒`;
  }
  return `${numberFormatter.format(value)} ms`;
}

export default App;
