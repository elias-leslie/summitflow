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
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";

import type { Feature } from "@/lib/api";
import { FeatureCard, DragOverlayCard } from "./FeatureCard";

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
  onStartClick?: (feature: Feature) => void;
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
// Droppable Column
// ============================================================================

interface DroppableColumnProps {
  column: KanbanColumn;
  features: Feature[];
  onFeatureClick?: (feature: Feature) => void;
  onStartClick?: (feature: Feature) => void;
}

function DroppableColumn({ column, features, onFeatureClick, onStartClick }: DroppableColumnProps) {
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
                <FeatureCard
                  key={feature.feature_id}
                  feature={feature}
                  onClick={() => onFeatureClick?.(feature)}
                  onStartClick={onStartClick}
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
  onStartClick,
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
      // Use status field from backend, default to backlog
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

  const handleDragOver = (_event: DragOverEvent) => {
    // Handle drag over logic if needed for visual feedback
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
            onStartClick={onStartClick}
          />
        ))}
      </div>

      {/* Drag Overlay */}
      <DragOverlay>
        {activeFeature && <DragOverlayCard feature={activeFeature} />}
      </DragOverlay>
    </DndContext>
  );
}
