"use client";

import { useState, useMemo } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Search,
  Download,
  Play,
  RefreshCw,
} from "lucide-react";

import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { TestList } from "@/components/tests/TestList";
import { TestDetailDrawer } from "@/components/tests/TestDetailDrawer";
import { ImportTestsDialog } from "@/components/tests/ImportTestsDialog";
import {
  fetchTddTests,
  runTddTest,
  runTddTests,
  type TddTest,
} from "@/lib/api";

function TestsPageSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
            <Skeleton className="h-8 w-16 mb-2" />
            <Skeleton className="h-4 w-24" />
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-3">
        <Skeleton className="h-10 flex-1 min-w-[250px]" />
        <Skeleton className="h-10 w-[150px]" />
        <Skeleton className="h-10 w-[120px]" />
      </div>
      <div className="space-y-3">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-24 w-full rounded-lg" />
        ))}
      </div>
    </div>
  );
}

export default function TestsPage() {
  const params = useParams();
  const projectId = params.id as string;
  const queryClient = useQueryClient();

  const [searchQuery, setSearchQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [selectedTest, setSelectedTest] = useState<TddTest | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [runningTests, setRunningTests] = useState<Set<string>>(new Set());
  const [isRunningAll, setIsRunningAll] = useState(false);

  // Fetch tests
  const { data: tests = [], isLoading, refetch } = useQuery({
    queryKey: ["tdd-tests", projectId],
    queryFn: () => fetchTddTests(projectId),
  });

  // Compute stats
  const stats = useMemo(() => {
    const passCount = tests.filter((t) => t.last_result === "passed").length;
    const failCount = tests.filter((t) => t.last_result === "failed" || t.last_result === "error").length;
    const pendingCount = tests.filter((t) => !t.last_result).length;
    const types = new Set(tests.map((t) => t.test_type));
    return { total: tests.length, passCount, failCount, pendingCount, types: Array.from(types).sort() };
  }, [tests]);

  // Filter tests
  const filteredTests = useMemo(() => {
    let result = tests;

    // Type filter
    if (typeFilter !== "all") {
      result = result.filter((t) => t.test_type === typeFilter);
    }

    // Status filter
    if (statusFilter !== "all") {
      result = result.filter((t) => {
        if (statusFilter === "passed") return t.last_result === "passed";
        if (statusFilter === "failed") return t.last_result === "failed" || t.last_result === "error";
        if (statusFilter === "pending") return !t.last_result;
        return true;
      });
    }

    // Search filter
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (t) =>
          t.test_id.toLowerCase().includes(q) ||
          t.name.toLowerCase().includes(q)
      );
    }

    return result;
  }, [tests, typeFilter, statusFilter, searchQuery]);

  const handleRunTest = async (testId: string) => {
    setRunningTests((prev) => new Set(prev).add(testId));
    try {
      await runTddTest(projectId, testId);
      queryClient.invalidateQueries({ queryKey: ["tdd-tests", projectId] });
    } finally {
      setRunningTests((prev) => {
        const next = new Set(prev);
        next.delete(testId);
        return next;
      });
    }
  };

  const handleRunAll = async () => {
    const testIds = filteredTests.map((t) => t.test_id);
    if (testIds.length === 0) return;

    setIsRunningAll(true);
    setRunningTests(new Set(testIds));
    try {
      await runTddTests(projectId, { testIds });
      queryClient.invalidateQueries({ queryKey: ["tdd-tests", projectId] });
    } finally {
      setIsRunningAll(false);
      setRunningTests(new Set());
    }
  };

  const handleSelectTest = (test: TddTest) => {
    setSelectedTest(test);
    setDrawerOpen(true);
  };

  if (isLoading) {
    return (
      <div className="h-full overflow-auto p-4">
        <TestsPageSkeleton />
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto p-4 space-y-4">
      {/* Summary Cards */}
      <div className="grid grid-cols-4 gap-4">
        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
          <div className="text-2xl font-bold text-white mono">{stats.total}</div>
          <div className="text-sm text-slate-500">Total Tests</div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
          <div className="text-2xl font-bold text-phosphor-400 mono">{stats.passCount}</div>
          <div className="text-sm text-slate-500">Passed</div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
          <div className="text-2xl font-bold text-rose-400 mono">{stats.failCount}</div>
          <div className="text-sm text-slate-500">Failed</div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
          <div className="text-2xl font-bold text-slate-400 mono">{stats.pendingCount}</div>
          <div className="text-sm text-slate-500">Not Run</div>
        </div>
      </div>

      {/* Filters and Actions */}
      <div className="flex flex-wrap gap-3">
        <div className="relative flex-1 min-w-[250px]">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
          <Input
            type="text"
            placeholder="Search tests..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>

        {stats.types.length > 1 && (
          <Select value={typeFilter} onValueChange={setTypeFilter}>
            <SelectTrigger className="w-[150px]">
              <SelectValue placeholder="All Types" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Types</SelectItem>
              {stats.types.map((type) => (
                <SelectItem key={type} value={type}>{type}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-[130px]">
            <SelectValue placeholder="All Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Status</SelectItem>
            <SelectItem value="passed">Passed</SelectItem>
            <SelectItem value="failed">Failed</SelectItem>
            <SelectItem value="pending">Not Run</SelectItem>
          </SelectContent>
        </Select>

        <Button variant="outline" onClick={() => refetch()}>
          <RefreshCw className="h-4 w-4 mr-1.5" />
          Refresh
        </Button>

        <Button variant="outline" onClick={() => setImportDialogOpen(true)}>
          <Download className="h-4 w-4 mr-1.5" />
          Import
        </Button>

        <Button onClick={handleRunAll} disabled={filteredTests.length === 0 || isRunningAll}>
          {isRunningAll ? (
            <div className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-1.5" />
          ) : (
            <Play className="h-4 w-4 mr-1.5" />
          )}
          Run All ({filteredTests.length})
        </Button>
      </div>

      {/* Results count */}
      <div className="text-sm text-slate-500">
        {filteredTests.length > 0
          ? `Showing ${filteredTests.length} of ${tests.length} tests`
          : tests.length > 0
          ? "No tests match your filters"
          : "No tests found. Import tests to get started."}
      </div>

      {/* Tests List */}
      <TestList
        tests={filteredTests}
        isLoading={false}
        onRunTest={handleRunTest}
        onSelectTest={handleSelectTest}
        runningTests={runningTests}
      />

      {/* Test Detail Drawer */}
      <TestDetailDrawer
        test={selectedTest}
        projectId={projectId}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
      />

      {/* Import Dialog */}
      <ImportTestsDialog
        open={importDialogOpen}
        onOpenChange={setImportDialogOpen}
        projectId={projectId}
      />
    </div>
  );
}
