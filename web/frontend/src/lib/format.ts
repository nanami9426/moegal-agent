import type { Platform } from "@/lib/api";

export const numberFormatter = new Intl.NumberFormat("zh-CN");

export function clampNumber(value: string, min: number, max: number) {
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) {
    return min;
  }
  return Math.min(max, Math.max(min, parsed));
}

export function formatPlatform(platform: Platform) {
  if (platform === "web") {
    return "Web";
  }
  return platform === "tg" ? "Telegram" : "QQ";
}

export function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(date);
}

export function formatMilliseconds(value: number) {
  if (value >= 1000) {
    const seconds = value / 1000;
    return `${seconds >= 10 ? seconds.toFixed(0) : seconds.toFixed(1)} 秒`;
  }
  return `${numberFormatter.format(value)} ms`;
}
