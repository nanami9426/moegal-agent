import type { LucideIcon } from "lucide-react";

import { numberFormatter } from "@/lib/format";

interface StatusPillProps {
  icon: LucideIcon;
  label: string;
  value: number;
}

export function StatusPill({ icon: Icon, label, value }: StatusPillProps) {
  return (
    <div className="flex h-10 items-center gap-2 rounded-md border bg-card px-3 text-sm shadow-sm">
      <Icon className="h-4 w-4 text-primary" />
      <span className="text-muted-foreground">{label}</span>
      <span className="font-semibold">{numberFormatter.format(value)}</span>
    </div>
  );
}
