"use client";

import { useMemo } from "react";
import type { Subtask } from "@/lib/api/tasks";

interface SubtaskProgressProps {
  subtasks: Subtask[];
  maxVisible?: number;
}

export function SubtaskProgress({
  subtasks,
  maxVisible = 6,
}: SubtaskProgressProps) {
  const { completed, total, displaySubtasks, hiddenCount, nextIncomplete } =
    useMemo(() => {
      const sorted = [...subtasks].sort((a, b) => a.display_order - b.display_order);
      const nextInc = sorted.find((s) => !s.passes);

      return {
        completed: subtasks.filter((s) => s.passes).length,
        total: subtasks.length,
        displaySubtasks: sorted.slice(0, maxVisible),
        hiddenCount: Math.max(0, sorted.length - maxVisible),
        nextIncomplete: nextInc,
      };
    }, [subtasks, maxVisible]);

  if (total === 0) {
    return <span className="text-2xs text-slate-600">—</span>;
  }

  const tooltipContent = nextIncomplete
    ? `Next: ${nextIncomplete.subtask_id} - ${nextIncomplete.description.slice(0, 50)}${nextIncomplete.description.length > 50 ? "..." : ""}`
    : "All subtasks complete!";

  return (
    <div
      className="inline-flex items-center gap-1.5 group cursor-default"
      title={tooltipContent}
    >
      {/* Squares */}
      <div className="flex items-center gap-0.5">
        {displaySubtasks.map((subtask, index) => (
          <div
            key={subtask.id || index}
            className={`w-1.5 h-1.5 rounded-[1px] transition-all duration-200 ${
              subtask.passes
                ? "bg-emerald-400 shadow-sm shadow-emerald-400/30"
                : "bg-slate-700 group-hover:bg-slate-600"
            }`}
          />
        ))}
        {hiddenCount > 0 && (
          <span className="text-2xs text-slate-600 ml-0.5">+{hiddenCount}</span>
        )}
      </div>

      {/* Count */}
      <span
        className={`text-2xs font-mono transition-colors ${
          completed === total
            ? "text-emerald-400"
            : completed > 0
              ? "text-slate-400"
              : "text-slate-600"
        }`}
      >
        {completed}/{total}
      </span>
    </div>
  );
}
