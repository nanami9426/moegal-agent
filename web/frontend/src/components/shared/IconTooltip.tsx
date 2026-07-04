import type { ReactNode } from "react";

export function IconTooltip({
  children,
  label,
}: {
  children: ReactNode;
  label: string;
}) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span className="pointer-events-none absolute right-0 top-full z-50 mt-2 whitespace-nowrap border-2 border-foreground bg-card px-2 py-1 text-xs font-bold text-foreground opacity-0 shadow-[2px_2px_0_hsl(var(--foreground))] group-focus-within:opacity-100 group-hover:opacity-100">
        {label}
      </span>
    </span>
  );
}
