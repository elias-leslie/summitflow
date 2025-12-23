"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  Target,
  Layers,
  Loader2,
  AlertCircle,
  CheckCircle2,
  ArrowRight,
} from "lucide-react";

import { fetchVisionGoals, type VisionGoal } from "@/lib/api";

// ============================================================================
// Types
// ============================================================================

interface GoalsListProps {
  projectId: string;
}

// ============================================================================
// Category Config
// ============================================================================

const categoryConfig: Record<string, { color: string; bg: string; border: string }> = {
  core: {
    color: "text-blue-400",
    bg: "bg-blue-500/10",
    border: "border-blue-500/30",
  },
  automation: {
    color: "text-purple-400",
    bg: "bg-purple-500/10",
    border: "border-purple-500/30",
  },
  agents: {
    color: "text-amber-400",
    bg: "bg-amber-500/10",
    border: "border-amber-500/30",
  },
  quality: {
    color: "text-green-400",
    bg: "bg-green-500/10",
    border: "border-green-500/30",
  },
  intelligence: {
    color: "text-cyan-400",
    bg: "bg-cyan-500/10",
    border: "border-cyan-500/30",
  },
  reliability: {
    color: "text-rose-400",
    bg: "bg-rose-500/10",
    border: "border-rose-500/30",
  },
  experience: {
    color: "text-pink-400",
    bg: "bg-pink-500/10",
    border: "border-pink-500/30",
  },
  default: {
    color: "text-slate-400",
    bg: "bg-slate-500/10",
    border: "border-slate-500/30",
  },
};

function getCategoryStyle(category: string | null) {
  if (!category) return categoryConfig.default;
  return categoryConfig[category.toLowerCase()] || categoryConfig.default;
}

// ============================================================================
// Goal Card
// ============================================================================

interface GoalCardProps {
  goal: VisionGoal;
  onClick: () => void;
}

function GoalCard({ goal, onClick }: GoalCardProps) {
  const categoryStyle = getCategoryStyle(goal.category);
  const hasFeatures = goal.feature_count > 0;
  const passRate = goal.criteria_total > 0 ? Math.round(goal.pass_rate * 100) : null;

  return (
    <button
      onClick={onClick}
      className={`
        w-full text-left p-4 rounded-lg border transition-all
        hover:scale-[1.02] hover:shadow-lg
        ${categoryStyle.bg} ${categoryStyle.border}
        focus:outline-none focus:ring-2 focus:ring-blue-500/50
      `}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <Target className={`h-4 w-4 ${categoryStyle.color}`} />
          <span className={`text-xs font-mono font-medium ${categoryStyle.color}`}>
            {goal.code}
          </span>
        </div>
        {goal.category && (
          <span className={`text-xs px-2 py-0.5 rounded ${categoryStyle.bg} ${categoryStyle.color}`}>
            {goal.category}
          </span>
        )}
      </div>

      {/* Name */}
      <h3 className="text-sm font-medium text-slate-200 mb-1 line-clamp-1">
        {goal.name}
      </h3>

      {/* Description */}
      {goal.description && (
        <p className="text-xs text-slate-400 line-clamp-2 mb-3">
          {goal.description}
        </p>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {/* Feature count */}
          <div className="flex items-center gap-1">
            <Layers className="h-3.5 w-3.5 text-slate-500" />
            <span className={`text-xs ${hasFeatures ? "text-slate-300" : "text-slate-500"}`}>
              {goal.feature_count} feature{goal.feature_count !== 1 ? "s" : ""}
            </span>
          </div>

          {/* Pass rate */}
          {passRate !== null && (
            <div className="flex items-center gap-1">
              <CheckCircle2 className={`h-3.5 w-3.5 ${passRate === 100 ? "text-green-400" : "text-slate-500"}`} />
              <span className={`text-xs ${passRate === 100 ? "text-green-400" : "text-slate-400"}`}>
                {passRate}%
              </span>
            </div>
          )}
        </div>

        {/* Arrow */}
        {hasFeatures && (
          <ArrowRight className="h-4 w-4 text-slate-500" />
        )}
      </div>
    </button>
  );
}

// ============================================================================
// Goals List Component
// ============================================================================

export function GoalsList({ projectId }: GoalsListProps) {
  const router = useRouter();

  const { data: goals, error, isLoading } = useQuery<VisionGoal[]>({
    queryKey: ["vision-goals", projectId],
    queryFn: () => fetchVisionGoals(projectId),
    enabled: !!projectId,
    staleTime: 1000 * 60 * 5, // 5 minutes
  });

  const handleGoalClick = (goalCode: string) => {
    // Navigate to Kanban with goal filter
    router.push(`/projects/${projectId}/kanban?goal=${goalCode}`);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-rose-400">
        <AlertCircle className="h-5 w-5" />
        <span>Failed to load goals</span>
      </div>
    );
  }

  if (!goals || goals.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-slate-500">
        <Target className="h-8 w-8 mb-2" />
        <span className="text-sm">No vision goals defined</span>
        <span className="text-xs text-slate-600">Define goals to track project vision</span>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-medium text-slate-200">Vision Goals</h2>
          <p className="text-xs text-slate-500">
            {goals.length} goal{goals.length !== 1 ? "s" : ""} defined
          </p>
        </div>
      </div>

      {/* Goals Grid */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {goals.map((goal) => (
          <GoalCard
            key={goal.code}
            goal={goal}
            onClick={() => handleGoalClick(goal.code)}
          />
        ))}
      </div>

      {/* Summary */}
      <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
        <div className="grid grid-cols-3 gap-4 text-center">
          <div>
            <div className="text-lg font-semibold text-slate-200">
              {goals.reduce((sum, g) => sum + g.feature_count, 0)}
            </div>
            <div className="text-xs text-slate-500">Total Features</div>
          </div>
          <div>
            <div className="text-lg font-semibold text-slate-200">
              {goals.reduce((sum, g) => sum + g.criteria_passed, 0)}
            </div>
            <div className="text-xs text-slate-500">Criteria Passed</div>
          </div>
          <div>
            <div className="text-lg font-semibold text-slate-200">
              {goals.reduce((sum, g) => sum + g.criteria_total, 0)}
            </div>
            <div className="text-xs text-slate-500">Total Criteria</div>
          </div>
        </div>
      </div>
    </div>
  );
}
