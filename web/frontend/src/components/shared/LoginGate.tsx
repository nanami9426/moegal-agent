import { LogIn, Shield } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Toaster } from "@/components/ui/sonner";

interface LoginGateProps {
  title: string;
  description: string;
}

export function LoginGate({ title, description }: LoginGateProps) {
  return (
    <main className="relative min-h-screen overflow-hidden">
      <div className="surface-grid pointer-events-none absolute inset-x-0 top-0 h-80" />
      <div className="container relative z-10 flex min-h-screen max-w-3xl items-center justify-center py-8">
        <Card className="w-full max-w-md">
          <CardHeader>
            <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <Shield className="h-5 w-5" />
            </div>
            <CardTitle>{title}</CardTitle>
            <CardDescription>{description}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Button asChild className="w-full">
              <a href="/">
                <LogIn />
                去登录
              </a>
            </Button>
          </CardContent>
        </Card>
      </div>
      <Toaster />
    </main>
  );
}
