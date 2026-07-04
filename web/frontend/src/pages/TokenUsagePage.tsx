import {
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  AlertCircle,
  Bot,
  Clock3,
  History,
  KeyRound,
  LogOut,
  MessageCircle,
  RefreshCcw,
  Search,
  Shield,
} from "lucide-react";
import { toast } from "sonner";

import {
  fetchAdminBindings,
  fetchCurrentWebUser,
  fetchTokenUsage,
  logoutWebUser,
  type PlatformBindingItem,
  type TokenUsageData,
  type WebUser,
} from "@/lib/api";
import { webTokenStorageKey } from "@/lib/auth";
import {
  clampNumber,
  formatMilliseconds,
  formatPlatform,
  formatTime,
  numberFormatter,
} from "@/lib/format";
import { cn } from "@/lib/utils";

import { BindingAccountButton } from "@/components/shared/BindingAccountButton";
import { LoadingScreen } from "@/components/shared/LoadingScreen";
import { LoginGate } from "@/components/shared/LoginGate";
import { OverviewSkeleton } from "@/components/shared/SkeletonPanels";
import { StatusPill } from "@/components/shared/StatusPill";
import {
  ModelUsagePanel,
  RecentUsagePanel,
  UsageMetricCard,
} from "@/components/usage/UsagePanels";
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

export function TokenUsagePage() {
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
            initialUsage = await fetchTokenUsage(
              {
                platform: firstBinding.platform,
                platformUserId: firstBinding.platform_user_id,
                recentLimit,
              },
              activeToken,
            );
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
      const payload = await fetchTokenUsage(
        {
          platform: binding.platform,
          platformUserId: binding.platform_user_id,
          recentLimit,
        },
        activeToken,
      );
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
    return <LoadingScreen label="正在读取用量" />;
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
