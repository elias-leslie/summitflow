/**
 * TypeNavigator - Left sidebar type selector
 *
 * Vertical icon bar for switching between explorer types.
 * Features glowing active states and type-specific colors.
 */

"use client";

import { cn } from "@/lib/utils";
import { Folder, Database, Zap, Globe, Filter, Search } from "lucide-react";
import type { ExplorerType } from "./types";
import type { HealthStatus } from "./types";

interface TypeNavigatorProps {
  activeType: ExplorerType;
  onTypeChange: (type: ExplorerType) => void;
  activeFilter: HealthStatus | "all";
  onFilterChange: (filter: HealthStatus | "all") => void;
  counts?: Record<ExplorerType, number>;
  className?: string;
}

const typeConfig: Record<
  ExplorerType,
  {
    icon: typeof Folder;
    label: string;
    color: string;
    activeClass: string;
    glowClass: string;
  }
> = {
  files: {
    icon: Folder,
    label: "Files",
    color: "text-purple-400",
    activeClass: "bg-purple-500/20 border-purple-500/50 text-purple-300",
    glowClass: "shadow-[0_0_12px_rgba(168,85,247,0.4)]",
  },
  database: {
    icon: Database,
    label: "Database",
    color: "text-cyan-400",
    activeClass: "bg-cyan-500/20 border-cyan-500/50 text-cyan-300",
    glowClass: "shadow-[0_0_12px_rgba(34,211,238,0.4)]",
  },
  celery: {
    icon: Zap,
    label: "Tasks",
    color: "text-orange-400",
    activeClass: "bg-orange-500/20 border-orange-500/50 text-orange-300",
    glowClass: "shadow-[0_0_12px_rgba(251,146,60,0.4)]",
  },
  api: {
    icon: Globe,
    label: "API",
    color: "text-lime-400",
    activeClass: "bg-lime-500/20 border-lime-500/50 text-lime-300",
    glowClass: "shadow-[0_0_12px_rgba(163,230,53,0.4)]",
  },
};

const filterConfig: Record<
  HealthStatus | "all",
  { label: string; dotClass: string }
> = {
  all: { label: "All", dotClass: "bg-slate-500" },
  fresh: { label: "Fresh", dotClass: "bg-phosphor-500" },
  active: { label: "Active", dotClass: "bg-phosphor-500" },
  stale: { label: "Stale", dotClass: "bg-amber-400" },
  orphan: { label: "Orphan", dotClass: "bg-rose-500" },
  unknown: { label: "Unknown", dotClass: "bg-slate-600" },
};

export function TypeNavigator({
  activeType,
  onTypeChange,
  activeFilter,
  onFilterChange,
  counts,
  className,
}: TypeNavigatorProps) {
  const types: ExplorerType[] = ["files", "database", "celery", "api"];
  const filters: (HealthStatus | "all")[] = [
    "all",
    "fresh",
    "stale",
    "orphan",
  ];

  return (
    <nav
      className={cn(
        "flex flex-col w-16 bg-slate-900/50 border-r border-slate-700/50",
        "py-4 gap-1",
        className
      )}
    >
      {/* Type selector buttons */}
      <div className="flex flex-col gap-1 px-2">
        {types.map((type) => {
          const config = typeConfig[type];
          const Icon = config.icon;
          const isActive = activeType === type;
          const count = counts?.[type];

          return (
            <button
              key={type}
              onClick={() => onTypeChange(type)}
              className={cn(
                "relative flex flex-col items-center justify-center",
                "w-12 h-12 rounded-lg border transition-all duration-200",
                "hover:bg-slate-800/50",
                isActive
                  ? cn(config.activeClass, config.glowClass, "border")
                  : "border-transparent text-slate-500 hover:text-slate-300"
              )}
              title={config.label}
            >
              <Icon className="w-5 h-5" />
              {count !== undefined && count > 0 && (
                <span
                  className={cn(
                    "absolute -top-1 -right-1 min-w-[18px] h-[18px]",
                    "flex items-center justify-center",
                    "text-[10px] font-bold rounded-full",
                    isActive
                      ? "bg-slate-900 text-slate-300"
                      : "bg-slate-700 text-slate-400"
                  )}
                >
                  {count > 99 ? "99+" : count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Divider */}
      <div className="my-3 mx-3 border-t border-slate-700/50" />

      {/* Quick filters */}
      <div className="flex flex-col gap-1 px-2">
        <div className="flex items-center justify-center mb-1">
          <Filter className="w-3 h-3 text-slate-600" />
        </div>
        {filters.map((filter) => {
          const config = filterConfig[filter];
          const isActive = activeFilter === filter;

          return (
            <button
              key={filter}
              onClick={() => onFilterChange(filter)}
              className={cn(
                "flex items-center justify-center gap-2",
                "w-12 h-8 rounded-md transition-all duration-150",
                isActive
                  ? "bg-slate-800 text-slate-200"
                  : "text-slate-500 hover:text-slate-300 hover:bg-slate-800/30"
              )}
              title={config.label}
            >
              <span
                className={cn("w-2 h-2 rounded-full", config.dotClass)}
              />
            </button>
          );
        })}
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Search button at bottom */}
      <div className="px-2">
        <button
          className={cn(
            "flex items-center justify-center",
            "w-12 h-10 rounded-lg transition-all duration-150",
            "text-slate-500 hover:text-phosphor-400 hover:bg-slate-800/50"
          )}
          title="Search (Cmd+K)"
        >
          <Search className="w-4 h-4" />
        </button>
      </div>
    </nav>
  );
}
