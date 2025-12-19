"use client";

import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical, Play } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { Feature } from "@/lib/api";

// ============================================================================
// Types
// ============================================================================

interface FeatureCardProps {
  feature: Feature;
  onClick?: () => void;
  onStartClick?: (feature: Feature) => void;
}

// ============================================================================
// Priority Colors
// ============================================================================

const priorityColors: Record<number, string> = {
  1: "bg-rose-500/20 text-rose-400 border-rose-500/30",
  2: "bg-orange-500/20 text-orange-400 border-orange-500/30",
  3: "bg-amber-500/20 text-amber-400 border-amber-500/30",
  4: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  5: "bg-slate-500/20 text-slate-400 border-slate-500/30",
};

// ============================================================================
// Feature Card Component
// ============================================================================

export function FeatureCard({ feature, onClick, onStartClick }: FeatureCardProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: feature.feature_id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  // Calculate criteria progress
  const criteria = feature.acceptance_criteria ?? [];
  const passedCount = criteria.filter((c) => c.passed).length;
  const totalCount = criteria.length;
  const progressPct = totalCount > 0 ? (passedCount / totalCount) * 100 : 0;
  const allPassed = totalCount > 0 && passedCount === totalCount;

  // Priority
  const priority = feature.priority ?? feature.effective_priority ?? 3;

  const handleStartClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onStartClick?.(feature);
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="group relative rounded-lg border border-slate-700 bg-slate-900/80 p-3 shadow-sm hover:border-slate-600 hover:bg-slate-850 transition-colors cursor-pointer"
      onClick={onClick}
    >
      {/* Drag Handle */}
      <div
        {...attributes}
        {...listeners}
        className="absolute left-1 top-3 opacity-0 group-hover:opacity-100 transition-opacity cursor-grab active:cursor-grabbing"
        onClick={(e) => e.stopPropagation()}
      >
        <GripVertical className="h-4 w-4 text-slate-500" />
      </div>

      {/* Card Content */}
      <div className="pl-4">
        {/* Header: ID + Priority */}
        <div className="flex items-center justify-between gap-2 mb-1">
          <div className="flex items-center gap-2">
            <span className="text-xs mono text-slate-500">{feature.feature_id}</span>
            <span
              className={`text-xs px-1.5 py-0.5 rounded border mono font-medium ${priorityColors[priority] || priorityColors[5]}`}
            >
              P{priority}
            </span>
          </div>

          {/* Start Button - always visible */}
          <Button
            size="sm"
            variant="ghost"
            className="h-6 w-6 p-0 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-phosphor-500/20 hover:text-phosphor-400"
            onClick={handleStartClick}
            title="Start working on this feature"
          >
            <Play className="h-3.5 w-3.5" />
          </Button>
        </div>

        {/* Title */}
        <h4 className="text-sm font-medium text-white leading-tight mb-2 line-clamp-2 pr-6">
          {feature.name}
        </h4>

        {/* Criteria Progress */}
        {totalCount > 0 ? (
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-500">Criteria</span>
              <span className={`text-xs mono font-medium ${allPassed ? "text-phosphor-400" : "text-slate-400"}`}>
                {passedCount}/{totalCount}
              </span>
            </div>
            <div className="h-1.5 w-full bg-slate-700 rounded-full overflow-hidden">
              <div
                className={`h-full transition-all duration-300 ${allPassed ? "bg-phosphor-500" : "bg-blue-500"}`}
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
        ) : (
          <div className="text-xs text-slate-600 italic">No criteria defined</div>
        )}

        {/* Category tag if present */}
        {feature.category && (
          <div className="mt-2">
            <span className="text-xs px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-400 border border-slate-600">
              {feature.category}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Drag Overlay Card (for visual feedback during drag)
// ============================================================================

interface DragOverlayCardProps {
  feature: Feature;
}

export function DragOverlayCard({ feature }: DragOverlayCardProps) {
  const priority = feature.priority ?? feature.effective_priority ?? 3;

  return (
    <div className="rounded-lg border border-phosphor-500 bg-slate-900 p-3 shadow-xl shadow-phosphor-500/20 rotate-2 max-w-[300px]">
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs mono text-slate-500">{feature.feature_id}</span>
        <span
          className={`text-xs px-1.5 py-0.5 rounded border mono font-medium ${priorityColors[priority] || priorityColors[5]}`}
        >
          P{priority}
        </span>
      </div>
      <h4 className="text-sm font-medium text-white line-clamp-2">
        {feature.name}
      </h4>
    </div>
  );
}
