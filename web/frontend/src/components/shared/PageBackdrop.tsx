import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function PageBackdrop({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <main className={cn("relative min-h-screen overflow-hidden", className)}>
      <div className="surface-grid pointer-events-none absolute inset-x-0 top-0 h-80" />
      {children}
    </main>
  );
}
