import {
  Bot,
  History,
  type LucideIcon,
} from "lucide-react";

import type {
  TokenUsageByModelItem,
  TokenUsageRecordItem,
} from "@/lib/api";
import {
  formatMilliseconds,
  formatTime,
  numberFormatter,
} from "@/lib/format";

import { EmptyState } from "@/components/shared/EmptyState";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

export function UsageMetricCard({
  icon: Icon,
  label,
  value,
  detail,
}: {
  icon: LucideIcon;
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

export function ModelUsagePanel({ models }: { models: TokenUsageByModelItem[] }) {
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
              <div className="pixel-inset bg-background p-4" key={model.model}>
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
                <div className="mt-3 h-3 overflow-hidden border-2 border-foreground bg-muted">
                  <div
                    className="h-full bg-primary"
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

export function RecentUsagePanel({ records }: { records: TokenUsageRecordItem[] }) {
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
            <div className="pixel-inset bg-background p-4" key={record.id}>
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
