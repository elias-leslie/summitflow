"use client";

import { useState, useMemo } from "react";
import {
  DndContext,
  DragOverlay,
  closestCorners,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragStartEvent,
  type DragEndEvent,
  type DragOverEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical } from "lucide-react";

import type { Feature } from "@/lib/api";

// ============================================================================
// Types
// ============================================================================

export type KanbanStatus = "backlog" | "in_progress" | "review" | "done";

export interface KanbanColumn {
  id: KanbanStatus;
  title: string;
  color: string;
}

interface KanbanBoardProps {
  features: Feature[];
  onStatusChange?: (featureId: string, newStatus: KanbanStatus) => void;
  onFeatureClick?: (feature: Feature) => void;
}

// ============================================================================
// Column Configuration
// ============================================================================

const COLUMNS: KanbanColumn[] = [
  { id: "backlog", title: "Backlog", color: "slate" },
  { id: "in_progress", title: "In Progress", color: "blue" },
  { id: "review", title: "Review", color: "amber" },
  { id: "done", title: "Done", color: "phosphor" },
];

// ============================================================================
// Sortable Feature Card
// ============================================================================

interface SortableFeatureCardProps {
  feature: Feature;
  onClick?: () => void;
}

function SortableFeatureCard({ feature, onClick }: SortableFeatureCardProps) {
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

  const criteria = feature.acceptance_criteria ?? [];
  const passedCount = criteria.filter((c) => c.passed).length;
  const totalCount = criteria.length;
  const progressPct = totalCount > 0 ? (passedCount / totalCount) * 100 : 0;

  const priorityColors: Record<number, string> = {
    1: "bg-rose-500/20 text-rose-400 border-rose-500/30",
    2: "bg-orange-500/20 text-orange-400 border-orange-500/30",
    3: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    4: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    5: "bg-slate-500/20 text-slate-400 border-slate-500/30",
  };
  const priority = feature.priority ?? feature.effective_priority ?? 3;

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
        className="absolute left-1 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity cursor-grab active:cursor-grabbing"
        onClick={(e) => e.stopPropagation()}
      >
        <GripVertical className="h-4 w-4 text-slate-500" />
      </div>

      {/* Card Content */}
      <div className="pl-4">
        {/* Header: ID + Priority */}
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs mono text-slate-500">{feature.feature_id}</span>
          <span
            className={`text-xs px-1.5 py-0.5 rounded border mono font-medium ${priorityColors[priority] || priorityColors[5]}`}
          >
            P{priority}
          </span>
        </div>

        {/* Title */}
        <h4 className="text-sm font-medium text-white leading-tight mb-2 line-clamp-2">
          {feature.name}
        </h4>

        {/* Criteria Progress */}
        {totalCount > 0 && (
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-500">Criteria</span>
              <span className="text-xs mono text-slate-400">
                {passedCount}/{totalCount}
              </span>
            </div>
            <div className="h-1 w-full bg-slate-700 rounded-full overflow-hidden">
              <div
                className={`h-full transition-all ${progressPct === 100 ? "bg-phosphor-500" : "bg-blue-500"}`}
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Droppable Column
// ============================================================================

interface DroppableColumnProps {
  column: KanbanColumn;
  features: Feature[];
  onFeatureClick?: (feature: Feature) => void;
}

function DroppableColumn({ column, features, onFeatureClick }: DroppableColumnProps) {
  const colorClasses: Record<string, { header: string; border: string }> = {
    slate: { header: "text-slate-400", border: "border-slate-700" },
    blue: { header: "text-blue-400", border: "border-blue-700/50" },
    amber: { header: "text-amber-400", border: "border-amber-700/50" },
    phosphor: { header: "text-phosphor-400", border: "border-phosphor-700/50" },
  };

  const colors = colorClasses[column.color] || colorClasses.slate;

  return (
    <div className={`flex-1 min-w-[280px] max-w-[360px] flex flex-col rounded-lg border ${colors.border} bg-slate-900/30`}>
      {/* Column Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <h3 className={`text-sm font-medium ${colors.header}`}>{column.title}</h3>
        <span className="text-xs mono text-slate-500 bg-slate-800 px-2 py-0.5 rounded">
          {features.length}
        </span>
      </div>

      {/* Column Content */}
      <div className="flex-1 p-2 overflow-y-auto min-h-[200px]">
        <SortableContext
          items={features.map((f) => f.feature_id)}
          strategy={verticalListSortingStrategy}
        >
          <div className="space-y-2">
            {features.length > 0 ? (
              features.map((feature) => (
                <SortableFeatureCard
                  key={feature.feature_id}
                  feature={feature}
                  onClick={() => onFeatureClick?.(feature)}
                />
              ))
            ) : (
              <div className="flex items-center justify-center h-24 text-xs text-slate-600 italic">
                No features
              </div>
            )}
          </div>
        </SortableContext>
      </div>
    </div>
  );
}

// ============================================================================
// Kanban Board
// ============================================================================

export function KanbanBoard({
  features,
  onStatusChange,
  onFeatureClick,
}: KanbanBoardProps) {
  const [activeId, setActiveId] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  // Group features by status
  const featuresByStatus = useMemo(() => {
    const grouped: Record<KanbanStatus, Feature[]> = {
      backlog: [],
      in_progress: [],
      review: [],
      done: [],
    };

    for (const feature of features) {
      // Use health_status or default to backlog
      // The actual status field should be mapped from the backend
      const status = (feature as Feature & { status?: string }).status as KanbanStatus | undefined;
      const column = status && status in grouped ? status : "backlog";
      grouped[column].push(feature);
    }

    return grouped;
  }, [features]);

  const activeFeature = useMemo(() => {
    if (!activeId) return null;
    return features.find((f) => f.feature_id === activeId) ?? null;
  }, [activeId, features]);

  // Find which column contains a feature
  const findColumn = (featureId: string): KanbanStatus | null => {
    for (const [status, feats] of Object.entries(featuresByStatus)) {
      if (feats.some((f) => f.feature_id === featureId)) {
        return status as KanbanStatus;
      }
    }
    return null;
  };

  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(event.active.id as string);
  };

  const handleDragOver = (event: DragOverEvent) => {
    // Handle drag over logic if needed
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;

    if (!over) {
      setActiveId(null);
      return;
    }

    const activeFeatureId = active.id as string;
    const overId = over.id as string;

    // Find current and target columns
    const fromColumn = findColumn(activeFeatureId);

    // Determine target column - could be a column ID or another feature ID
    let toColumn: KanbanStatus | null = null;

    // Check if dropping on a column
    if (COLUMNS.some((c) => c.id === overId)) {
      toColumn = overId as KanbanStatus;
    } else {
      // Dropping on another feature - find its column
      toColumn = findColumn(overId);
    }

    if (fromColumn && toColumn && fromColumn !== toColumn) {
      onStatusChange?.(activeFeatureId, toColumn);
    }

    setActiveId(null);
  };

  const handleDragCancel = () => {
    setActiveId(null);
  };

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCorners}
      onDragStart={handleDragStart}
      onDragOver={handleDragOver}
      onDragEnd={handleDragEnd}
      onDragCancel={handleDragCancel}
    >
      <div className="flex gap-4 overflow-x-auto pb-4">
        {COLUMNS.map((column) => (
          <DroppableColumn
            key={column.id}
            column={column}
            features={featuresByStatus[column.id]}
            onFeatureClick={onFeatureClick}
          />
        ))}
      </div>

      {/* Drag Overlay */}
      <DragOverlay>
        {activeFeature && (
          <div className="rounded-lg border border-phosphor-500 bg-slate-900 p-3 shadow-xl shadow-phosphor-500/20 rotate-2">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs mono text-slate-500">{activeFeature.feature_id}</span>
            </div>
            <h4 className="text-sm font-medium text-white line-clamp-2">
              {activeFeature.name}
            </h4>
          </div>
        )}
      </DragOverlay>
    </DndContext>
  );
}
