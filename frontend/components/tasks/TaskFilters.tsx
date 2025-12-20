"use client";

import { useQuery } from "@tanstack/react-query";
import { Filter } from "lucide-react";
import { fetchFeatures, type TaskType, type TaskStatus, type Feature } from "@/lib/api";
import { cn } from "@/lib/utils";

export interface TaskFilterValues {
  type: TaskType | "all";
  status: TaskStatus | "all" | "active";
  priority: number | "all";
  featureId: number | "all";
  standaloneOnly: boolean;
}

interface TaskFiltersProps {
  projectId: string;
  filters: TaskFilterValues;
  onChange: (filters: TaskFilterValues) => void;
  className?: string;
}

const STATUS_OPTIONS = [
  { value: "all", label: "All Status" },
  { value: "active", label: "Active" },
  { value: "pending", label: "Pending" },
  { value: "running", label: "Running" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
];

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

export function TaskFilters({ projectId, filters, onChange, className }: TaskFiltersProps) {
  // Fetch features for the feature filter dropdown
  const { data: featuresData } = useQuery({
    queryKey: ["features", projectId],
    queryFn: () => fetchFeatures(projectId, { limit: 100 }),
    staleTime: 60000, // 1 minute
  });

  const features = featuresData?.features || [];

  const handleChange = (key: keyof TaskFilterValues, value: string | number | boolean) => {
    onChange({ ...filters, [key]: value });
  };

  return (
    <div className={cn("flex flex-wrap items-center gap-2", className)}>
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

      {/* Status Filter */}
      <select
        value={filters.status}
        onChange={(e) => handleChange("status", e.target.value)}
        className="px-2 py-1.5 text-xs bg-slate-800 border border-slate-700 rounded text-white"
      >
        {STATUS_OPTIONS.map((opt) => (
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

      {/* Standalone Only Checkbox */}
      <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer">
        <input
          type="checkbox"
          checked={filters.standaloneOnly}
          onChange={(e) => handleChange("standaloneOnly", e.target.checked)}
          className="rounded border-slate-600 bg-slate-800 text-blue-500 focus:ring-blue-500 focus:ring-offset-0"
        />
        <span>Standalone only</span>
      </label>
    </div>
  );
}

export const DEFAULT_FILTERS: TaskFilterValues = {
  type: "all",
  status: "all",
  priority: "all",
  featureId: "all",
  standaloneOnly: false,
};
