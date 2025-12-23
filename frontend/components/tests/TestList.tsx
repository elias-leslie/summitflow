"use client";

import { useState, useMemo, Fragment } from "react";
import {
  CheckCircle2,
  XCircle,
  HelpCircle,
  ChevronDown,
  ChevronRight,
  Play,
  Clock,
  AlertTriangle,
  Timer,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { TddTest } from "@/lib/api";

interface TestListProps {
  tests: TddTest[];
  isLoading: boolean;
  onRunTest: (testId: string) => void;
  onSelectTest: (test: TddTest) => void;
  runningTests: Set<string>;
}

interface TestGroup {
  type: string;
  tests: TddTest[];
  passCount: number;
  failCount: number;
  pendingCount: number;
}

function TestListSkeleton() {
  return (
    <div className="space-y-3">
      {[...Array(4)].map((_, i) => (
        <div key={i} className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
          <div className="flex items-center gap-3 mb-3">
            <Skeleton className="h-5 w-5 rounded" />
            <Skeleton className="h-5 w-24" />
            <Skeleton className="h-5 w-16" />
          </div>
          <div className="space-y-2 pl-8">
            {[...Array(3)].map((_, j) => (
              <Skeleton key={j} className="h-8 w-full" />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function getResultIcon(result: string | null) {
  if (result === "passed") {
    return <CheckCircle2 className="h-4 w-4 text-phosphor-400" />;
  }
  if (result === "failed" || result === "error") {
    return <XCircle className="h-4 w-4 text-rose-400" />;
  }
  if (result === "timeout") {
    return <Timer className="h-4 w-4 text-amber-400" />;
  }
  return <HelpCircle className="h-4 w-4 text-slate-500" />;
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
  return `${(ms / 1000).toFixed(1)}s`;
}

export function TestList({
  tests,
  isLoading,
  onRunTest,
  onSelectTest,
  runningTests,
}: TestListProps) {
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

  // Group tests by type
  const groupedTests = useMemo<TestGroup[]>(() => {
    const groups: Record<string, TddTest[]> = {};

    for (const test of tests) {
      const type = test.test_type || "unknown";
      if (!groups[type]) {
        groups[type] = [];
      }
      groups[type].push(test);
    }

    return Object.entries(groups).map(([type, typeTests]) => ({
      type,
      tests: typeTests.sort((a, b) => a.name.localeCompare(b.name)),
      passCount: typeTests.filter((t) => t.last_result === "passed").length,
      failCount: typeTests.filter((t) => t.last_result === "failed" || t.last_result === "error").length,
      pendingCount: typeTests.filter((t) => !t.last_result).length,
    })).sort((a, b) => a.type.localeCompare(b.type));
  }, [tests]);

  const toggleGroup = (type: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return next;
    });
  };

  if (isLoading) return <TestListSkeleton />;

  if (tests.length === 0) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-8 text-center">
        <AlertTriangle className="mx-auto h-12 w-12 text-slate-600" />
        <p className="mt-4 text-sm text-slate-500">No tests found. Import tests to get started.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {groupedTests.map((group) => {
        const isExpanded = expandedGroups.has(group.type);

        return (
          <div
            key={group.type}
            className="rounded-lg border border-slate-700 bg-slate-900/50 overflow-hidden"
          >
            {/* Group Header */}
            <div
              className="flex items-center gap-3 p-3 cursor-pointer hover:bg-slate-800/50 transition-colors"
              onClick={() => toggleGroup(group.type)}
            >
              {isExpanded ? (
                <ChevronDown className="h-4 w-4 text-slate-500" />
              ) : (
                <ChevronRight className="h-4 w-4 text-slate-500" />
              )}
              <span
                className={`text-xs px-2 py-0.5 rounded border font-medium ${getTypeColor(group.type)}`}
              >
                {group.type}
              </span>
              <span className="text-sm text-slate-300 font-medium">
                {group.tests.length} test{group.tests.length !== 1 ? "s" : ""}
              </span>
              <div className="flex-1" />
              <div className="flex items-center gap-2 text-xs">
                {group.passCount > 0 && (
                  <Badge variant="phosphor" className="gap-1 text-xs">
                    <CheckCircle2 className="h-3 w-3" />
                    {group.passCount}
                  </Badge>
                )}
                {group.failCount > 0 && (
                  <Badge variant="rose" className="gap-1 text-xs">
                    <XCircle className="h-3 w-3" />
                    {group.failCount}
                  </Badge>
                )}
                {group.pendingCount > 0 && (
                  <Badge variant="slate" className="gap-1 text-xs">
                    <HelpCircle className="h-3 w-3" />
                    {group.pendingCount}
                  </Badge>
                )}
              </div>
            </div>

            {/* Tests List */}
            {isExpanded && (
              <div className="border-t border-slate-800">
                {group.tests.map((test) => {
                  const isRunning = runningTests.has(test.test_id);

                  return (
                    <div
                      key={test.test_id}
                      className="flex items-center gap-3 px-4 py-2 hover:bg-slate-800/30 border-b border-slate-800 last:border-b-0 cursor-pointer"
                      onClick={() => onSelectTest(test)}
                    >
                      {getResultIcon(test.last_result)}
                      <span className="mono text-xs text-slate-500 min-w-[100px] truncate">
                        {test.test_id}
                      </span>
                      <span className="flex-1 text-sm text-slate-200 truncate">
                        {test.name}
                      </span>
                      {test.flaky_score > 0.2 && (
                        <Badge variant="amber" className="text-xs gap-1">
                          <AlertTriangle className="h-3 w-3" />
                          Flaky
                        </Badge>
                      )}
                      {test.last_duration_ms !== null && (
                        <span className="flex items-center gap-1 text-xs text-slate-500">
                          <Clock className="h-3 w-3" />
                          {formatDuration(test.last_duration_ms)}
                        </span>
                      )}
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2"
                        onClick={(e) => {
                          e.stopPropagation();
                          onRunTest(test.test_id);
                        }}
                        disabled={isRunning}
                      >
                        {isRunning ? (
                          <div className="h-4 w-4 border-2 border-slate-500/30 border-t-slate-500 rounded-full animate-spin" />
                        ) : (
                          <Play className="h-3.5 w-3.5" />
                        )}
                      </Button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
