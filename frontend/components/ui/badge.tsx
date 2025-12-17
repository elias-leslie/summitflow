"use client";

import { type ReactNode } from "react";
import { clsx } from "clsx";

type BadgeVariant = "default" | "phosphor" | "amber" | "rose" | "slate" | "outline";

interface BadgeProps {
  variant?: BadgeVariant;
  children: ReactNode;
  className?: string;
}

const variants: Record<BadgeVariant, string> = {
  default: "bg-slate-700/50 text-slate-300 border border-slate-600",
  phosphor: "bg-phosphor-500/15 text-phosphor-400 border border-phosphor-500/30",
  amber: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
  rose: "bg-rose-500/15 text-rose-400 border border-rose-500/30",
  slate: "bg-slate-800 text-slate-400 border border-slate-700",
  outline: "bg-transparent text-slate-400 border border-slate-600",
};

export function Badge({ variant = "default", children, className }: BadgeProps) {
  return (
    <span
      className={clsx(
        "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium mono",
        variants[variant],
        className
      )}
    >
      {children}
    </span>
  );
}

// Convenience wrappers for common status badges
export function SuccessBadge({ children, className }: { children: ReactNode; className?: string }) {
  return <Badge variant="phosphor" className={className}>{children}</Badge>;
}

export function WarningBadge({ children, className }: { children: ReactNode; className?: string }) {
  return <Badge variant="amber" className={className}>{children}</Badge>;
}

export function ErrorBadge({ children, className }: { children: ReactNode; className?: string }) {
  return <Badge variant="rose" className={className}>{children}</Badge>;
}
