import { RefreshCcw } from "lucide-react";

import { Toaster } from "@/components/ui/sonner";

export function LoadingScreen({ label }: { label: string }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background">
      <div className="flex items-center gap-3 text-sm text-muted-foreground">
        <RefreshCcw className="h-4 w-4 animate-spin" />
        {label}
      </div>
      <Toaster />
    </main>
  );
}
