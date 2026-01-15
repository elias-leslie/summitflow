"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  Circle,
  FileCode,
  Loader2,
  Square,
  CheckSquare,
  Copy,
  Check,
} from "lucide-react";
import type { Subtask, Step } from "@/lib/api/tasks";
import { getSteps, updateStep } from "@/lib/api/tasks";
import { PHASE_CONFIG } from "@/lib/utils/task-status";

interface SubtasksSectionProps {
  projectId: string;
  taskId: string;
  subtasks: Subtask[];
  onTogglePass: (subtaskId: string, passes: boolean) => Promise<void>;
  isLoading?: boolean;
}

function groupByPhase(subtasks: Subtask[]): Record<string, Subtask[]> {
  return subtasks.reduce(
    (acc, subtask) => {
      const phase = subtask.phase || "other";
      if (!acc[phase]) acc[phase] = [];
      acc[phase].push(subtask);
      return acc;
    },
    {} as Record<string, Subtask[]>,
  );
}

interface StepItemProps {
  step: Step;
  index: number;
  isOptimisticallyUpdated: boolean;
  onToggle: (stepNumber: number, passes: boolean) => void;
  isUpdating: boolean;
}

function StepItem({
  step,
  index,
  isOptimisticallyUpdated,
  onToggle,
  isUpdating,
}: StepItemProps) {
  const [isSpecExpanded, setIsSpecExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const passes = isOptimisticallyUpdated ? !step.passes : step.passes;
  const hasSpec = step.spec && Object.keys(step.spec).length > 0;

  const handleCopy = useCallback(async () => {
    if (!step.spec) return;
    await navigator.clipboard.writeText(JSON.stringify(step.spec, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [step.spec]);

  return (
    <motion.li
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: index * 0.03 }}
      className="group"
    >
      <div className="flex items-start gap-2.5">
        <button
          onClick={() => onToggle(step.step_number, !passes)}
          disabled={isUpdating}
          className="mt-0.5 flex-shrink-0 focus:outline-none focus:ring-1 focus:ring-blue-500/50 rounded"
          aria-label={passes ? "Mark step incomplete" : "Mark step complete"}
        >
          {isUpdating ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-500" />
          ) : passes ? (
            <motion.div
              initial={{ scale: 0.8 }}
              animate={{ scale: 1 }}
              transition={{ type: "spring", stiffness: 400, damping: 15 }}
            >
              <CheckSquare className="w-3.5 h-3.5 text-phosphor-400" />
            </motion.div>
          ) : (
            <Square className="w-3.5 h-3.5 text-slate-600 group-hover:text-slate-400 transition-colors" />
          )}
        </button>
        <div className="flex-1 min-w-0">
          <div className="flex items-start gap-2">
            <span className="text-slate-600 text-2xs font-mono flex-shrink-0 w-4 text-right">
              {step.step_number}.
            </span>
            <span
              className={`text-xs transition-all duration-200 ${
                passes
                  ? "text-slate-600 line-through decoration-slate-700"
                  : "text-slate-400"
              }`}
            >
              {step.description}
            </span>
            {hasSpec && (
              <button
                onClick={() => setIsSpecExpanded(!isSpecExpanded)}
                className="flex-shrink-0 p-0.5 rounded hover:bg-slate-800 transition-colors"
                aria-label={isSpecExpanded ? "Hide spec" : "Show spec"}
              >
                {isSpecExpanded ? (
                  <ChevronDown className="w-3 h-3 text-blue-400" />
                ) : (
                  <ChevronRight className="w-3 h-3 text-slate-500 hover:text-blue-400" />
                )}
              </button>
            )}
          </div>
          <AnimatePresence>
            {isSpecExpanded && hasSpec && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="overflow-hidden"
              >
                <div className="mt-2 ml-6 relative">
                  <button
                    onClick={handleCopy}
                    className="absolute top-1 right-1 p-1 rounded bg-slate-800 hover:bg-slate-700 transition-colors"
                    aria-label="Copy spec"
                  >
                    {copied ? (
                      <Check className="w-3 h-3 text-phosphor-400" />
                    ) : (
                      <Copy className="w-3 h-3 text-slate-500" />
                    )}
                  </button>
                  <pre className="text-2xs bg-slate-800/50 border border-slate-700 rounded p-2 pr-8 overflow-x-auto text-slate-400 font-mono">
                    {JSON.stringify(step.spec, null, 2)}
                  </pre>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </motion.li>
  );
}

interface StepsListProps {
  projectId: string;
  taskId: string;
  subtask: Subtask;
}

function StepsList({ projectId, taskId, subtask }: StepsListProps) {
  const [steps, setSteps] = useState<Step[]>(subtask.steps_from_table || []);
  const [isLoading, setIsLoading] = useState(!subtask.steps_from_table?.length);
  const [updatingSteps, setUpdatingSteps] = useState<Set<number>>(new Set());
  const [optimisticUpdates, setOptimisticUpdates] = useState<Set<number>>(
    new Set(),
  );

  // Fetch steps if not already loaded
  const fetchStepsIfNeeded = useCallback(async () => {
    if (subtask.steps_from_table?.length) {
      setSteps(subtask.steps_from_table);
      setIsLoading(false);
      return;
    }

    // If no table steps, check if we have legacy steps
    if (!subtask.steps?.length) {
      setIsLoading(false);
      return;
    }

    try {
      setIsLoading(true);
      const fetchedSteps = await getSteps(
        projectId,
        taskId,
        subtask.subtask_id,
      );
      setSteps(fetchedSteps);
    } catch (error) {
      console.error("Failed to fetch steps:", error);
      // Fallback: convert legacy steps to display format
      setSteps([]);
    } finally {
      setIsLoading(false);
    }
  }, [projectId, taskId, subtask]);

  // Fetch on mount
  useEffect(() => {
    fetchStepsIfNeeded();
  }, [fetchStepsIfNeeded]);

  const handleToggleStep = useCallback(
    async (stepNumber: number, passes: boolean) => {
      // Optimistic update
      setOptimisticUpdates((prev) => new Set(prev).add(stepNumber));
      setUpdatingSteps((prev) => new Set(prev).add(stepNumber));

      try {
        const updated = await updateStep(
          projectId,
          taskId,
          subtask.subtask_id,
          stepNumber,
          passes,
        );
        // Update local state with server response
        setSteps((prev) =>
          prev.map((s) => (s.step_number === stepNumber ? updated : s)),
        );
        // Clear optimistic update on success
        setOptimisticUpdates((prev) => {
          const next = new Set(prev);
          next.delete(stepNumber);
          return next;
        });
      } catch (error) {
        console.error("Failed to update step:", error);
        // Revert optimistic update on failure
        setOptimisticUpdates((prev) => {
          const next = new Set(prev);
          next.delete(stepNumber);
          return next;
        });
      } finally {
        setUpdatingSteps((prev) => {
          const next = new Set(prev);
          next.delete(stepNumber);
          return next;
        });
      }
    },
    [projectId, taskId, subtask.subtask_id],
  );

  // Calculate completion with optimistic updates
  const completedCount = useMemo(() => {
    return steps.filter((s) => {
      const isOptimistic = optimisticUpdates.has(s.step_number);
      return isOptimistic ? !s.passes : s.passes;
    }).length;
  }, [steps, optimisticUpdates]);

  // If no steps in table, show legacy steps as read-only
  if (steps.length === 0 && subtask.steps?.length) {
    return (
      <ul className="pl-11 pr-4 pb-3 space-y-1.5">
        {subtask.steps.map((stepText, idx) => (
          <li
            key={idx}
            className="text-xs text-slate-500 flex items-start gap-2"
          >
            <span className="text-slate-700 font-mono text-2xs w-4 text-right flex-shrink-0">
              {idx + 1}.
            </span>
            <span>{stepText}</span>
          </li>
        ))}
      </ul>
    );
  }

  if (isLoading) {
    return (
      <div className="pl-11 pr-4 pb-3 flex items-center gap-2">
        <Loader2 className="w-3 h-3 animate-spin text-slate-600" />
        <span className="text-2xs text-slate-600">Loading steps...</span>
      </div>
    );
  }

  if (steps.length === 0) {
    return (
      <div className="pl-11 pr-4 pb-3">
        <span className="text-2xs text-slate-600">No steps defined</span>
      </div>
    );
  }

  return (
    <div className="pl-11 pr-4 pb-3">
      {/* Step progress indicator */}
      <div className="flex items-center gap-2 mb-2">
        <div className="flex-1 h-0.5 bg-slate-800 rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-gradient-to-r from-phosphor-500/60 to-phosphor-400"
            initial={{ width: 0 }}
            animate={{ width: `${(completedCount / steps.length) * 100}%` }}
            transition={{ duration: 0.3, ease: "easeOut" }}
          />
        </div>
        <span className="text-2xs font-mono text-slate-500 tabular-nums">
          {completedCount}/{steps.length}
        </span>
      </div>

      {/* Steps list */}
      <ul className="space-y-1.5">
        {steps.map((step, idx) => (
          <StepItem
            key={step.id}
            step={step}
            index={idx}
            isOptimisticallyUpdated={optimisticUpdates.has(step.step_number)}
            onToggle={handleToggleStep}
            isUpdating={updatingSteps.has(step.step_number)}
          />
        ))}
      </ul>
    </div>
  );
}

export function SubtasksSection({
  projectId,
  taskId,
  subtasks,
  onTogglePass,
  isLoading = false,
}: SubtasksSectionProps) {
  const [expandedPhases, setExpandedPhases] = useState<Set<string>>(new Set());
  const [expandedSubtasks, setExpandedSubtasks] = useState<Set<string>>(
    new Set(),
  );
  const [updatingIds, setUpdatingIds] = useState<Set<string>>(new Set());

  const groupedSubtasks = useMemo(() => groupByPhase(subtasks), [subtasks]);
  const phases = Object.keys(groupedSubtasks);

  const togglePhase = (phase: string) => {
    setExpandedPhases((prev) => {
      const next = new Set(prev);
      if (next.has(phase)) {
        next.delete(phase);
      } else {
        next.add(phase);
      }
      return next;
    });
  };

  const toggleSubtask = (subtaskId: string) => {
    setExpandedSubtasks((prev) => {
      const next = new Set(prev);
      if (next.has(subtaskId)) {
        next.delete(subtaskId);
      } else {
        next.add(subtaskId);
      }
      return next;
    });
  };

  const handleTogglePass = async (subtask: Subtask) => {
    setUpdatingIds((prev) => new Set(prev).add(subtask.id));
    try {
      await onTogglePass(subtask.subtask_id, !subtask.passes);
    } finally {
      setUpdatingIds((prev) => {
        const next = new Set(prev);
        next.delete(subtask.id);
        return next;
      });
    }
  };

  // Get step count for a subtask (from table or legacy)
  const getStepInfo = (subtask: Subtask) => {
    if (subtask.step_summary) {
      return {
        total: subtask.step_summary.total,
        completed: subtask.step_summary.completed,
      };
    }
    if (subtask.steps_from_table?.length) {
      const completed = subtask.steps_from_table.filter((s) => s.passes).length;
      return { total: subtask.steps_from_table.length, completed };
    }
    if (subtask.steps?.length) {
      return { total: subtask.steps.length, completed: 0 };
    }
    return null;
  };

  if (subtasks.length === 0) {
    return (
      <section>
        <div className="flex items-center gap-2 mb-2">
          <FileCode className="w-4 h-4 text-slate-500" />
          <h4 className="text-xs font-mono uppercase tracking-wider text-slate-400">
            Subtasks
          </h4>
        </div>
        <div className="p-4 bg-slate-800/50 rounded-lg text-center">
          <p className="text-sm text-slate-500">No subtasks defined</p>
        </div>
      </section>
    );
  }

  const totalComplete = subtasks.filter((s) => s.passes).length;

  return (
    <section>
      <div className="flex items-center gap-2 mb-3">
        <FileCode className="w-4 h-4 text-blue-400" />
        <h4 className="text-xs font-mono uppercase tracking-wider text-slate-400">
          Subtasks
        </h4>
        <span className="text-2xs text-slate-500">
          {totalComplete}/{subtasks.length} complete
        </span>
        {isLoading && (
          <Loader2 className="w-3 h-3 animate-spin text-slate-500" />
        )}
      </div>

      <div className="space-y-1 rounded-lg border border-slate-800 overflow-hidden">
        {phases.map((phase) => {
          const phaseSubtasks = groupedSubtasks[phase];
          const isExpanded = expandedPhases.has(phase);
          const config = PHASE_CONFIG[phase] || PHASE_CONFIG.other;
          const PhaseIcon = config.icon;
          const completedCount = phaseSubtasks.filter((s) => s.passes).length;

          return (
            <div key={phase}>
              {/* Phase Header */}
              <button
                onClick={() => togglePhase(phase)}
                className="w-full flex items-center gap-3 px-4 py-2.5 bg-slate-800/50 hover:bg-slate-800 transition-colors"
              >
                {isExpanded ? (
                  <ChevronDown className="w-4 h-4 text-slate-500" />
                ) : (
                  <ChevronRight className="w-4 h-4 text-slate-500" />
                )}
                <span className={`p-1.5 rounded ${config.bgColor}`}>
                  <PhaseIcon className={`w-3.5 h-3.5 ${config.color}`} />
                </span>
                <span className="text-sm text-slate-200 capitalize flex-1 text-left">
                  {phase}
                </span>
                <span
                  className={`text-xs font-mono ${
                    completedCount === phaseSubtasks.length
                      ? "text-phosphor-400"
                      : "text-slate-500"
                  }`}
                >
                  {completedCount}/{phaseSubtasks.length}
                </span>
              </button>

              {/* Subtasks List */}
              <AnimatePresence>
                {isExpanded && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    className="overflow-hidden"
                  >
                    <div className="divide-y divide-slate-800/50">
                      {phaseSubtasks
                        .sort((a, b) => a.display_order - b.display_order)
                        .map((subtask) => {
                          const isSubtaskExpanded = expandedSubtasks.has(
                            subtask.id,
                          );
                          const isUpdating = updatingIds.has(subtask.id);
                          const stepInfo = getStepInfo(subtask);

                          return (
                            <div key={subtask.id} className="bg-slate-900/50">
                              {/* Subtask Row */}
                              <div className="flex items-start gap-3 px-4 py-2.5">
                                {/* Checkbox */}
                                <button
                                  onClick={() => handleTogglePass(subtask)}
                                  disabled={isUpdating}
                                  className="mt-0.5 flex-shrink-0"
                                >
                                  {isUpdating ? (
                                    <Loader2 className="w-4 h-4 animate-spin text-slate-500" />
                                  ) : subtask.passes ? (
                                    <CheckCircle2 className="w-4 h-4 text-phosphor-400" />
                                  ) : (
                                    <Circle className="w-4 h-4 text-slate-600 hover:text-slate-400 transition-colors" />
                                  )}
                                </button>

                                {/* Content */}
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-2">
                                    <span className="text-2xs font-mono text-slate-600">
                                      {subtask.subtask_id}
                                    </span>
                                    <span
                                      className={`text-sm ${
                                        subtask.passes
                                          ? "text-slate-500 line-through"
                                          : "text-slate-200"
                                      }`}
                                    >
                                      {subtask.description}
                                    </span>
                                  </div>

                                  {/* Steps Toggle with progress */}
                                  {stepInfo && stepInfo.total > 0 && (
                                    <button
                                      onClick={() => toggleSubtask(subtask.id)}
                                      className="mt-1 flex items-center gap-2 text-2xs text-slate-500 hover:text-slate-400 transition-colors group"
                                    >
                                      <span>
                                        {isSubtaskExpanded ? "Hide" : "Show"}{" "}
                                        steps
                                      </span>
                                      <span
                                        className={`font-mono px-1.5 py-0.5 rounded ${
                                          stepInfo.completed === stepInfo.total
                                            ? "bg-phosphor-500/10 text-phosphor-400"
                                            : "bg-slate-800 text-slate-500"
                                        }`}
                                      >
                                        {stepInfo.completed}/{stepInfo.total}
                                      </span>
                                    </button>
                                  )}
                                </div>
                              </div>

                              {/* Steps */}
                              <AnimatePresence>
                                {isSubtaskExpanded &&
                                  stepInfo &&
                                  stepInfo.total > 0 && (
                                    <motion.div
                                      initial={{ height: 0, opacity: 0 }}
                                      animate={{ height: "auto", opacity: 1 }}
                                      exit={{ height: 0, opacity: 0 }}
                                      className="overflow-hidden"
                                    >
                                      <StepsList
                                        projectId={projectId}
                                        taskId={taskId}
                                        subtask={subtask}
                                      />
                                    </motion.div>
                                  )}
                              </AnimatePresence>
                            </div>
                          );
                        })}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
    </section>
  );
}
