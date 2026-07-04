import type { PlatformBindingItem } from "@/lib/api";
import { formatPlatform, formatTime } from "@/lib/format";
import { cn } from "@/lib/utils";

import { Badge } from "@/components/ui/badge";

interface BindingAccountButtonProps {
  active: boolean;
  binding: PlatformBindingItem;
  onClick: () => void;
}

export function BindingAccountButton({
  active,
  binding,
  onClick,
}: BindingAccountButtonProps) {
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
