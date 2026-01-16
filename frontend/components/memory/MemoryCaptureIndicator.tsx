"use client";

import { useState } from "react";
import { clsx } from "clsx";
import {
  useObservationStream,
  type ConnectionStatus,
} from "@/lib/hooks/useObservationStream";

interface MemoryCaptureIndicatorProps {
  projectId: string;
  className?: string;
}

/**
 * Small status dot indicating memory capture connection status.
 * Designed to be unobtrusive - just a pulsing dot with tooltip.
 */
export function MemoryCaptureIndicator({
  projectId,
  className,
}: MemoryCaptureIndicatorProps) {
  const { status } = useObservationStream({ projectId });
  const [showTooltip, setShowTooltip] = useState(false);

  const statusConfig: Record<
    ConnectionStatus,
    { color: string; shadow: string; pulse: boolean; text: string }
  > = {
    connected: {
      color: "bg-emerald-400",
      shadow: "shadow-[0_0_6px_rgba(52,211,153,0.6)]",
      pulse: true,
      text: "Memory capture active",
    },
    reconnecting: {
      color: "bg-amber-400",
      shadow: "shadow-[0_0_6px_rgba(251,191,36,0.6)]",
      pulse: false,
      text: "Reconnecting...",
    },
    disconnected: {
      color: "bg-rose-400",
      shadow: "shadow-[0_0_6px_rgba(251,113,133,0.6)]",
      pulse: false,
      text: "Memory capture disconnected",
    },
  };

  const config = statusConfig[status];

  return (
    <div
      className={clsx("relative", className)}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
      data-testid="memory-capture-indicator"
    >
      {/* Status dot */}
      <span
        className={clsx(
          "w-2 h-2 rounded-full block",
          config.color,
          config.shadow,
          config.pulse && "animate-pulse",
        )}
      />

      {/* Tooltip */}
      {showTooltip && (
        <div className="absolute top-full left-1/2 -translate-x-1/2 mt-2 z-50">
          <div className="px-2 py-1 text-xs bg-slate-800 border border-slate-700 rounded shadow-lg whitespace-nowrap">
            {config.text}
          </div>
        </div>
      )}
    </div>
  );
}
