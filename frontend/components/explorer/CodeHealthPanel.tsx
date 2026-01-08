/**
 * CodeHealthPanel - Diagnostic terminal aesthetic for code health monitoring
 *
 * Replaces AnalysisSummary with a full-featured refactoring triage interface.
 * Features:
 * - HealthMetricsBar with triage counts
 * - ComplexityGauge visualization
 * - FilterBar for priority filtering
 * - Sortable RefactorTargetsTable with expandable rows
 */

"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  AlertCircle,
  AlertTriangle,
  Activity,
  FileCode,
  ArrowUpDown,
  ExternalLink,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ScanTrendLine } from "./ScanTrendLine";

// Types
interface RefactorTarget {
  path: string;
  name: string;
  complexity_score: number;
  lines_of_code: number;
  function_count: number;
  class_count: number;
  priority: "high" | "medium" | "none";
  reason: string;
}

interface RefactorTargetsResponse {
  targets: RefactorTarget[];
  summary: {
    high_priority_count: number;
    medium_priority_count: number;
    total_complexity: number;
  };
  warning?: {
    message: string;
    stale_count: number;
  };
}

interface CodeHealthPanelProps {
  projectId: string;
  onFileSelect?: (path: string) => void;
  className?: string;
}

type SortField = "path" | "complexity_score" | "lines_of_code" | "priority";
type SortDir = "asc" | "desc";
type PriorityFilter = "all" | "high" | "medium";

// API fetch function
async function fetchRefactorTargets(
  projectId: string,
  codeOnly: boolean = true
): Promise<RefactorTargetsResponse> {
  const params = new URLSearchParams({ code_only: String(codeOnly) });
  const res = await fetch(
    `/api/projects/${projectId}/explorer/refactor-targets?${params}`
  );
  if (!res.ok) {
    throw new Error("Failed to fetch refactor targets");
  }
  return res.json();
}

export function CodeHealthPanel({
  projectId,
  onFileSelect,
  className,
}: CodeHealthPanelProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const [priorityFilter, setPriorityFilter] = useState<PriorityFilter>("all");
  const [sortField, setSortField] = useState<SortField>("complexity_score");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

  const { data, isLoading, error } = useQuery({
    queryKey: ["refactor-targets", projectId, true],
    queryFn: () => fetchRefactorTargets(projectId, true),
    staleTime: 60000,
    refetchOnWindowFocus: false,
  });

  // Filter and sort targets
  const filteredTargets = useMemo(() => {
    if (!data?.targets) return [];

    let filtered = data.targets;

    // Apply priority filter
    if (priorityFilter !== "all") {
      filtered = filtered.filter((t) => t.priority === priorityFilter);
    }

    // Sort
    filtered = [...filtered].sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case "path":
          cmp = a.path.localeCompare(b.path);
          break;
        case "complexity_score":
          cmp = a.complexity_score - b.complexity_score;
          break;
        case "lines_of_code":
          cmp = a.lines_of_code - b.lines_of_code;
          break;
        case "priority":
          const priorityOrder = { high: 0, medium: 1, none: 2 };
          cmp = priorityOrder[a.priority] - priorityOrder[b.priority];
          break;
      }
      return sortDir === "desc" ? -cmp : cmp;
    });

    return filtered;
  }, [data?.targets, priorityFilter, sortField, sortDir]);

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("desc");
    }
  };

  const toggleRow = (path: string) => {
    const next = new Set(expandedRows);
    if (next.has(path)) {
      next.delete(path);
    } else {
      next.add(path);
    }
    setExpandedRows(next);
  };

  const highCount = data?.summary.high_priority_count ?? 0;
  const mediumCount = data?.summary.medium_priority_count ?? 0;
  const totalComplexity = data?.summary.total_complexity ?? 0;
  const totalTargets = highCount + mediumCount;

  if (error) {
    return (
      <div className={cn("border border-red-500/30 bg-red-950/20 p-4", className)}>
        <div className="flex items-center gap-2 text-red-400 text-sm">
          <AlertCircle className="w-4 h-4" />
          <span>Failed to load code health data</span>
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "border border-slate-700/50 bg-gradient-to-b from-slate-900/80 to-slate-950/90",
        "font-mono text-sm",
        className
      )}
    >
      {/* Header - Diagnostic Terminal Style */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-800/30 transition-colors border-b border-slate-700/30"
      >
        <div className="flex items-center gap-3">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-emerald-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-500" />
          )}
          <Activity className="w-4 h-4 text-emerald-500" />
          <span className="text-emerald-400 font-semibold tracking-wide">
            CODE HEALTH DIAGNOSTIC
          </span>
          {isLoading && (
            <Loader2 className="w-3 h-3 animate-spin text-slate-500 ml-2" />
          )}
        </div>

        {/* Triage counts in header */}
        <div className="flex items-center gap-4 text-xs">
          {highCount > 0 && (
            <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-red-950/50 border border-red-500/30">
              <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
              <span className="text-red-400 font-medium">{highCount} CRITICAL</span>
            </div>
          )}
          {mediumCount > 0 && (
            <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-amber-950/50 border border-amber-500/30">
              <div className="w-2 h-2 rounded-full bg-amber-500" />
              <span className="text-amber-400 font-medium">{mediumCount} WARNING</span>
            </div>
          )}
          {totalTargets === 0 && !isLoading && (
            <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-emerald-950/50 border border-emerald-500/30">
              <div className="w-2 h-2 rounded-full bg-emerald-500" />
              <span className="text-emerald-400 font-medium">ALL CLEAR</span>
            </div>
          )}
        </div>
      </button>

      {isExpanded && (
        <div className="p-4 space-y-4">
          {/* Stale data warning */}
          {data?.warning && (
            <div className="flex items-center gap-2 px-3 py-2 rounded bg-amber-950/30 border border-amber-500/30 text-xs">
              <AlertTriangle className="w-4 h-4 text-amber-500 flex-shrink-0" />
              <span className="text-amber-300">{data.warning.message}</span>
            </div>
          )}

          {/* Metrics Bar */}
          <HealthMetricsBar
            highCount={highCount}
            mediumCount={mediumCount}
            totalComplexity={totalComplexity}
            isLoading={isLoading}
          />

          {/* Scan History Trend */}
          <ScanTrendLine projectId={projectId} />

          {/* Filter Bar */}
          <FilterBar
            activeFilter={priorityFilter}
            onFilterChange={setPriorityFilter}
            highCount={highCount}
            mediumCount={mediumCount}
          />

          {/* Targets Table */}
          {filteredTargets.length > 0 ? (
            <RefactorTargetsTable
              targets={filteredTargets}
              sortField={sortField}
              sortDir={sortDir}
              onSort={toggleSort}
              expandedRows={expandedRows}
              onToggleRow={toggleRow}
              onFileSelect={onFileSelect}
            />
          ) : !isLoading ? (
            <div className="text-center py-8 text-slate-500">
              <FileCode className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p>No refactoring targets match current filters</p>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Sub-components
// ============================================================================

function HealthMetricsBar({
  highCount,
  mediumCount,
  totalComplexity,
  isLoading,
}: {
  highCount: number;
  mediumCount: number;
  totalComplexity: number;
  isLoading: boolean;
}) {
  const total = highCount + mediumCount;

  return (
    <div className="grid grid-cols-3 gap-3">
      {/* Critical metric */}
      <div className="p-3 rounded bg-slate-800/50 border border-slate-700/50">
        <div className="text-xs text-slate-500 mb-1">CRITICAL</div>
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-bold text-red-400 tabular-nums">
            {isLoading ? "-" : highCount}
          </span>
          <span className="text-xs text-slate-500">files</span>
        </div>
        <div className="mt-2 h-1 rounded-full bg-slate-700/50 overflow-hidden">
          <div
            className="h-full bg-red-500 transition-all duration-500"
            style={{ width: total > 0 ? `${(highCount / total) * 100}%` : "0%" }}
          />
        </div>
      </div>

      {/* Warning metric */}
      <div className="p-3 rounded bg-slate-800/50 border border-slate-700/50">
        <div className="text-xs text-slate-500 mb-1">WARNING</div>
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-bold text-amber-400 tabular-nums">
            {isLoading ? "-" : mediumCount}
          </span>
          <span className="text-xs text-slate-500">files</span>
        </div>
        <div className="mt-2 h-1 rounded-full bg-slate-700/50 overflow-hidden">
          <div
            className="h-full bg-amber-500 transition-all duration-500"
            style={{ width: total > 0 ? `${(mediumCount / total) * 100}%` : "0%" }}
          />
        </div>
      </div>

      {/* Complexity Gauge */}
      <div className="p-3 rounded bg-slate-800/50 border border-slate-700/50">
        <div className="text-xs text-slate-500 mb-1">TOTAL COMPLEXITY</div>
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-bold text-emerald-400 tabular-nums">
            {isLoading ? "-" : Math.round(totalComplexity)}
          </span>
          <span className="text-xs text-slate-500">score</span>
        </div>
        <ComplexityGauge value={totalComplexity} max={5000} />
      </div>
    </div>
  );
}

function ComplexityGauge({ value, max }: { value: number; max: number }) {
  const percentage = Math.min((value / max) * 100, 100);
  const color =
    percentage > 75
      ? "bg-red-500"
      : percentage > 50
        ? "bg-amber-500"
        : "bg-emerald-500";

  return (
    <div className="mt-2 h-1 rounded-full bg-slate-700/50 overflow-hidden">
      <div
        className={cn("h-full transition-all duration-500", color)}
        style={{ width: `${percentage}%` }}
      />
    </div>
  );
}

function FilterBar({
  activeFilter,
  onFilterChange,
  highCount,
  mediumCount,
}: {
  activeFilter: PriorityFilter;
  onFilterChange: (filter: PriorityFilter) => void;
  highCount: number;
  mediumCount: number;
}) {
  const filters: { value: PriorityFilter; label: string; count: number }[] = [
    { value: "all", label: "All", count: highCount + mediumCount },
    { value: "high", label: "Critical", count: highCount },
    { value: "medium", label: "Warning", count: mediumCount },
  ];

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-slate-500 mr-2">FILTER:</span>
      {filters.map((f) => (
        <button
          key={f.value}
          onClick={() => onFilterChange(f.value)}
          className={cn(
            "px-3 py-1.5 text-xs rounded border transition-colors",
            activeFilter === f.value
              ? "bg-slate-700 border-slate-600 text-slate-200"
              : "bg-transparent border-slate-700/50 text-slate-500 hover:text-slate-300 hover:border-slate-600"
          )}
        >
          {f.label} ({f.count})
        </button>
      ))}
    </div>
  );
}

function RefactorTargetsTable({
  targets,
  sortField,
  sortDir,
  onSort,
  expandedRows,
  onToggleRow,
  onFileSelect,
}: {
  targets: RefactorTarget[];
  sortField: SortField;
  sortDir: SortDir;
  onSort: (field: SortField) => void;
  expandedRows: Set<string>;
  onToggleRow: (path: string) => void;
  onFileSelect?: (path: string) => void;
}) {
  return (
    <div className="border border-slate-700/50 rounded overflow-hidden">
      {/* Table header */}
      <div className="grid grid-cols-12 gap-2 px-3 py-2 bg-slate-800/80 border-b border-slate-700/50 text-xs text-slate-400">
        <div className="col-span-1" /> {/* Expand toggle */}
        <SortableHeader
          field="path"
          label="FILE"
          currentField={sortField}
          currentDir={sortDir}
          onSort={onSort}
          className="col-span-5"
        />
        <SortableHeader
          field="complexity_score"
          label="COMPLEXITY"
          currentField={sortField}
          currentDir={sortDir}
          onSort={onSort}
          className="col-span-2 justify-end"
        />
        <SortableHeader
          field="lines_of_code"
          label="LOC"
          currentField={sortField}
          currentDir={sortDir}
          onSort={onSort}
          className="col-span-2 justify-end"
        />
        <SortableHeader
          field="priority"
          label="STATUS"
          currentField={sortField}
          currentDir={sortDir}
          onSort={onSort}
          className="col-span-2 justify-center"
        />
      </div>

      {/* Table body */}
      <div className="max-h-[400px] overflow-y-auto">
        {targets.map((target) => (
          <TargetRow
            key={target.path}
            target={target}
            isExpanded={expandedRows.has(target.path)}
            onToggle={() => onToggleRow(target.path)}
            onFileSelect={onFileSelect}
          />
        ))}
      </div>
    </div>
  );
}

function SortableHeader({
  field,
  label,
  currentField,
  currentDir,
  onSort,
  className,
}: {
  field: SortField;
  label: string;
  currentField: SortField;
  currentDir: SortDir;
  onSort: (field: SortField) => void;
  className?: string;
}) {
  const isActive = currentField === field;

  return (
    <button
      onClick={() => onSort(field)}
      className={cn(
        "flex items-center gap-1 hover:text-slate-200 transition-colors",
        isActive && "text-emerald-400",
        className
      )}
    >
      <span>{label}</span>
      <ArrowUpDown
        className={cn(
          "w-3 h-3",
          isActive ? "opacity-100" : "opacity-30",
          isActive && currentDir === "asc" && "rotate-180"
        )}
      />
    </button>
  );
}

function TargetRow({
  target,
  isExpanded,
  onToggle,
  onFileSelect,
}: {
  target: RefactorTarget;
  isExpanded: boolean;
  onToggle: () => void;
  onFileSelect?: (path: string) => void;
}) {
  const priorityStyles = {
    high: {
      bg: "bg-red-950/30",
      border: "border-red-500/30",
      text: "text-red-400",
      badge: "bg-red-500",
      label: "CRITICAL",
    },
    medium: {
      bg: "bg-amber-950/30",
      border: "border-amber-500/30",
      text: "text-amber-400",
      badge: "bg-amber-500",
      label: "WARNING",
    },
    none: {
      bg: "bg-slate-800/30",
      border: "border-slate-700/30",
      text: "text-slate-400",
      badge: "bg-slate-500",
      label: "OK",
    },
  };

  const style = priorityStyles[target.priority];

  return (
    <div className={cn("border-b border-slate-700/30", style.bg)}>
      {/* Main row */}
      <div
        className="grid grid-cols-12 gap-2 px-3 py-2 items-center cursor-pointer hover:bg-slate-700/20 transition-colors"
        onClick={onToggle}
      >
        <div className="col-span-1">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-slate-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-500" />
          )}
        </div>
        <div className="col-span-5 truncate text-slate-300" title={target.path}>
          <span className="text-slate-500">{target.path.split("/").slice(0, -1).join("/")}/</span>
          <span className="font-medium">{target.name}</span>
        </div>
        <div className={cn("col-span-2 text-right tabular-nums", style.text)}>
          {target.complexity_score.toFixed(1)}
        </div>
        <div className="col-span-2 text-right tabular-nums text-slate-400">
          {target.lines_of_code.toLocaleString()}
        </div>
        <div className="col-span-2 flex justify-center">
          <span
            className={cn(
              "px-2 py-0.5 text-xs rounded text-white font-medium",
              style.badge
            )}
          >
            {style.label}
          </span>
        </div>
      </div>

      {/* Expanded details */}
      {isExpanded && (
        <div className={cn("px-3 py-3 border-t", style.border, "bg-slate-900/50")}>
          <div className="grid grid-cols-2 gap-4 text-xs">
            <div className="space-y-2">
              <div>
                <span className="text-slate-500">Full Path:</span>
                <span className="ml-2 text-slate-300 font-mono">{target.path}</span>
              </div>
              <div>
                <span className="text-slate-500">Reason:</span>
                <span className={cn("ml-2", style.text)}>{target.reason}</span>
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex gap-4">
                <span>
                  <span className="text-slate-500">Functions:</span>
                  <span className="ml-2 text-slate-300">{target.function_count}</span>
                </span>
                <span>
                  <span className="text-slate-500">Classes:</span>
                  <span className="ml-2 text-slate-300">{target.class_count}</span>
                </span>
              </div>
              {onFileSelect && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onFileSelect(target.path);
                  }}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10 transition-colors"
                >
                  <ExternalLink className="w-3 h-3" />
                  View in Explorer
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
