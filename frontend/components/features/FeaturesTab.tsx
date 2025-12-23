"use client";

import { useState, Fragment, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Search,
  CheckCircle2,
  XCircle,
  HelpCircle,
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  Eye,
  AlertTriangle,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Plus,
} from "lucide-react";

import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { EvidenceViewerModal } from "@/components/evidence/EvidenceViewerModal";
import { CreateFeatureDialog } from "./CreateFeatureDialog";
import {
  fetchFeatures,
  fetchFeatureSummary,
  fetchVerificationSummary,
  type Feature,
  type FeaturesListResponse,
  type FeatureSummary,
  type VerificationSummary,
  type AcceptanceCriterion,
} from "@/lib/api";

interface FeaturesTabProps {
  projectId: string;
}

type SortColumn = "feature_id" | "priority" | "name" | "category" | "criteria" | "verified";
type SortDirection = "asc" | "desc";
type VerificationStatus = "verified" | "needs-review" | "has-tasks" | "no-criteria";

function FeaturesTabSkeleton() {
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
        <Skeleton className="h-10 w-[180px]" />
      </div>
      <div className="rounded-lg border border-slate-700">
        <div className="p-4 space-y-3">
          {[...Array(8)].map((_, i) => (
            <div key={i} className="flex items-center gap-4">
              <Skeleton className="h-4 w-20" />
              <Skeleton className="h-4 w-8" />
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-4 w-16" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function FeaturesTab({ projectId }: FeaturesTabProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
  const [pageSize, setPageSize] = useState(25);
  const [currentPage, setCurrentPage] = useState(1);
  const [sortColumn, setSortColumn] = useState<SortColumn>("feature_id");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");
  const [evidenceModal, setEvidenceModal] = useState<{
    open: boolean;
    featureId: string;
    criterionId: string;
    criterionText: string;
    verificationUrl: string;
  }>({ open: false, featureId: "", criterionId: "", criterionText: "", verificationUrl: "" });
  const [createDialogOpen, setCreateDialogOpen] = useState(false);

  // Fetch features
  const { data: featuresData, isLoading } = useQuery<FeaturesListResponse>({
    queryKey: ["features", projectId, categoryFilter],
    queryFn: () => fetchFeatures(projectId, {
      category: categoryFilter !== "all" ? categoryFilter : undefined,
      limit: 500,
    }),
    enabled: !!projectId,
  });

  // Fetch summary
  const { data: summaryData } = useQuery<FeatureSummary>({
    queryKey: ["feature-summary", projectId],
    queryFn: () => fetchFeatureSummary(projectId),
    enabled: !!projectId,
  });

  // Fetch verification summary
  const { data: verificationData } = useQuery<VerificationSummary>({
    queryKey: ["verification-summary", projectId],
    queryFn: () => fetchVerificationSummary(projectId),
    enabled: !!projectId,
  });

  // Toggle row expansion
  const toggleRow = (featureId: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(featureId)) {
        next.delete(featureId);
      } else {
        next.add(featureId);
      }
      return next;
    });
  };

  // Get verification status for feature
  const getVerificationStatus = (f: Feature): VerificationStatus => {
    const incompleteTasks = f.total_tasks - f.completed_tasks;
    const criteria = f.acceptance_criteria ?? [];
    const hasCriteria = criteria.length > 0;
    const allPassed = hasCriteria && criteria.every((c) => c.passed === true);

    if (incompleteTasks > 0) return "has-tasks";
    if (!hasCriteria) return "no-criteria";
    if (allPassed) return "verified";
    return "needs-review";
  };

  // Compute verification counts
  const verificationCounts = useMemo(() => {
    const features = featuresData?.features ?? [];
    let verified = 0;
    let needsReview = 0;
    let hasTasks = 0;
    let noCriteria = 0;

    for (const f of features) {
      const status = getVerificationStatus(f);
      if (status === "verified") verified++;
      else if (status === "needs-review") needsReview++;
      else if (status === "has-tasks") hasTasks++;
      else noCriteria++;
    }

    return { verified, needsReview, hasTasks, noCriteria };
  }, [featuresData?.features]);

  // Filter features
  const filteredFeatures = useMemo(() => {
    let features = featuresData?.features ?? [];

    // Status filter
    if (statusFilter !== "all") {
      features = features.filter((f) => {
        const status = getVerificationStatus(f);
        if (statusFilter === "verified") return status === "verified";
        if (statusFilter === "failing") return status === "needs-review" || status === "has-tasks";
        if (statusFilter === "pending") return status === "no-criteria";
        return true;
      });
    }

    // Search filter
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      features = features.filter((f) =>
        f.feature_id.toLowerCase().includes(q) ||
        f.name.toLowerCase().includes(q) ||
        f.category?.toLowerCase().includes(q)
      );
    }

    return features;
  }, [featuresData?.features, statusFilter, searchQuery]);

  // Sort features
  const sortedFeatures = useMemo(() => {
    return [...filteredFeatures].sort((a, b) => {
      let comparison = 0;

      switch (sortColumn) {
        case "feature_id":
          comparison = a.feature_id.localeCompare(b.feature_id, undefined, { numeric: true });
          break;
        case "priority":
          comparison = (a.priority ?? a.effective_priority) - (b.priority ?? b.effective_priority);
          break;
        case "name":
          comparison = a.name.localeCompare(b.name);
          break;
        case "category":
          comparison = (a.category ?? "").localeCompare(b.category ?? "");
          break;
        case "criteria": {
          const aPassed = a.acceptance_criteria?.filter(c => c.passed).length ?? 0;
          const bPassed = b.acceptance_criteria?.filter(c => c.passed).length ?? 0;
          comparison = aPassed - bPassed;
          break;
        }
        case "verified": {
          const statusOrder: Record<VerificationStatus, number> = {
            "has-tasks": 0, "no-criteria": 1, "needs-review": 2, "verified": 3
          };
          comparison = statusOrder[getVerificationStatus(a)] - statusOrder[getVerificationStatus(b)];
          break;
        }
      }

      return sortDirection === "asc" ? comparison : -comparison;
    });
  }, [filteredFeatures, sortColumn, sortDirection]);

  // Pagination
  const totalFiltered = sortedFeatures.length;
  const totalPages = Math.ceil(totalFiltered / pageSize);
  const startIndex = (currentPage - 1) * pageSize;
  const endIndex = Math.min(startIndex + pageSize, totalFiltered);
  const paginatedFeatures = sortedFeatures.slice(startIndex, endIndex);

  // Sort handler
  const handleSort = (column: SortColumn) => {
    if (sortColumn === column) {
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      setSortColumn(column);
      setSortDirection("asc");
    }
    setCurrentPage(1);
  };

  // Get sort icon
  const getSortIcon = (column: SortColumn) => {
    if (sortColumn !== column) return <ArrowUpDown className="h-3 w-3 ml-1 opacity-40" />;
    return sortDirection === "asc"
      ? <ArrowUp className="h-3 w-3 ml-1 text-phosphor-400" />
      : <ArrowDown className="h-3 w-3 ml-1 text-phosphor-400" />;
  };

  // Parse verification URL
  const parseVerificationUrl = (verification: string): string => {
    const match = verification.match(/screenshot\s+(\/[^\s]+)/i);
    if (match && typeof window !== "undefined") {
      return `${window.location.origin}${match[1]}`;
    }
    return "";
  };

  // Categories from summary
  const categories = summaryData?.category_breakdown
    ? Object.keys(summaryData.category_breakdown).sort()
    : [];

  // Render status badge
  const renderStatusBadge = (feature: Feature) => {
    const status = getVerificationStatus(feature);
    switch (status) {
      case "verified":
        return (
          <Badge variant="phosphor" className="gap-1">
            <CheckCircle2 className="h-3 w-3" /> Verified
          </Badge>
        );
      case "needs-review":
        return (
          <Badge variant="amber" className="gap-1">
            <HelpCircle className="h-3 w-3" /> Needs Review
          </Badge>
        );
      case "has-tasks":
        return (
          <Badge variant="amber" className="gap-1">
            <AlertTriangle className="h-3 w-3" /> Has Tasks
          </Badge>
        );
      default:
        return (
          <Badge variant="slate" className="gap-1">
            <HelpCircle className="h-3 w-3" /> No Criteria
          </Badge>
        );
    }
  };

  // Render priority badge
  const renderPriorityBadge = (priority: number | null, effective: number) => {
    const p = priority ?? effective;
    const colors: Record<number, string> = {
      1: "bg-rose-500/20 text-rose-400 border-rose-500/30",
      2: "bg-orange-500/20 text-orange-400 border-orange-500/30",
      3: "bg-amber-500/20 text-amber-400 border-amber-500/30",
      4: "bg-blue-500/20 text-blue-400 border-blue-500/30",
      5: "bg-slate-500/20 text-slate-400 border-slate-500/30",
    };
    return (
      <span className={`text-xs px-1.5 py-0.5 rounded border mono font-medium ${colors[p] || colors[5]}`}>
        P{p}
      </span>
    );
  };

  // Render criteria status
  const renderCriteriaStatus = (criteria: AcceptanceCriterion[]) => {
    if (!criteria?.length) return <span className="text-xs text-slate-600">—</span>;
    const passed = criteria.filter((c) => c.passed === true).length;
    const total = criteria.length;
    const allPassed = passed === total;
    const hasFailed = criteria.some((c) => c.passed === false);
    return (
      <span className={`text-xs mono font-medium ${allPassed ? "text-phosphor-400" : hasFailed ? "text-rose-400" : "text-slate-400"}`}>
        {passed}/{total}
      </span>
    );
  };

  if (isLoading) return <FeaturesTabSkeleton />;

  return (
    <div className="space-y-4">
      {/* Summary Cards */}
      <div className="grid grid-cols-5 gap-4">
        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
          <div className="text-2xl font-bold text-white mono">{summaryData?.total || 0}</div>
          <div className="text-sm text-slate-500">Total Features</div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
          <div className="text-2xl font-bold text-phosphor-400 mono">{verificationCounts.verified}</div>
          <div className="text-sm text-slate-500">Verified</div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
          <div className="text-2xl font-bold text-amber-400 mono">{verificationCounts.needsReview}</div>
          <div className="text-sm text-slate-500">Needs Review</div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
          <div className="text-2xl font-bold text-orange-400 mono">{verificationCounts.hasTasks}</div>
          <div className="text-sm text-slate-500">Has Tasks</div>
        </div>
        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
          <div className="text-2xl font-bold text-slate-400 mono">{verificationCounts.noCriteria}</div>
          <div className="text-sm text-slate-500">No Criteria</div>
        </div>
      </div>

      {/* Acceptance Criteria Summary */}
      {verificationData && (
        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-medium text-slate-300">Acceptance Criteria</span>
            <span className="text-xs text-slate-500 mono">{verificationData.total_criteria} total</span>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-phosphor-400" />
              <span className="text-lg font-semibold text-phosphor-400 mono">{verificationData.passed}</span>
              <span className="text-xs text-slate-500">passed</span>
            </div>
            <div className="flex items-center gap-2">
              <XCircle className="h-4 w-4 text-rose-400" />
              <span className="text-lg font-semibold text-rose-400 mono">{verificationData.failed}</span>
              <span className="text-xs text-slate-500">failed</span>
            </div>
            <div className="flex items-center gap-2">
              <HelpCircle className="h-4 w-4 text-amber-400" />
              <span className="text-lg font-semibold text-amber-400 mono">{verificationData.pending}</span>
              <span className="text-xs text-slate-500">pending</span>
            </div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div className="relative flex-1 min-w-[250px]">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
          <Input
            type="text"
            placeholder="Search features..."
            value={searchQuery}
            onChange={(e) => { setSearchQuery(e.target.value); setCurrentPage(1); }}
            className="pl-9"
          />
        </div>

        {categories.length > 0 && (
          <Select value={categoryFilter} onValueChange={(v) => { setCategoryFilter(v); setCurrentPage(1); }}>
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="Category" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Categories</SelectItem>
              {categories.map((cat) => (
                <SelectItem key={cat} value={cat}>{cat}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v); setCurrentPage(1); }}>
          <SelectTrigger className="w-[150px]">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Status</SelectItem>
            <SelectItem value="verified">Verified</SelectItem>
            <SelectItem value="failing">Failing</SelectItem>
            <SelectItem value="pending">Pending</SelectItem>
          </SelectContent>
        </Select>

        <Select value={String(pageSize)} onValueChange={(v) => { setPageSize(Number(v)); setCurrentPage(1); }}>
          <SelectTrigger className="w-[80px]">
            <SelectValue placeholder="25" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="10">10</SelectItem>
            <SelectItem value="25">25</SelectItem>
            <SelectItem value="50">50</SelectItem>
            <SelectItem value="100">100</SelectItem>
          </SelectContent>
        </Select>

        <Button onClick={() => setCreateDialogOpen(true)}>
          <Plus className="w-4 h-4 mr-1.5" />
          Create Feature
        </Button>
      </div>

      {/* Results count */}
      <div className="text-sm text-slate-500">
        {totalFiltered > 0
          ? `Showing ${startIndex + 1}–${endIndex} of ${totalFiltered} features`
          : "No features match your filters"}
      </div>

      {/* Table */}
      {paginatedFeatures.length > 0 ? (
        <div className="rounded-lg border border-slate-700 overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="border-slate-700 hover:bg-transparent">
                <TableHead
                  className="w-24 cursor-pointer select-none hover:text-phosphor-400"
                  onClick={() => handleSort("feature_id")}
                >
                  <div className="flex items-center">ID{getSortIcon("feature_id")}</div>
                </TableHead>
                <TableHead
                  className="w-12 text-center cursor-pointer select-none hover:text-phosphor-400"
                  onClick={() => handleSort("priority")}
                >
                  <div className="flex items-center justify-center">P{getSortIcon("priority")}</div>
                </TableHead>
                <TableHead
                  className="cursor-pointer select-none hover:text-phosphor-400"
                  onClick={() => handleSort("name")}
                >
                  <div className="flex items-center">Name{getSortIcon("name")}</div>
                </TableHead>
                <TableHead
                  className="w-28 cursor-pointer select-none hover:text-phosphor-400"
                  onClick={() => handleSort("category")}
                >
                  <div className="flex items-center">Category{getSortIcon("category")}</div>
                </TableHead>
                <TableHead
                  className="w-16 text-center cursor-pointer select-none hover:text-phosphor-400"
                  onClick={() => handleSort("criteria")}
                >
                  <div className="flex items-center justify-center">AC{getSortIcon("criteria")}</div>
                </TableHead>
                <TableHead
                  className="w-28 cursor-pointer select-none hover:text-phosphor-400"
                  onClick={() => handleSort("verified")}
                >
                  <div className="flex items-center">Status{getSortIcon("verified")}</div>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {paginatedFeatures.map((feature) => {
                const isExpanded = expandedRows.has(feature.feature_id);
                const hasCriteria = feature.acceptance_criteria?.length > 0;

                return (
                  <Fragment key={feature.feature_id}>
                    <TableRow
                      className={`border-slate-800 ${hasCriteria ? "cursor-pointer hover:bg-slate-850/50" : ""}`}
                      onClick={() => hasCriteria && toggleRow(feature.feature_id)}
                    >
                      <TableCell className="mono text-xs py-2">
                        <div className="flex items-center gap-1">
                          {hasCriteria && (
                            isExpanded
                              ? <ChevronDown className="h-4 w-4 text-slate-500" />
                              : <ChevronRight className="h-4 w-4 text-slate-500" />
                          )}
                          <span className={`${getVerificationStatus(feature) === "verified" ? "text-phosphor-400" : getVerificationStatus(feature) === "needs-review" ? "text-amber-400" : "text-slate-300"}`}>
                            {feature.feature_id}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="py-2 text-center">
                        {renderPriorityBadge(feature.priority, feature.effective_priority)}
                      </TableCell>
                      <TableCell className="py-2 font-medium text-white">
                        {feature.name}
                      </TableCell>
                      <TableCell className="py-2">
                        {feature.category && (
                          <span className="text-xs px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-300 border border-slate-600">
                            {feature.category}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="py-2 text-center">
                        {renderCriteriaStatus(feature.acceptance_criteria)}
                      </TableCell>
                      <TableCell className="py-2">
                        {renderStatusBadge(feature)}
                      </TableCell>
                    </TableRow>

                    {/* Expanded row - Acceptance Criteria */}
                    {isExpanded && hasCriteria && (
                      <TableRow className="bg-slate-900/80 border-slate-800">
                        <TableCell colSpan={6} className="py-3 px-6">
                          <div className="space-y-2">
                            <div className="text-xs text-slate-500 mb-2">
                              Acceptance Criteria ({feature.acceptance_criteria.filter(c => c.passed).length}/{feature.acceptance_criteria.length} verified)
                            </div>
                            {feature.acceptance_criteria.map((criterion) => (
                              <div
                                key={criterion.id}
                                className="flex items-start gap-3 py-2 border-b border-slate-800 last:border-0"
                                onClick={(e) => e.stopPropagation()}
                              >
                                <span className="shrink-0 mt-0.5">
                                  {criterion.passed === true ? (
                                    <CheckCircle2 className="h-4 w-4 text-phosphor-400" />
                                  ) : criterion.passed === false ? (
                                    <XCircle className="h-4 w-4 text-rose-400" />
                                  ) : (
                                    <HelpCircle className="h-4 w-4 text-amber-400" />
                                  )}
                                </span>
                                <span className="mono text-xs text-slate-500 shrink-0 min-w-[50px]">
                                  {criterion.id}
                                </span>
                                <span className="text-xs px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 border border-blue-500/30 shrink-0">
                                  {criterion.type}
                                </span>
                                {criterion.type === "ui" && (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-5 px-1.5 text-xs shrink-0"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setEvidenceModal({
                                        open: true,
                                        featureId: feature.feature_id,
                                        criterionId: criterion.id,
                                        criterionText: criterion.criterion,
                                        verificationUrl: parseVerificationUrl(criterion.verification || ""),
                                      });
                                    }}
                                  >
                                    <Eye className="h-3 w-3 mr-1" />
                                    Evidence
                                  </Button>
                                )}
                                <span className="flex-1 text-sm text-slate-300">
                                  {criterion.criterion}
                                </span>
                              </div>
                            ))}
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        </div>
      ) : (
        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-8 text-center">
          <HelpCircle className="mx-auto h-12 w-12 text-slate-600" />
          <p className="mt-4 text-sm text-slate-500">No features found.</p>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-2">
          <div className="text-sm text-slate-500">Page {currentPage} of {totalPages}</div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={currentPage === 1}
            >
              <ChevronLeft className="h-4 w-4 mr-1" />
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              disabled={currentPage === totalPages}
            >
              Next
              <ChevronRight className="h-4 w-4 ml-1" />
            </Button>
          </div>
        </div>
      )}

      {/* Create Feature Dialog */}
      <CreateFeatureDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
        projectId={projectId}
      />

      {/* Evidence Modal */}
      <EvidenceViewerModal
        open={evidenceModal.open}
        onOpenChange={(open) => setEvidenceModal((prev) => ({ ...prev, open }))}
        projectId={projectId}
        featureId={evidenceModal.featureId}
        criterionId={evidenceModal.criterionId}
        criterionText={evidenceModal.criterionText}
        verificationUrl={evidenceModal.verificationUrl}
      />
    </div>
  );
}
