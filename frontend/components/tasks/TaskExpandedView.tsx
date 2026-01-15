"use client";

import { useState, useEffect, useCallback } from "react";
import { motion } from "motion/react";
import { Loader2 } from "lucide-react";
import { ObjectiveSection } from "./ObjectiveSection";
import { SubtasksSection } from "./SubtasksSection";
import { DescriptionSection } from "./DescriptionSection";
import { ActionsSection, type TaskAction } from "./ActionsSection";
import { CriteriaProgress } from "./CriteriaProgress";
import { EnrichmentStatusBadge } from "./EnrichmentStatusBadge";
import {
  getSubtasks,
  updateSubtask,
  updateTask,
  updateTaskStatus,
  type Task,
  type Subtask,
  type TaskStatus,
} from "@/lib/api/tasks";

interface TaskExpandedViewProps {
  projectId: string;
  task: Task;
  onTaskUpdated?: (task: Task) => void;
  onTaskDeleted?: () => void;
}

export function TaskExpandedView({
  projectId,
  task,
  onTaskUpdated,
  onTaskDeleted,
}: TaskExpandedViewProps) {
  const [subtasks, setSubtasks] = useState<Subtask[]>([]);
  const [isLoadingSubtasks, setIsLoadingSubtasks] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Fetch subtasks on mount
  useEffect(() => {
    setIsLoadingSubtasks(true);
    setError(null);

    getSubtasks(projectId, task.id)
      .then((response) => {
        setSubtasks(response.subtasks);
      })
      .catch((err) => {
        console.error("Failed to fetch subtasks:", err);
        setError("Failed to load subtasks");
      })
      .finally(() => {
        setIsLoadingSubtasks(false);
      });
  }, [projectId, task.id]);

  const handleObjectiveEdit = useCallback(
    async (newObjective: string) => {
      try {
        await updateTask(projectId, task.id, {
          title: task.title,
          description: task.description || undefined,
        });
        // Note: objective update would need a separate API endpoint
        // For now, just call onTaskUpdated if provided
        if (onTaskUpdated) {
          onTaskUpdated({ ...task, objective: newObjective });
        }
      } catch (err) {
        console.error("Failed to update objective:", err);
      }
    },
    [projectId, task, onTaskUpdated],
  );

  const handleSubtaskToggle = useCallback(
    async (subtaskId: string, passes: boolean) => {
      try {
        const updated = await updateSubtask(
          projectId,
          task.id,
          subtaskId,
          passes,
        );
        setSubtasks((prev) =>
          prev.map((s) =>
            s.subtask_id === subtaskId ? { ...s, ...updated } : s,
          ),
        );
      } catch (err) {
        console.error("Failed to update subtask:", err);
        throw err; // Re-throw so SubtasksSection can handle loading state
      }
    },
    [projectId, task.id],
  );

  const handleAction = useCallback(
    async (action: TaskAction) => {
      try {
        let newStatus: TaskStatus | undefined;

        switch (action) {
          case "execute":
          case "resume":
            newStatus = "running";
            break;
          case "pause":
            newStatus = "paused";
            break;
          case "complete":
            newStatus = "completed";
            break;
          case "cancel":
            newStatus = "failed";
            break;
          case "delete":
            // Handle delete separately - would need a delete API
            if (onTaskDeleted) {
              onTaskDeleted();
            }
            return;
        }

        if (newStatus) {
          const updated = await updateTaskStatus(projectId, task.id, newStatus);
          if (onTaskUpdated) {
            onTaskUpdated(updated);
          }
        }
      } catch (err) {
        console.error(`Failed to ${action} task:`, err);
      }
    },
    [projectId, task.id, onTaskUpdated, onTaskDeleted],
  );

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.2 }}
      className="bg-slate-900/80 border-t border-slate-800 px-6 py-5 space-y-6"
    >
      {/* Header Row */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        {/* Meta Info */}
        <div className="flex items-center gap-4">
          {/* Enrichment Status */}
          <EnrichmentStatusBadge status={task.enrichment_status} />

          {/* Criteria Progress */}
          {task.acceptance_criteria && task.acceptance_criteria.length > 0 && (
            <div className="flex items-center gap-2">
              <span className="text-2xs text-slate-500 uppercase">
                Criteria
              </span>
              <CriteriaProgress criteria={task.acceptance_criteria} />
            </div>
          )}
        </div>
      </div>

      {/* Objective */}
      <ObjectiveSection
        objective={task.objective}
        onEdit={handleObjectiveEdit}
      />

      {/* Description */}
      <DescriptionSection description={task.description} />

      {/* Subtasks */}
      {isLoadingSubtasks ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="w-5 h-5 animate-spin text-slate-500" />
        </div>
      ) : error ? (
        <div className="p-4 bg-red-950/30 border border-red-800/30 rounded-lg">
          <p className="text-sm text-red-400">{error}</p>
        </div>
      ) : (
        <SubtasksSection
          projectId={projectId}
          taskId={task.id}
          subtasks={subtasks}
          onTogglePass={handleSubtaskToggle}
        />
      )}

      {/* Actions */}
      <div className="pt-4 border-t border-slate-800">
        <ActionsSection task={task} onAction={handleAction} />
      </div>
    </motion.div>
  );
}
