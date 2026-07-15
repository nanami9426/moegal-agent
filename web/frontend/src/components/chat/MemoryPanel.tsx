import { useEffect, useState } from "react";
import { Brain, RefreshCcw, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  clearMemoryDocument,
  fetchMemoryDocument,
  fetchMemorySettings,
  updateMemoryDocument,
  updateMemorySettings,
  type MemorySettings,
} from "@/lib/api";
import { Button } from "@/components/ui/button";


const EMPTY_MEMORY_TEMPLATE = `# 用户记忆

## 基本资料

## 稳定偏好

## 禁忌与边界

## 长期目标与待办`;


export function MemoryPanel({ token }: { token: string }) {
  const [content, setContent] = useState("");
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [settings, setSettings] = useState<MemorySettings | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setIsLoading(true);
      try {
        const [document, memorySettings] = await Promise.all([
          fetchMemoryDocument(token),
          fetchMemorySettings(token),
        ]);
        if (cancelled) return;
        setContent(document.content);
        setUpdatedAt(document.updated_at);
        setSettings(memorySettings);
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
    key: "enabled" | "auto_extract",
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

  async function saveDocument() {
    setIsSaving(true);
    try {
      const updated = await updateMemoryDocument(token, content);
      setContent(updated.content);
      setUpdatedAt(updated.updated_at);
      toast.success("Markdown 记忆已保存");
    } catch (error) {
      toast.error("保存记忆失败", {
        description: error instanceof Error ? error.message : "请稍后再试。",
      });
    } finally {
      setIsSaving(false);
    }
  }

  async function clearDocument() {
    if (!window.confirm("确定清空整份长期记忆吗？聊天记录不会被删除。")) return;
    try {
      const updated = await clearMemoryDocument(token);
      setContent(updated.content);
      setUpdatedAt(updated.updated_at);
      toast.success("长期记忆已清空");
    } catch (error) {
      toast.error("清空记忆失败", {
        description: error instanceof Error ? error.message : "请稍后再试。",
      });
    }
  }

  return (
    <section className="pixel-panel mb-4 bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 font-semibold">
            <Brain className="h-4 w-4" />长期记忆
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            机器人会定期整理这份 Markdown；你也可以直接修改并保存整份文档。
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            disabled={isSaving || isLoading}
            onClick={() => void saveDocument()}
            size="sm"
          >
            <Save />{isSaving ? "保存中" : "保存"}
          </Button>
          <Button
            disabled={!content || isLoading}
            onClick={() => void clearDocument()}
            size="sm"
            variant="outline"
          >
            <Trash2 />清空
          </Button>
        </div>
      </div>

      {settings ? (
        <div className="mt-4 grid gap-2 text-sm sm:grid-cols-2">
          <SettingCheckbox
            checked={settings.enabled}
            label="启用长期记忆"
            onChange={(value) => void changeSetting("enabled", value)}
          />
          <SettingCheckbox
            checked={settings.auto_extract}
            label="后台自动整理"
            onChange={(value) => void changeSetting("auto_extract", value)}
          />
        </div>
      ) : null}

      {isLoading ? (
        <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
          <RefreshCcw className="h-4 w-4 animate-spin" />正在读取
        </div>
      ) : (
        <>
          <textarea
            className="mt-4 min-h-96 w-full resize-y border-2 border-input bg-background p-3 font-mono text-sm leading-6"
            maxLength={16_000}
            onChange={(event) => setContent(event.target.value)}
            placeholder={EMPTY_MEMORY_TEMPLATE}
            spellCheck={false}
            value={content}
          />
          <div className="mt-2 flex justify-between text-xs text-muted-foreground">
            <span>{content.length} / 16000 字符</span>
            <span>
              {updatedAt ? `更新于 ${new Date(updatedAt).toLocaleString()}` : "尚未保存"}
            </span>
          </div>
        </>
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
      <input
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        type="checkbox"
      />
      {label}
    </label>
  );
}
