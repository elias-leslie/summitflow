/**
 * ExplorerShell - Main layout container for unified explorer
 *
 * Three-panel layout:
 * - Left: TypeNavigator (type selector + filters)
 * - Center: Main content area (SummaryBar + DataList)
 * - Right: Optional detail sidebar (future)
 *
 * This component orchestrates the explorer state and renders
 * type-specific content based on the active type.
 */

"use client";

import { useState, useCallback, useMemo } from "react";
import { cn } from "@/lib/utils";
import { Folder, Database, Zap, Globe, Loader2 } from "lucide-react";
import { TypeNavigator } from "./TypeNavigator";
import { SummaryBar, ScanningOverlay } from "./SummaryBar";
import type { ExplorerType, HealthStatus, ExplorerStats } from "./types";

interface ExplorerShellProps {
  projectId: string;
  initialType?: ExplorerType;
  className?: string;
  children?: (props: ExplorerChildProps) => React.ReactNode;
}

export interface ExplorerChildProps {
  type: ExplorerType;
  filter: HealthStatus | "all";
  sortField: string;
  sortDir: "asc" | "desc";
  expandedIds: Set<string>;
  onSort: (field: string) => void;
  onToggleExpand: (id: string) => void;
  onExpandAll: () => void;
  onCollapseAll: () => void;
}

// Placeholder stats for demo - replace with real data fetching
const demoStats: Record<ExplorerType, ExplorerStats> = {
  files: {
    total: 234,
    fresh: 189,
    stale: 32,
    orphan: 13,
    lastScan: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
  },
  database: {
    total: 47,
    fresh: 38,
    stale: 7,
    orphan: 2,
    lastScan: new Date(Date.now() - 4 * 60 * 60 * 1000).toISOString(),
  },
  celery: {
    total: 23,
    fresh: 18,
    stale: 4,
    orphan: 1,
    lastScan: new Date(Date.now() - 1 * 60 * 60 * 1000).toISOString(),
  },
  api: {
    total: 89,
    fresh: 82,
    stale: 5,
    orphan: 2,
    lastScan: new Date(Date.now() - 30 * 60 * 1000).toISOString(),
  },
};

const typeIcons: Record<ExplorerType, React.ReactNode> = {
  files: <Folder className="w-5 h-5" />,
  database: <Database className="w-5 h-5" />,
  celery: <Zap className="w-5 h-5" />,
  api: <Globe className="w-5 h-5" />,
};

const typeTitles: Record<ExplorerType, string> = {
  files: "Files Explorer",
  database: "Database Tables",
  celery: "Celery Tasks",
  api: "API Endpoints",
};

export function ExplorerShell({
  projectId,
  initialType = "files",
  className,
  children,
}: ExplorerShellProps) {
  // Explorer state
  const [activeType, setActiveType] = useState<ExplorerType>(initialType);
  const [activeFilter, setActiveFilter] = useState<HealthStatus | "all">("all");
  const [sortField, setSortField] = useState("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [isScanning, setIsScanning] = useState(false);

  // Handlers
  const handleTypeChange = useCallback((type: ExplorerType) => {
    setActiveType(type);
    setExpandedIds(new Set()); // Reset expansion on type change
    setSortField("name");
    setSortDir("asc");
  }, []);

  const handleFilterChange = useCallback((filter: HealthStatus | "all") => {
    setActiveFilter(filter);
  }, []);

  const handleSort = useCallback(
    (field: string) => {
      if (sortField === field) {
        setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      } else {
        setSortField(field);
        setSortDir("asc");
      }
    },
    [sortField]
  );

  const handleToggleExpand = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const handleExpandAll = useCallback(() => {
    // This would need to be connected to actual data
    // For now, it's a placeholder
  }, []);

  const handleCollapseAll = useCallback(() => {
    setExpandedIds(new Set());
  }, []);

  const handleScan = useCallback(() => {
    setIsScanning(true);
    // Simulate scan - replace with real API call
    setTimeout(() => {
      setIsScanning(false);
    }, 3000);
  }, []);

  // Current stats
  const stats = demoStats[activeType];
  const counts = useMemo(
    () => ({
      files: demoStats.files.total,
      database: demoStats.database.total,
      celery: demoStats.celery.total,
      api: demoStats.api.total,
    }),
    []
  );

  // Props for child render function
  const childProps: ExplorerChildProps = {
    type: activeType,
    filter: activeFilter,
    sortField,
    sortDir,
    expandedIds,
    onSort: handleSort,
    onToggleExpand: handleToggleExpand,
    onExpandAll: handleExpandAll,
    onCollapseAll: handleCollapseAll,
  };

  return (
    <div
      className={cn(
        "flex h-full overflow-hidden rounded-lg",
        "bg-slate-850 border border-slate-700/50",
        className
      )}
    >
      {/* Left: Type Navigator */}
      <TypeNavigator
        activeType={activeType}
        onTypeChange={handleTypeChange}
        activeFilter={activeFilter}
        onFilterChange={handleFilterChange}
        counts={counts}
      />

      {/* Center: Main content */}
      <div className="flex-1 flex flex-col min-w-0 relative">
        {/* Scanning overlay */}
        {isScanning && <ScanningOverlay />}

        {/* Header */}
        <div
          className={cn(
            "flex items-center gap-3 px-4 py-3",
            "border-b border-slate-700/50"
          )}
        >
          <span className="text-slate-400">{typeIcons[activeType]}</span>
          <h2 className="text-lg font-semibold text-slate-100 display">
            {typeTitles[activeType]}
          </h2>
        </div>

        {/* Summary bar */}
        <SummaryBar
          type={activeType}
          stats={stats}
          activeFilter={activeFilter}
          onFilterChange={handleFilterChange}
          onScan={handleScan}
          isScanning={isScanning}
        />

        {/* Content area */}
        <div className="flex-1 overflow-hidden">
          {children ? (
            children(childProps)
          ) : (
            <ExplorerPlaceholder type={activeType} />
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Placeholder content when no children provided
 */
function ExplorerPlaceholder({ type }: { type: ExplorerType }) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-slate-500">
      <div className="opacity-20 mb-4">{typeIcons[type]}</div>
      <p className="text-sm">
        {typeTitles[type]} content will render here
      </p>
      <p className="text-xs text-slate-600 mt-1">
        Connect data source to display items
      </p>
    </div>
  );
}

/**
 * ExplorerHeader - Alternative standalone header component
 */
export function ExplorerHeader({
  type,
  title,
  actions,
  className,
}: {
  type: ExplorerType;
  title?: string;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-4 px-4 py-3",
        "border-b border-slate-700/50",
        className
      )}
    >
      <div className="flex items-center gap-3">
        <span className="text-slate-400">{typeIcons[type]}</span>
        <h2 className="text-lg font-semibold text-slate-100 display">
          {title || typeTitles[type]}
        </h2>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
