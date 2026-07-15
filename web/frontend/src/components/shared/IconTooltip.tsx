import { useState, type ReactNode } from "react";

export function IconTooltip({
  children,
  label,
}: {
  children: ReactNode;
  label: string;
}) {
  const [visible, setVisible] = useState(false);

  return (
    <span
      className="relative inline-flex"
      onBlur={() => setVisible(false)}
      onClickCapture={() => {
        // 点击后按钮仍会保持焦点，主动关闭以免提示悬停在已打开的面板上。
        setVisible(false);
      }}
      onFocus={() => setVisible(true)}
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
    >
      {children}
      <span
        aria-hidden={!visible}
        className={`pointer-events-none absolute right-0 top-full z-50 mt-2 whitespace-nowrap border-2 border-foreground bg-card px-2 py-1 text-xs font-bold text-foreground shadow-[2px_2px_0_hsl(var(--foreground))] ${visible ? "opacity-100" : "opacity-0"}`}
        role="tooltip"
      >
        {label}
      </span>
    </span>
  );
}
