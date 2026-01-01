"use client";

import { useMemo } from "react";
import type { TaskAcceptanceCriterion } from "@/lib/api/tasks";

interface CriteriaProgressProps {
  criteria: TaskAcceptanceCriterion[];
  maxVisible?: number;
}

export function CriteriaProgress({
  criteria,
  maxVisible = 5,
}: CriteriaProgressProps) {
  const { verified, total, displayCriteria, hiddenCount } = useMemo(() => {
    const sorted = [...criteria].sort((a, b) => {
      // Show verified ones first
      if (a.verified && !b.verified) return -1;
      if (!a.verified && b.verified) return 1;
      return 0;
    });

    return {
      verified: criteria.filter((c) => c.verified).length,
      total: criteria.length,
      displayCriteria: sorted.slice(0, maxVisible),
      hiddenCount: Math.max(0, sorted.length - maxVisible),
    };
  }, [criteria, maxVisible]);

  if (total === 0) {
    return (
      <span className="text-2xs text-slate-600">—</span>
    );
  }

  const tooltipContent = criteria
    .map((c, i) => `${c.verified ? "✓" : "○"} ${i + 1}. ${c.criterion.slice(0, 40)}${c.criterion.length > 40 ? "..." : ""}`)
    .join("\n");

  return (
    <div
      className="inline-flex items-center gap-1.5 group cursor-default"
      title={tooltipContent}
    >
      {/* Dots */}
      <div className="flex items-center gap-0.5">
        {displayCriteria.map((criterion, index) => (
          <div
            key={criterion.id || index}
            className={`w-2 h-2 rounded-full transition-all duration-200 ${
              criterion.verified
                ? "bg-phosphor-400 shadow-sm shadow-phosphor-400/30"
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
          verified === total
            ? "text-phosphor-400"
            : verified > 0
              ? "text-slate-400"
              : "text-slate-600"
        }`}
      >
        {verified}/{total}
      </span>
    </div>
  );
}
