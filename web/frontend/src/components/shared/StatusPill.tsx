import type { LucideIcon } from "lucide-react";

import { numberFormatter } from "@/lib/format";

interface StatusPillProps {
  icon: LucideIcon;
  label: string;
  value: number;
}

export function StatusPill({ icon: Icon, label, value }: StatusPillProps) {
  return (
    <div className="pixel-panel-sm flex h-10 items-center gap-2 bg-card px-3 text-sm">
      <Icon className="h-4 w-4 text-primary" />
      <span className="text-muted-foreground">{label}</span>
      <span className="font-bold">{numberFormatter.format(value)}</span>
    </div>
  );
}
