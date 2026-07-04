import {
  isValidElement,
  type HTMLAttributes,
  type ReactNode,
  useState,
} from "react";
import {
  Check,
  Copy,
} from "lucide-react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

import { Button } from "@/components/ui/button";

function CodeBlock({
  children,
  className,
  ...props
}: HTMLAttributes<HTMLPreElement>) {
  const [hasCopied, setHasCopied] = useState(false);
  const code = extractText(children).replace(/\n$/, "");

  async function copyCode() {
    if (!code) {
      return;
    }
    try {
      await navigator.clipboard.writeText(code);
      setHasCopied(true);
      window.setTimeout(() => setHasCopied(false), 1400);
    } catch {
      setHasCopied(false);
    }
  }

  return (
    <div className="relative">
      <Button
        aria-label={hasCopied ? "已复制代码" : "复制代码"}
        className="absolute right-2 top-2 h-8 w-8 border-card/40 bg-card/20 text-card opacity-70 shadow-none hover:bg-card/35 hover:text-card hover:opacity-100 focus-visible:bg-card/35 focus-visible:text-card focus-visible:opacity-100"
        onClick={() => void copyCode()}
        size="icon"
        type="button"
        variant="outline"
      >
        {hasCopied ? <Check /> : <Copy />}
      </Button>
      <pre
        className={cn(
          "overflow-x-auto border-2 border-foreground bg-foreground p-3 pr-12 text-card shadow-[3px_3px_0_hsl(var(--muted-foreground))] [&_code]:block [&_code]:border-0 [&_code]:bg-transparent [&_code]:p-0 [&_code]:text-sm [&_code]:font-normal [&_code]:leading-6",
          className,
        )}
        {...props}
      >
        {children}
      </pre>
    </div>
  );
}

function extractText(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map(extractText).join("");
  }
  if (isValidElement<{ children?: ReactNode }>(node)) {
    return extractText(node.props.children);
  }
  return "";
}

const markdownComponents: Components = {
  a({ className, ...props }) {
    return (
      <a
        className={cn("font-bold text-primary underline underline-offset-4", className)}
        rel="noreferrer"
        target="_blank"
        {...props}
      />
    );
  },
  blockquote({ className, ...props }) {
    return (
      <blockquote
        className={cn(
          "border-l-4 border-foreground bg-muted px-3 py-2 text-muted-foreground",
          className,
        )}
        {...props}
      />
    );
  },
  code({ className, children, ...props }) {
    return (
      <code
        className={cn(
          "border-2 border-foreground bg-muted px-1.5 py-0.5 font-mono text-[0.92em] font-bold",
          className,
        )}
        {...props}
      >
        {children}
      </code>
    );
  },
  h1({ className, ...props }) {
    return <h1 className={cn("text-lg font-bold leading-7", className)} {...props} />;
  },
  h2({ className, ...props }) {
    return <h2 className={cn("text-base font-bold leading-6", className)} {...props} />;
  },
  h3({ className, ...props }) {
    return <h3 className={cn("text-sm font-bold leading-6", className)} {...props} />;
  },
  hr({ className, ...props }) {
    return <hr className={cn("border-0 border-t-2 border-foreground", className)} {...props} />;
  },
  ol({ className, ...props }) {
    return <ol className={cn("list-decimal space-y-1 pl-5", className)} {...props} />;
  },
  p({ className, ...props }) {
    return <p className={cn("leading-6", className)} {...props} />;
  },
  pre({ className, children, ...props }) {
    return (
      <CodeBlock className={className} {...props}>
        {children}
      </CodeBlock>
    );
  },
  table({ className, ...props }) {
    return (
      <div className="overflow-x-auto">
        <table
          className={cn("w-full border-2 border-foreground text-left text-sm", className)}
          {...props}
        />
      </div>
    );
  },
  td({ className, ...props }) {
    return <td className={cn("border-2 border-foreground px-2 py-1", className)} {...props} />;
  },
  th({ className, ...props }) {
    return (
      <th
        className={cn("border-2 border-foreground bg-secondary px-2 py-1 font-bold", className)}
        {...props}
      />
    );
  },
  ul({ className, ...props }) {
    return <ul className={cn("list-disc space-y-1 pl-5", className)} {...props} />;
  },
};

export function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="space-y-3 break-words text-sm">
      <Markdown components={markdownComponents} remarkPlugins={[remarkGfm]}>
        {content}
      </Markdown>
    </div>
  );
}
