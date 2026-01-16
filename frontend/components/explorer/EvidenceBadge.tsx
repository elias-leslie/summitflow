/**
 * EvidenceBadge - Evidence capture indicator for explorer rows
 *
 * Shows evidence count and freshness status with color coding:
 * - Green: Fresh (< 7 days)
 * - Yellow: Stale (7-30 days)
 * - Red: Very stale (> 30 days) or missing
 */

"use client";

import { Camera } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

type EvidenceFreshness = "fresh" | "stale" | "very-stale" | "missing";

interface EvidenceBadgeProps {
  evidenceCount: number;
  lastEvidenceAt: string | null;
  className?: string;
}

const DAYS_FRESH = 7;
const DAYS_STALE = 30;

function getEvidenceFreshness(
  evidenceCount: number,
  lastEvidenceAt: string | null,
): EvidenceFreshness {
  if (evidenceCount === 0 || !lastEvidenceAt) {
    return "missing";
  }

  const lastDate = new Date(lastEvidenceAt);
  const now = new Date();
  const daysSince = Math.floor(
    (now.getTime() - lastDate.getTime()) / (1000 * 60 * 60 * 24),
  );

  if (daysSince < DAYS_FRESH) {
    return "fresh";
  } else if (daysSince < DAYS_STALE) {
    return "stale";
  }
  return "very-stale";
}

function formatRelativeTime(dateString: string | null): string {
  if (!dateString) return "Never captured";

  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / (1000 * 60));
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 30) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

const freshnessConfig: Record<
  EvidenceFreshness,
  { iconClass: string; bgClass: string; label: string }
> = {
  fresh: {
    iconClass: "text-phosphor-400",
    bgClass: "bg-phosphor-500/10",
    label: "Fresh evidence",
  },
  stale: {
    iconClass: "text-amber-400",
    bgClass: "bg-amber-500/10",
    label: "Stale evidence",
  },
  "very-stale": {
    iconClass: "text-rose-400",
    bgClass: "bg-rose-500/10",
    label: "Very stale evidence",
  },
  missing: {
    iconClass: "text-slate-500",
    bgClass: "bg-slate-500/10",
    label: "No evidence",
  },
};

export function EvidenceBadge({
  evidenceCount,
  lastEvidenceAt,
  className,
}: EvidenceBadgeProps) {
  const freshness = getEvidenceFreshness(evidenceCount, lastEvidenceAt);
  const config = freshnessConfig[freshness];
  const relativeTime = formatRelativeTime(lastEvidenceAt);

  return (
    <TooltipProvider>
      <Tooltip delayDuration={300}>
        <TooltipTrigger asChild>
          <span
            className={cn(
              "inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs",
              config.bgClass,
              className,
            )}
            data-testid="evidence-badge"
          >
            <Camera className={cn("w-3 h-3", config.iconClass)} />
            {evidenceCount > 0 && (
              <span className={cn("font-medium", config.iconClass)}>
                {evidenceCount}
              </span>
            )}
          </span>
        </TooltipTrigger>
        <TooltipContent side="top" className="text-xs">
          <div className="space-y-1">
            <div className="font-medium">{config.label}</div>
            <div className="text-slate-400">
              {evidenceCount > 0
                ? `${evidenceCount} capture${evidenceCount !== 1 ? "s" : ""}`
                : "No captures yet"}
            </div>
            <div className="text-slate-400">Last: {relativeTime}</div>
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/**
 * EvidenceBadgeSkeleton - Loading placeholder
 */
export function EvidenceBadgeSkeleton() {
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-slate-800 animate-pulse">
      <span className="w-3 h-3 rounded bg-slate-700" />
      <span className="w-4 h-3 rounded bg-slate-700" />
    </span>
  );
}
