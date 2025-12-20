"use client";

import { useQuery } from "@tanstack/react-query";
import { Filter, Plus } from "lucide-react";
import { fetchFeatures, type TaskType, type Feature } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface KanbanFilterValues {
  type: TaskType | "all";
  priority: number | "all";
  featureId: number | "all";
}

interface KanbanFiltersProps {
  projectId: string;
  filters: KanbanFilterValues;
  onChange: (filters: KanbanFilterValues) => void;
  onNewTask?: () => void;
  className?: string;
}

const TYPE_OPTIONS = [
  { value: "all", label: "All Types" },
  { value: "feature", label: "Features" },
  { value: "bug", label: "Bugs" },
  { value: "task", label: "Tasks" },
];

const PRIORITY_OPTIONS = [
  { value: "all", label: "All Priority" },
  { value: 0, label: "P0 - Critical" },
  { value: 1, label: "P1 - High" },
  { value: 2, label: "P2 - Medium" },
  { value: 3, label: "P3 - Low" },
  { value: 4, label: "P4 - Backlog" },
];

export function KanbanFilters({
  projectId,
  filters,
  onChange,
  onNewTask,
  className,
}: KanbanFiltersProps) {
  // Fetch features for the feature filter dropdown
  const { data: featuresData } = useQuery({
    queryKey: ["features", projectId],
    queryFn: () => fetchFeatures(projectId, { limit: 100 }),
    staleTime: 60000, // 1 minute
  });

  const features = featuresData?.features || [];

  const handleChange = (key: keyof KanbanFilterValues, value: string | number) => {
    onChange({ ...filters, [key]: value });
  };

  return (
    <div className={cn("flex flex-wrap items-center justify-between gap-4", className)}>
      <div className="flex flex-wrap items-center gap-2">
        <Filter className="w-4 h-4 text-slate-500" />

        {/* Type Filter */}
        <select
          value={filters.type}
          onChange={(e) => handleChange("type", e.target.value)}
          className="px-2 py-1.5 text-xs bg-slate-800 border border-slate-700 rounded text-white"
        >
          {TYPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        {/* Priority Filter */}
        <select
          value={filters.priority}
          onChange={(e) => {
            const val = e.target.value;
            handleChange("priority", val === "all" ? "all" : parseInt(val, 10));
          }}
          className="px-2 py-1.5 text-xs bg-slate-800 border border-slate-700 rounded text-white"
        >
          {PRIORITY_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        {/* Feature Filter */}
        <select
          value={filters.featureId}
          onChange={(e) => {
            const val = e.target.value;
            handleChange("featureId", val === "all" ? "all" : parseInt(val, 10));
          }}
          className="px-2 py-1.5 text-xs bg-slate-800 border border-slate-700 rounded text-white"
        >
          <option value="all">All Features</option>
          {features
            .filter((f: Feature) => f.id !== null)
            .map((f: Feature) => (
              <option key={f.id} value={f.id!}>
                {f.feature_id} - {f.name}
              </option>
            ))}
        </select>
      </div>

      {/* New Task Button */}
      {onNewTask && (
        <Button
          size="sm"
          onClick={onNewTask}
          className="bg-phosphor-500 hover:bg-phosphor-600 text-white"
        >
          <Plus className="w-4 h-4 mr-1" />
          New Task
        </Button>
      )}
    </div>
  );
}

export const DEFAULT_KANBAN_FILTERS: KanbanFilterValues = {
  type: "all",
  priority: "all",
  featureId: "all",
};
