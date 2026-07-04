import { Search } from "lucide-react";

import { cn } from "@/lib/utils";

interface EmptyStateProps {
  title: string;
  description: string;
  dense?: boolean;
}

export function EmptyState({ title, description, dense = false }: EmptyStateProps) {
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
