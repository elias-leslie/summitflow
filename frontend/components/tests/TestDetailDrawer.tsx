"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Play,
  CheckCircle2,
  XCircle,
  HelpCircle,
  Clock,
  Timer,
  Terminal,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  Image,
} from "lucide-react";

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetClose,
  SheetBody,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  fetchTddTest,
  runTddTest,
  type TddTest,
  type TddTestWithHistory,
} from "@/lib/api";

interface TestDetailDrawerProps {
  test: TddTest | null;
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function getResultIcon(result: string | null, size: "sm" | "md" = "sm") {
  const sizeClass = size === "sm" ? "h-4 w-4" : "h-5 w-5";
  if (result === "passed") {
    return <CheckCircle2 className={`${sizeClass} text-phosphor-400`} />;
  }
  if (result === "failed" || result === "error") {
    return <XCircle className={`${sizeClass} text-rose-400`} />;
  }
  if (result === "timeout") {
    return <Timer className={`${sizeClass} text-amber-400`} />;
  }
  return <HelpCircle className={`${sizeClass} text-slate-500`} />;
}

function getTypeColor(type: string): string {
  const colors: Record<string, string> = {
    pytest: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    vitest: "bg-cyan-500/20 text-cyan-400 border-cyan-500/30",
    mypy: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    ruff: "bg-orange-500/20 text-orange-400 border-orange-500/30",
    api: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    ui: "bg-purple-500/20 text-purple-400 border-purple-500/30",
  };
  return colors[type] || "bg-slate-500/20 text-slate-400 border-slate-500/30";
}

function formatDuration(ms: number | null): string {
  if (ms === null) return "-";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "-";
  return new Date(dateStr).toLocaleString();
}

export function TestDetailDrawer({
  test,
  projectId,
  open,
  onOpenChange,
}: TestDetailDrawerProps) {
  const queryClient = useQueryClient();
  const [isRunning, setIsRunning] = useState(false);
  const [expandedRuns, setExpandedRuns] = useState<Set<number>>(new Set());

  // Fetch full test details with history
  const { data: testDetails } = useQuery<TddTestWithHistory>({
    queryKey: ["tdd-test", projectId, test?.test_id],
    queryFn: () => fetchTddTest(projectId, test!.test_id),
    enabled: open && !!test,
  });

  const handleRunTest = async () => {
    if (!test) return;
    setIsRunning(true);
    try {
      await runTddTest(projectId, test.test_id);
      // Refresh test details and list
      queryClient.invalidateQueries({
        queryKey: ["tdd-test", projectId, test.test_id],
      });
      queryClient.invalidateQueries({ queryKey: ["tdd-tests", projectId] });
    } finally {
      setIsRunning(false);
    }
  };

  const toggleRun = (runId: number) => {
    setExpandedRuns((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) {
        next.delete(runId);
      } else {
        next.add(runId);
      }
      return next;
    });
  };

  const details = testDetails || test;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full max-w-lg">
        <SheetHeader className="flex flex-row items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              {details && getResultIcon(details.last_result, "md")}
              <span
                className={`text-xs px-2 py-0.5 rounded border font-medium ${getTypeColor(details?.test_type || "")}`}
              >
                {details?.test_type}
              </span>
            </div>
            <SheetTitle className="truncate">{details?.name}</SheetTitle>
            <p className="text-xs text-slate-500 mono mt-1">
              {details?.test_id}
            </p>
          </div>
          <SheetClose onClose={() => onOpenChange(false)} />
        </SheetHeader>

        <SheetBody className="space-y-6">
          {/* Actions */}
          <div className="flex gap-2">
            <Button
              onClick={handleRunTest}
              disabled={isRunning}
              className="flex-1"
            >
              {isRunning ? (
                <div className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2" />
              ) : (
                <Play className="h-4 w-4 mr-2" />
              )}
              Run Test
            </Button>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-3 text-center">
              <div className="text-lg font-bold text-white mono">
                {details?.run_count || 0}
              </div>
              <div className="text-xs text-slate-500">Runs</div>
            </div>
            <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-3 text-center">
              <div className="text-lg font-bold text-phosphor-400 mono">
                {details?.pass_count || 0}
              </div>
              <div className="text-xs text-slate-500">Passed</div>
            </div>
            <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-3 text-center">
              <div className="text-lg font-bold text-rose-400 mono">
                {details?.fail_count || 0}
              </div>
              <div className="text-xs text-slate-500">Failed</div>
            </div>
          </div>

          {/* Flaky warning */}
          {(details?.flaky_score || 0) > 0.2 && (
            <div className="flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-amber-400 text-sm">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>
                This test is flaky (
                {((details?.flaky_score || 0) * 100).toFixed(0)}% inconsistent
                results)
              </span>
            </div>
          )}

          {/* UI Test Config (for browser-automation tests) */}
          {details?.test_type === "ui" &&
            details?.config &&
            Object.keys(details.config).length > 0 && (
              <div>
                <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                  <Image
                    className="h-3.5 w-3.5"
                    aria-label="Browser automation icon"
                  />
                  Browser Automation
                </h3>
                <div className="rounded-lg bg-slate-800 p-3 space-y-2">
                  {(details.config as { script_name?: string }).script_name && (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-slate-500">Script:</span>
                      <span className="text-xs font-medium text-purple-400">
                        {
                          (details.config as { script_name?: string })
                            .script_name
                        }
                      </span>
                    </div>
                  )}
                  {(details.config as { url?: string }).url && (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-slate-500">URL:</span>
                      <code className="text-xs text-blue-400 truncate max-w-[280px]">
                        {(details.config as { url?: string }).url}
                      </code>
                    </div>
                  )}
                  {(details.config as { assertions?: unknown[] }).assertions &&
                    (details.config as { assertions: unknown[] }).assertions
                      .length > 0 && (
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-slate-500">
                          Assertions:
                        </span>
                        <span className="text-xs text-slate-300">
                          {
                            (details.config as { assertions: unknown[] })
                              .assertions.length
                          }{" "}
                          checks
                        </span>
                      </div>
                    )}
                </div>
              </div>
            )}

          {/* Command/Script */}
          {details?.command && (
            <div>
              <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-2">
                Command
              </h3>
              <pre className="rounded-lg bg-slate-800 p-3 text-xs text-slate-300 overflow-x-auto">
                {details.command}
              </pre>
            </div>
          )}

          {/* Last Run Info */}
          {details?.last_run_at && (
            <div>
              <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-2">
                Last Run
              </h3>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-slate-500">Date</span>
                  <span className="text-slate-300">
                    {formatDate(details.last_run_at)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Duration</span>
                  <span className="text-slate-300 flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {formatDuration(details.last_duration_ms)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Result</span>
                  <span className="flex items-center gap-1.5">
                    {getResultIcon(details.last_result)}
                    <span
                      className={
                        details.last_result === "passed"
                          ? "text-phosphor-400"
                          : "text-rose-400"
                      }
                    >
                      {details.last_result || "Not run"}
                    </span>
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Last Output */}
          {(details?.last_output || details?.last_error) && (
            <div>
              <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                <Terminal className="h-3.5 w-3.5" />
                Last Output
              </h3>
              <ScrollArea className="h-40">
                <pre className="rounded-lg bg-slate-800 p-3 text-xs text-slate-300 whitespace-pre-wrap">
                  {details?.last_error || details?.last_output || "No output"}
                </pre>
              </ScrollArea>
            </div>
          )}

          {/* Run History */}
          {testDetails?.run_history && testDetails.run_history.length > 0 && (
            <div>
              <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-2">
                Run History
              </h3>
              <div className="space-y-1">
                {testDetails.run_history.map((run) => {
                  const isExpanded = expandedRuns.has(run.id);
                  return (
                    <div
                      key={run.id}
                      className="rounded border border-slate-700 bg-slate-800/30 overflow-hidden"
                    >
                      <div
                        className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-slate-800/50"
                        onClick={() => toggleRun(run.id)}
                      >
                        {isExpanded ? (
                          <ChevronDown className="h-3.5 w-3.5 text-slate-500" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5 text-slate-500" />
                        )}
                        {getResultIcon(run.result)}
                        <span className="flex-1 text-xs text-slate-400">
                          {formatDate(run.created_at)}
                        </span>
                        <span className="text-xs text-slate-500">
                          {formatDuration(run.duration_ms)}
                        </span>
                      </div>
                      {isExpanded && (
                        <div className="border-t border-slate-700 space-y-2">
                          {run.evidence_path && (
                            <div className="p-2 bg-slate-800/50">
                              <div className="flex items-center gap-1.5 text-xs text-purple-400 mb-1.5">
                                <Image
                                  className="h-3 w-3"
                                  aria-label="Evidence captured icon"
                                />
                                <span className="font-medium">
                                  Evidence Captured
                                </span>
                              </div>
                              <code className="text-xs text-slate-500 break-all">
                                {run.evidence_path}
                              </code>
                            </div>
                          )}
                          {(run.output || run.error) && (
                            <div className="p-2">
                              <pre className="text-xs text-slate-400 whitespace-pre-wrap max-h-32 overflow-y-auto">
                                {run.error || run.output}
                              </pre>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}
