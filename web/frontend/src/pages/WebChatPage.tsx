import {
  type FormEvent,
  useEffect,
  useState,
} from "react";
import {
  AlertCircle,
  Bot,
  KeyRound,
  LogIn,
  LogOut,
  MessageCircle,
  Plus,
  RefreshCcw,
  Send,
  Shield,
  UserPlus,
} from "lucide-react";
import { toast } from "sonner";

import {
  fetchCurrentWebUser,
  fetchWebChatHistory,
  loginWebUser,
  logoutWebUser,
  registerWebUser,
  startNewWebChat,
  streamWebChatMessage,
  type WebUser,
} from "@/lib/api";
import { webTokenStorageKey } from "@/lib/auth";
import { cn } from "@/lib/utils";

import { ChatBubble } from "@/components/chat/ChatBubble";
import {
  messagesFromConversations,
  type ChatMessageView,
} from "@/components/chat/chatMessages";
import { LoadingScreen } from "@/components/shared/LoadingScreen";
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

export function WebChatPage() {
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
    return <LoadingScreen label="正在恢复登录" />;
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
                    className={cn(
                      authMode === "login" && "border-primary bg-primary/10 text-primary",
                    )}
                    onClick={() => setAuthMode("login")}
                    type="button"
                    variant="outline"
                  >
                    <LogIn />
                    登录
                  </Button>
                  <Button
                    className={cn(
                      authMode === "register" && "border-primary bg-primary/10 text-primary",
                    )}
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
                        onChange={(event) =>
                          setAuthForm((current) => ({
                            ...current,
                            userId: event.target.value,
                          }))
                        }
                        value={authForm.userId}
                      />
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <Label htmlFor="web-username">用户名</Label>
                      <Input
                        autoComplete="username"
                        id="web-username"
                        onChange={(event) =>
                          setAuthForm((current) => ({
                            ...current,
                            username: event.target.value,
                          }))
                        }
                        value={authForm.username}
                      />
                    </div>
                  )}

                  <div className="space-y-2">
                    <Label htmlFor="web-password">密码</Label>
                    <Input
                      autoComplete={authMode === "login" ? "current-password" : "new-password"}
                      id="web-password"
                      onChange={(event) =>
                        setAuthForm((current) => ({
                          ...current,
                          password: event.target.value,
                        }))
                      }
                      type="password"
                      value={authForm.password}
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
