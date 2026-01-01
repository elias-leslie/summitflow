"use client";

import { useMemo, useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import type { TaskAcceptanceCriterion } from "@/lib/api/tasks";

interface CriteriaProgressProps {
  criteria: TaskAcceptanceCriterion[];
  maxVisible?: number;
  /** If true, clicking shows expanded list. Default false for table rows. */
  expandable?: boolean;
}

export function CriteriaProgress({
  criteria,
  maxVisible = 5,
  expandable = false,
}: CriteriaProgressProps) {
  const [isExpanded, setIsExpanded] = useState(false);

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
    return <span className="text-2xs text-slate-600">—</span>;
  }

  const tooltipContent = criteria
    .map(
      (c, i) =>
        `${c.verified ? "✓" : "○"} ${i + 1}. ${c.criterion.slice(0, 40)}${c.criterion.length > 40 ? "..." : ""}`
    )
    .join("\n");

  const handleClick = (e: React.MouseEvent) => {
    if (expandable) {
      e.stopPropagation();
      setIsExpanded(!isExpanded);
    }
  };

  return (
    <div className="relative">
      <div
        onClick={handleClick}
        className={`inline-flex items-center gap-1.5 group ${expandable ? "cursor-pointer" : "cursor-default"}`}
        title={expandable ? "Click to expand" : tooltipContent}
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
            <span className="text-2xs text-slate-600 ml-0.5">
              +{hiddenCount}
            </span>
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

      {/* Expanded List */}
      {expandable && isExpanded && (
        <div className="absolute top-full left-0 mt-1 z-50 min-w-[250px] max-w-[350px] rounded-lg border border-slate-700 bg-slate-800 shadow-xl p-2 space-y-1">
          <div className="text-2xs text-slate-500 uppercase tracking-wider px-1 mb-1">
            Acceptance Criteria
          </div>
          {criteria.map((c, i) => (
            <div
              key={c.id || i}
              className="flex items-start gap-2 p-1.5 rounded hover:bg-slate-700/50"
            >
              {c.verified ? (
                <CheckCircle2 className="h-3.5 w-3.5 mt-0.5 text-phosphor-400 flex-shrink-0" />
              ) : (
                <XCircle className="h-3.5 w-3.5 mt-0.5 text-slate-500 flex-shrink-0" />
              )}
              <span className="text-xs text-slate-300 line-clamp-2">
                {c.criterion}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
