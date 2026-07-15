import { useEffect, useState } from "react";
import { Brain, RefreshCcw, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  clearWebMemories,
  deleteWebMemory,
  fetchMemorySettings,
  fetchWebMemories,
  updateMemorySettings,
  updateWebMemory,
  type MemoryItem,
  type MemorySettings,
} from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";


export function MemoryPanel({ token }: { token: string }) {
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [settings, setSettings] = useState<MemorySettings | null>(null);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setIsLoading(true);
      try {
        const [memoryItems, memorySettings] = await Promise.all([
          fetchWebMemories(token),
          fetchMemorySettings(token),
        ]);
        if (cancelled) return;
        setMemories(memoryItems);
        setSettings(memorySettings);
        setDrafts(Object.fromEntries(memoryItems.map((item) => [item.id, item.content])));
      } catch (error) {
        toast.error("读取记忆失败", {
          description: error instanceof Error ? error.message : "请稍后再试。",
        });
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function changeSetting(
    key: "enabled" | "auto_extract" | "use_chat_history",
    value: boolean,
  ) {
    try {
      const updated = await updateMemorySettings(token, { [key]: value });
      setSettings(updated);
    } catch (error) {
      toast.error("更新记忆设置失败", {
        description: error instanceof Error ? error.message : "请稍后再试。",
      });
    }
  }

  async function saveMemory(memory: MemoryItem) {
    const content = (drafts[memory.id] ?? "").trim();
    if (!content) return;
    try {
      const updated = await updateWebMemory(token, memory.id, { content });
      setMemories((current) => current.map((item) => item.id === updated.id ? updated : item));
      toast.success("记忆已更新");
    } catch (error) {
      toast.error("更新记忆失败", {
        description: error instanceof Error ? error.message : "请稍后再试。",
      });
    }
  }

  async function removeMemory(memoryId: number) {
    try {
      await deleteWebMemory(token, memoryId);
      setMemories((current) => current.filter((item) => item.id !== memoryId));
      toast.success("记忆已删除");
    } catch (error) {
      toast.error("删除记忆失败", {
        description: error instanceof Error ? error.message : "请稍后再试。",
      });
    }
  }

  async function clearAll() {
    if (!window.confirm("确定清空全部长期记忆吗？聊天记录不会被删除。")) return;
    const result = await clearWebMemories(token);
    setMemories([]);
    setDrafts({});
    toast.success(`已清空 ${result.deleted_count} 条记忆`);
  }

  return (
    <section className="pixel-panel mb-4 bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 font-semibold"><Brain className="h-4 w-4" />长期记忆</div>
          <p className="mt-1 text-xs text-muted-foreground">可查看、纠正或删除模型用于个性化的资料。</p>
        </div>
        <Button disabled={memories.length === 0} onClick={() => void clearAll()} size="sm" variant="outline">
          <Trash2 />清空
        </Button>
      </div>

      {settings ? (
        <div className="mt-4 grid gap-2 text-sm sm:grid-cols-3">
          <SettingCheckbox checked={settings.enabled} label="启用长期记忆" onChange={(value) => void changeSetting("enabled", value)} />
          <SettingCheckbox checked={settings.auto_extract} label="后台自动整理" onChange={(value) => void changeSetting("auto_extract", value)} />
          <SettingCheckbox checked={settings.use_chat_history} label="引用历史会话" onChange={(value) => void changeSetting("use_chat_history", value)} />
        </div>
      ) : null}

      {isLoading ? (
        <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground"><RefreshCcw className="h-4 w-4 animate-spin" />正在读取</div>
      ) : memories.length === 0 ? (
        <p className="mt-4 text-sm text-muted-foreground">暂时没有长期记忆。</p>
      ) : (
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          {memories.map((memory) => (
            <article className="border-2 border-foreground bg-background p-3" key={memory.id}>
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <Badge variant="outline">{memory.kind}</Badge>
                <span className="text-xs font-bold text-muted-foreground">{memory.key}</span>
              </div>
              <textarea
                className="min-h-20 w-full resize-y border-2 border-input bg-card p-2 text-sm"
                onChange={(event) => setDrafts((current) => ({ ...current, [memory.id]: event.target.value }))}
                value={drafts[memory.id] ?? memory.content}
              />
              <div className="mt-2 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                <span>{memory.source} · 使用 {memory.access_count} 次</span>
                <div className="flex gap-2">
                  <Button onClick={() => void saveMemory(memory)} size="sm" type="button" variant="outline"><Save />保存</Button>
                  <Button onClick={() => void removeMemory(memory.id)} size="sm" type="button" variant="outline"><Trash2 />删除</Button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}


function SettingCheckbox({
  checked,
  label,
  onChange,
}: {
  checked: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 border-2 border-foreground bg-background p-2 font-bold">
      <input checked={checked} onChange={(event) => onChange(event.target.checked)} type="checkbox" />
      {label}
    </label>
  );
}
