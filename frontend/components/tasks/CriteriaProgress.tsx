"use client";

import { useMemo, useState } from "react";
import { CheckCircle2, XCircle, Play, Loader2 } from "lucide-react";
import type { TaskAcceptanceCriterion } from "@/lib/api/tasks";

interface CriteriaProgressProps {
  criteria: TaskAcceptanceCriterion[];
  maxVisible?: number;
  /** If true, clicking shows expanded list. Default false for table rows. */
  expandable?: boolean;
  /** Callback when user verifies a criterion. If provided, shows verify buttons. */
  onVerify?: (
    criterionId: string,
    verifiedBy: "test" | "opus" | "human" | "agent",
  ) => Promise<void>;
  /** Project and task IDs for verification context */
  projectId?: string;
  taskId?: string;
}

export function CriteriaProgress({
  criteria,
  maxVisible = 5,
  expandable = false,
  onVerify,
  projectId,
  taskId,
}: CriteriaProgressProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [verifyingId, setVerifyingId] = useState<string | null>(null);

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
        `${c.verified ? "✓" : "○"} ${i + 1}. ${c.criterion.slice(0, 40)}${c.criterion.length > 40 ? "..." : ""}`,
    )
    .join("\n");

  const handleClick = (e: React.MouseEvent) => {
    if (expandable) {
      e.stopPropagation();
      setIsExpanded(!isExpanded);
    }
  };

  const handleVerify = async (
    criterionId: string,
    verifiedBy: "test" | "opus" | "human" | "agent",
  ) => {
    if (!onVerify) return;
    setVerifyingId(criterionId);
    try {
      await onVerify(criterionId, verifiedBy);
    } finally {
      setVerifyingId(null);
    }
  };

  const formatDate = (dateStr: string | null | undefined) => {
    if (!dateStr) return "";
    const date = new Date(dateStr);
    return date.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
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
        <div className="absolute top-full left-0 mt-1 z-50 min-w-[300px] max-w-[400px] rounded-lg border border-slate-700 bg-slate-800 shadow-xl p-2 space-y-1">
          <div className="text-2xs text-slate-500 uppercase tracking-wider px-1 mb-1">
            Acceptance Criteria
          </div>
          {criteria.map((c, i) => {
            const criterionId = c.criterion_id || c.id;
            const isVerifying = verifyingId === criterionId;

            return (
              <div
                key={c.id || i}
                className="flex flex-col gap-1 p-2 rounded hover:bg-slate-700/50 border-b border-slate-700/50 last:border-0"
              >
                <div className="flex items-start gap-2">
                  {c.verified ? (
                    <CheckCircle2 className="h-3.5 w-3.5 mt-0.5 text-phosphor-400 flex-shrink-0" />
                  ) : (
                    <XCircle className="h-3.5 w-3.5 mt-0.5 text-slate-500 flex-shrink-0" />
                  )}
                  <span className="text-xs text-slate-300 line-clamp-2 flex-1">
                    {c.criterion}
                  </span>
                </div>

                {/* Verify Command */}
                {c.verify_command && (
                  <div className="ml-5 mt-1">
                    <div className="text-2xs text-slate-500 uppercase tracking-wider mb-0.5">
                      Verify Command
                    </div>
                    <code className="text-2xs text-slate-400 bg-slate-900/50 px-1.5 py-0.5 rounded block whitespace-pre-wrap break-all">
                      {c.verify_command.length > 100
                        ? c.verify_command.slice(0, 100) + "..."
                        : c.verify_command}
                    </code>
                  </div>
                )}

                {/* Expected Output */}
                {c.expected_output && (
                  <div className="ml-5 mt-1">
                    <div className="text-2xs text-slate-500 uppercase tracking-wider mb-0.5">
                      Expected Output
                    </div>
                    <span className="text-2xs text-slate-400">
                      {c.expected_output}
                    </span>
                  </div>
                )}

                {/* Verify By + Verification Status */}
                <div className="ml-5 flex items-center gap-2 mt-1 flex-wrap">
                  {c.verify_by && (
                    <>
                      <span className="text-2xs text-slate-500">via</span>
                      <span
                        className={`text-2xs px-1.5 py-0.5 rounded ${
                          c.verify_by === "test"
                            ? "bg-blue-900/50 text-blue-400"
                            : c.verify_by === "opus"
                              ? "bg-purple-900/50 text-purple-400"
                              : c.verify_by === "human"
                                ? "bg-amber-900/50 text-amber-400"
                                : "bg-slate-700 text-slate-400"
                        }`}
                      >
                        {c.verify_by}
                      </span>
                    </>
                  )}

                  {/* Verification History */}
                  {c.verified && c.verified_at && (
                    <span className="text-2xs text-slate-500">
                      • verified {formatDate(c.verified_at)}
                      {c.verified_by_who && ` by ${c.verified_by_who}`}
                    </span>
                  )}
                </div>

                {/* Verify Button - only show if onVerify provided and not verified */}
                {onVerify && !c.verified && criterionId && (
                  <div className="ml-5 mt-2 flex items-center gap-2">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleVerify(criterionId, c.verify_by || "human");
                      }}
                      disabled={isVerifying}
                      className="inline-flex items-center gap-1 px-2 py-1 text-2xs bg-phosphor-600/20 hover:bg-phosphor-600/30 text-phosphor-400 rounded transition-colors disabled:opacity-50"
                    >
                      {isVerifying ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <Play className="h-3 w-3" />
                      )}
                      Mark Verified
                    </button>
                    {c.verify_by === "human" && (
                      <span className="text-2xs text-slate-500">
                        (manual confirmation)
                      </span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
