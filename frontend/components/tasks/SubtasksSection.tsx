"use client";

import { useState, useMemo } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  ChevronDown,
  ChevronRight,
  FileCode,
  Database,
  Server,
  Layout,
  TestTube,
  Search,
  CheckCircle2,
  Circle,
  Loader2,
} from "lucide-react";
import type { Subtask } from "@/lib/api/tasks";

interface SubtasksSectionProps {
  subtasks: Subtask[];
  onTogglePass: (subtaskId: string, passes: boolean) => Promise<void>;
  isLoading?: boolean;
}

const PHASE_CONFIG: Record<
  string,
  { icon: React.ElementType; color: string; bgColor: string }
> = {
  research: {
    icon: Search,
    color: "text-blue-400",
    bgColor: "bg-blue-500/10",
  },
  database: {
    icon: Database,
    color: "text-amber-400",
    bgColor: "bg-amber-500/10",
  },
  backend: {
    icon: Server,
    color: "text-emerald-400",
    bgColor: "bg-emerald-500/10",
  },
  frontend: {
    icon: Layout,
    color: "text-violet-400",
    bgColor: "bg-violet-500/10",
  },
  testing: {
    icon: TestTube,
    color: "text-rose-400",
    bgColor: "bg-rose-500/10",
  },
  other: {
    icon: FileCode,
    color: "text-slate-400",
    bgColor: "bg-slate-500/10",
  },
};

function groupByPhase(subtasks: Subtask[]): Record<string, Subtask[]> {
  return subtasks.reduce(
    (acc, subtask) => {
      const phase = subtask.phase || "other";
      if (!acc[phase]) acc[phase] = [];
      acc[phase].push(subtask);
      return acc;
    },
    {} as Record<string, Subtask[]>
  );
}

export function SubtasksSection({
  subtasks,
  onTogglePass,
  isLoading = false,
}: SubtasksSectionProps) {
  const [expandedPhases, setExpandedPhases] = useState<Set<string>>(new Set());
  const [expandedSubtasks, setExpandedSubtasks] = useState<Set<string>>(
    new Set()
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
        {isLoading && <Loader2 className="w-3 h-3 animate-spin text-slate-500" />}
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
                            subtask.id
                          );
                          const isUpdating = updatingIds.has(subtask.id);

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

                                  {/* Steps Toggle */}
                                  {subtask.steps && subtask.steps.length > 0 && (
                                    <button
                                      onClick={() => toggleSubtask(subtask.id)}
                                      className="mt-1 text-2xs text-slate-500 hover:text-slate-400 transition-colors"
                                    >
                                      {isSubtaskExpanded ? "Hide" : "Show"}{" "}
                                      {subtask.steps.length} steps
                                    </button>
                                  )}
                                </div>
                              </div>

                              {/* Steps */}
                              <AnimatePresence>
                                {isSubtaskExpanded &&
                                  subtask.steps &&
                                  subtask.steps.length > 0 && (
                                    <motion.div
                                      initial={{ height: 0, opacity: 0 }}
                                      animate={{ height: "auto", opacity: 1 }}
                                      exit={{ height: 0, opacity: 0 }}
                                      className="overflow-hidden"
                                    >
                                      <ul className="pl-11 pr-4 pb-3 space-y-1">
                                        {subtask.steps.map((step, idx) => (
                                          <li
                                            key={idx}
                                            className="text-xs text-slate-500 flex items-start gap-2"
                                          >
                                            <span className="text-slate-700 flex-shrink-0">
                                              {idx + 1}.
                                            </span>
                                            <span>{step}</span>
                                          </li>
                                        ))}
                                      </ul>
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
