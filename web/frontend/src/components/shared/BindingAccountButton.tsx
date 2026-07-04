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
        "pixel-panel-sm w-full bg-background p-3 text-left text-sm font-bold transition-none hover:bg-secondary",
        active && "bg-primary text-primary-foreground",
      )}
      onClick={onClick}
      type="button"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate">{title}</span>
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
