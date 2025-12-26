/**
 * AnalysisSummary - Collapsible analysis overview for Explorer
 *
 * Shows:
 * - Coverage gaps (endpoints, pages, tables without capabilities)
 * - Refactor targets (complex files needing attention)
 * - Multi-capability files (files linked to multiple capabilities)
 */

"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  FileWarning,
  Layers,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchCoverageGaps,
  fetchRefactorTargets,
  fetchMultiCapabilityFiles,
} from "@/lib/api/explorer";

interface AnalysisSummaryProps {
  projectId: string;
  className?: string;
}

export function AnalysisSummary({ projectId, className }: AnalysisSummaryProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  // Fetch analysis data
  const { data: coverageGaps, isLoading: gapsLoading } = useQuery({
    queryKey: ["coverage-gaps", projectId],
    queryFn: () => fetchCoverageGaps(projectId),
    staleTime: 60000,
  });

  const { data: refactorData, isLoading: targetsLoading } = useQuery({
    queryKey: ["refactor-targets", projectId],
    queryFn: () => fetchRefactorTargets(projectId),
    staleTime: 60000,
  });

  const { data: multiCapFiles = [], isLoading: multiCapLoading } = useQuery({
    queryKey: ["multi-capability-files", projectId],
    queryFn: () => fetchMultiCapabilityFiles(projectId),
    staleTime: 60000,
  });

  const isLoading = gapsLoading || targetsLoading || multiCapLoading;

  // Extract refactor targets from response
  const refactorTargets = refactorData?.targets ?? [];

  // Counts for summary
  const gapsCount = coverageGaps?.summary.total_uncovered ?? 0;
  const targetsCount = refactorData?.summary.high_priority_count ?? 0;
  const multiCapCount = multiCapFiles.length;
  const totalIssues = gapsCount + targetsCount + multiCapCount;

  if (totalIssues === 0 && !isLoading) {
    return null;
  }

  return (
    <div
      className={cn(
        "border-b border-slate-700/50 bg-slate-900/30",
        className
      )}
    >
      {/* Summary header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between px-4 py-2 hover:bg-slate-800/30 transition-colors"
      >
        <div className="flex items-center gap-3">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-slate-400" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-400" />
          )}
          <span className="text-sm font-medium text-slate-200">
            Analysis Overview
          </span>
          {isLoading && (
            <Loader2 className="w-3 h-3 animate-spin text-slate-400" />
          )}
        </div>

        <div className="flex items-center gap-4 text-xs">
          {gapsCount > 0 && (
            <div className="flex items-center gap-1.5 text-amber-400">
              <AlertTriangle className="w-3.5 h-3.5" />
              <span>{gapsCount} uncovered</span>
            </div>
          )}
          {targetsCount > 0 && (
            <div className="flex items-center gap-1.5 text-orange-400">
              <FileWarning className="w-3.5 h-3.5" />
              <span>{targetsCount} refactor</span>
            </div>
          )}
          {multiCapCount > 0 && (
            <div className="flex items-center gap-1.5 text-blue-400">
              <Layers className="w-3.5 h-3.5" />
              <span>{multiCapCount} multi-cap</span>
            </div>
          )}
        </div>
      </button>

      {/* Expanded content */}
      {isExpanded && (
        <div className="px-4 pb-3 space-y-3">
          {/* Coverage Gaps */}
          {gapsCount > 0 && coverageGaps && (
            <AnalysisSection
              title="Coverage Gaps"
              icon={<AlertTriangle className="w-4 h-4 text-amber-400" />}
              count={gapsCount}
              color="amber"
            >
              <div className="grid grid-cols-3 gap-2 text-xs">
                <div className="bg-slate-800/50 rounded px-2 py-1.5">
                  <span className="text-slate-400">Endpoints: </span>
                  <span className="text-slate-200">{coverageGaps.summary.endpoint_count}</span>
                </div>
                <div className="bg-slate-800/50 rounded px-2 py-1.5">
                  <span className="text-slate-400">Pages: </span>
                  <span className="text-slate-200">{coverageGaps.summary.page_count}</span>
                </div>
                <div className="bg-slate-800/50 rounded px-2 py-1.5">
                  <span className="text-slate-400">Tables: </span>
                  <span className="text-slate-200">{coverageGaps.summary.table_count}</span>
                </div>
              </div>
            </AnalysisSection>
          )}

          {/* Refactor Targets */}
          {targetsCount > 0 && (
            <AnalysisSection
              title="Refactor Targets"
              icon={<FileWarning className="w-4 h-4 text-orange-400" />}
              count={targetsCount}
              color="orange"
            >
              <div className="space-y-1">
                {refactorTargets.slice(0, 3).map((target) => (
                  <div
                    key={target.path}
                    className="flex items-center justify-between text-xs bg-slate-800/50 rounded px-2 py-1.5"
                  >
                    <span className="text-slate-300 truncate max-w-[200px]">
                      {target.path}
                    </span>
                    <span className="text-orange-400 shrink-0">
                      {Math.round(target.complexity_score)} complexity
                    </span>
                  </div>
                ))}
                {targetsCount > 3 && (
                  <div className="text-xs text-slate-500 pl-2">
                    +{targetsCount - 3} more
                  </div>
                )}
              </div>
            </AnalysisSection>
          )}

          {/* Multi-Capability Files */}
          {multiCapCount > 0 && (
            <AnalysisSection
              title="Multi-Capability Files"
              icon={<Layers className="w-4 h-4 text-blue-400" />}
              count={multiCapCount}
              color="blue"
            >
              <div className="space-y-1">
                {multiCapFiles.slice(0, 3).map((file) => (
                  <div
                    key={file.entry_id}
                    className="flex items-center justify-between text-xs bg-slate-800/50 rounded px-2 py-1.5"
                  >
                    <span className="text-slate-300 truncate max-w-[200px]">
                      {file.path}
                    </span>
                    <span className="text-blue-400 shrink-0">
                      {file.capability_count} capabilities
                    </span>
                  </div>
                ))}
                {multiCapCount > 3 && (
                  <div className="text-xs text-slate-500 pl-2">
                    +{multiCapCount - 3} more
                  </div>
                )}
              </div>
            </AnalysisSection>
          )}
        </div>
      )}
    </div>
  );
}

interface AnalysisSectionProps {
  title: string;
  icon: React.ReactNode;
  count: number;
  color: "amber" | "orange" | "blue";
  children: React.ReactNode;
}

function AnalysisSection({
  title,
  icon,
  count,
  color,
  children,
}: AnalysisSectionProps) {
  const borderColor = {
    amber: "border-amber-500/20",
    orange: "border-orange-500/20",
    blue: "border-blue-500/20",
  }[color];

  return (
    <div className={cn("border rounded-md p-2", borderColor)}>
      <div className="flex items-center gap-2 mb-2">
        {icon}
        <span className="text-xs font-medium text-slate-300">{title}</span>
        <span className="text-xs text-slate-500">({count})</span>
      </div>
      {children}
    </div>
  );
}
