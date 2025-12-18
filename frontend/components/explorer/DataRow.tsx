/**
 * DataRow - Expandable row with status border
 *
 * Generic expandable row component that renders custom content
 * and an optional detail panel when expanded.
 */

"use client";

import { useState, useCallback } from "react";
import { cn } from "@/lib/utils";
import { ChevronRight, ChevronDown } from "lucide-react";
import { StatusBorder } from "./StatusIndicator";
import type { HealthStatus } from "./types";

interface DataRowProps {
  id: string;
  healthStatus: HealthStatus;
  isExpanded: boolean;
  onToggle: (id: string) => void;
  renderContent: () => React.ReactNode;
  renderDetail?: () => React.ReactNode;
  depth?: number;
  hasChildren?: boolean;
  className?: string;
}

export function DataRow({
  id,
  healthStatus,
  isExpanded,
  onToggle,
  renderContent,
  renderDetail,
  depth = 0,
  hasChildren = false,
  className,
}: DataRowProps) {
  const handleClick = useCallback(() => {
    onToggle(id);
  }, [id, onToggle]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onToggle(id);
      }
    },
    [id, onToggle]
  );

  return (
    <div className={cn("group", className)}>
      {/* Row content */}
      <StatusBorder status={healthStatus}>
        <div
          role="button"
          tabIndex={0}
          onClick={handleClick}
          onKeyDown={handleKeyDown}
          className={cn(
            "flex items-center gap-2 px-3 py-2.5",
            "cursor-pointer select-none",
            "transition-colors duration-100",
            "hover:bg-slate-800/40",
            isExpanded && "bg-slate-800/30"
          )}
          style={{ paddingLeft: depth * 20 + 12 }}
        >
          {/* Expand/collapse chevron */}
          {hasChildren || renderDetail ? (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onToggle(id);
              }}
              className={cn(
                "flex-shrink-0 p-0.5 rounded",
                "text-slate-500 hover:text-slate-300",
                "hover:bg-slate-700/50 transition-colors"
              )}
            >
              {isExpanded ? (
                <ChevronDown className="w-4 h-4" />
              ) : (
                <ChevronRight className="w-4 h-4" />
              )}
            </button>
          ) : (
            <span className="w-5" /> // Spacer for alignment
          )}

          {/* Custom content */}
          {renderContent()}
        </div>
      </StatusBorder>

      {/* Expandable detail panel */}
      {renderDetail && (
        <div
          className={cn(
            "grid transition-all duration-200 ease-out",
            isExpanded ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
          )}
        >
          <div className="overflow-hidden">
            <div
              className={cn(
                "mx-3 mb-2 p-4 rounded-lg",
                "bg-slate-900/50 border border-slate-700/50",
                "animate-in fade-in-0 slide-in-from-top-1 duration-200"
              )}
              style={{ marginLeft: depth * 20 + 24 }}
            >
              {renderDetail()}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * DataRowSkeleton - Loading placeholder
 */
export function DataRowSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="space-y-1 p-2">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="flex items-center gap-3 px-3 py-3 animate-pulse"
          style={{ animationDelay: `${i * 50}ms` }}
        >
          <div className="w-4 h-4 rounded bg-slate-800" />
          <div className="w-4 h-4 rounded bg-slate-800" />
          <div
            className="h-4 rounded bg-slate-800"
            style={{ width: `${150 + Math.random() * 100}px` }}
          />
          <div className="flex-1" />
          <div className="w-16 h-4 rounded bg-slate-800" />
          <div className="w-12 h-4 rounded bg-slate-800" />
        </div>
      ))}
    </div>
  );
}
