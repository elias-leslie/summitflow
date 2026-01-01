"use client";

import { Loader2, FileEdit, Eye, MessageSquare, CheckCircle2 } from "lucide-react";
import type { EnrichmentStatus } from "@/lib/api/tasks";

interface EnrichmentStatusBadgeProps {
  status: EnrichmentStatus | null | undefined;
  className?: string;
}

const statusConfig: Record<
  Exclude<EnrichmentStatus, "none" | "accepted">,
  {
    label: string;
    icon: React.ElementType;
    className: string;
  }
> = {
  draft: {
    label: "Draft",
    icon: FileEdit,
    className: "text-slate-400 bg-slate-800 border-slate-700",
  },
  enriching: {
    label: "Enriching",
    icon: Loader2,
    className: "text-blue-400 bg-blue-500/10 border-blue-500/20",
  },
  review: {
    label: "Review",
    icon: Eye,
    className: "text-amber-400 bg-amber-500/10 border-amber-500/20",
  },
  discussing: {
    label: "Discussing",
    icon: MessageSquare,
    className: "text-violet-400 bg-violet-500/10 border-violet-500/20",
  },
  failed: {
    label: "Failed",
    icon: CheckCircle2,
    className: "text-red-400 bg-red-500/10 border-red-500/20",
  },
};

export function EnrichmentStatusBadge({
  status,
  className = "",
}: EnrichmentStatusBadgeProps) {
  // Don't show badge for none, accepted, or undefined
  if (!status || status === "none" || status === "accepted") {
    return null;
  }

  const config = statusConfig[status];
  if (!config) return null;

  const Icon = config.icon;
  const isAnimated = status === "enriching";

  return (
    <span
      className={`
        inline-flex items-center gap-1 px-1.5 py-0.5
        text-2xs font-medium rounded border
        ${config.className}
        ${className}
      `}
    >
      <Icon className={`w-3 h-3 ${isAnimated ? "animate-spin" : ""}`} />
      <span>{config.label}</span>
    </span>
  );
}
