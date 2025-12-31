"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Image from "next/image";
import {
  Grid3X3,
  List,
  Loader2,
  Search,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  Camera,
  FileQuestion,
  Bot,
  TestTube,
} from "lucide-react";
import { EvidenceViewerModal } from "./EvidenceViewerModal";

interface EvidenceTabProps {
  projectId: string;
}

interface Evidence {
  id: number;
  evidenceId: string;
  capabilityId: string;
  criterionId: string;
  version: number;
  isCurrent: boolean;
  capturedAt: string;
  qualityStatus: string;
  confidence: number | null;
  userApproved: boolean | null;
  userNotes: string | null;
  fileSizeBytes: number | null;
  screenshotUrl: string;
  // New fields for criteria linkage
  criterionDbId: number | null;
  testRunId: number | null;
  autoCaptured: boolean;
}

interface EvidenceSummary {
  total_current: number;
  by_status: Record<string, number>;
  auto_captured_count: number;
  with_user_notes: number;
  total_storage_bytes: number;
}

type ViewMode = "grid" | "list";

export function EvidenceTab({ projectId }: EvidenceTabProps) {
  const [viewMode, setViewMode] = useState<ViewMode>("grid");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [page, setPage] = useState(0);
  const pageSize = 50;

  // Modal state
  const [selectedEvidence, setSelectedEvidence] = useState<Evidence | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  // Queries
  const { data: evidenceData, isLoading: evidenceLoading } = useQuery({
    queryKey: ["evidence", projectId, statusFilter, searchQuery, page],
    queryFn: async () => {
      const params = new URLSearchParams({
        limit: String(pageSize),
        offset: String(page * pageSize),
      });
      if (statusFilter !== "all") params.set("status", statusFilter);
      if (searchQuery.trim()) params.set("search", searchQuery.trim());

      const response = await fetch(`/api/projects/${projectId}/evidence?${params}`);
      if (!response.ok) throw new Error("Failed to fetch evidence");
      return response.json() as Promise<{
        evidence: Evidence[];
        total: number;
        limit: number;
        offset: number;
      }>;
    },
    refetchInterval: 60000,
  });

  const { data: summary } = useQuery({
    queryKey: ["evidence", projectId, "summary"],
    queryFn: async () => {
      const response = await fetch(`/api/projects/${projectId}/evidence/summary`);
      if (!response.ok) throw new Error("Failed to fetch summary");
      return response.json() as Promise<EvidenceSummary>;
    },
    refetchInterval: 60000,
  });

  const handleEvidenceClick = (evidence: Evidence) => {
    setSelectedEvidence(evidence);
    setModalOpen(true);
  };

  // Status badge component
  const StatusBadge = ({ status }: { status: string }) => {
    const base = "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium";
    switch (status) {
      case "passed":
        return (
          <span className={`${base} bg-green-500/20 text-green-400`}>
            <CheckCircle2 className="w-3 h-3" />
            Passed
          </span>
        );
      case "failed":
        return (
          <span className={`${base} bg-red-500/20 text-red-400`}>
            <XCircle className="w-3 h-3" />
            Failed
          </span>
        );
      case "needs_review":
        return (
          <span className={`${base} bg-yellow-500/20 text-yellow-400`}>
            <AlertTriangle className="w-3 h-3" />
            Review
          </span>
        );
      case "pending":
        return (
          <span className={`${base} bg-blue-500/20 text-blue-400`}>
            <Clock className="w-3 h-3" />
            Pending
          </span>
        );
      case "migrated":
        return (
          <span className={`${base} bg-slate-500/20 text-slate-400`}>
            <FileQuestion className="w-3 h-3" />
            Migrated
          </span>
        );
      default:
        return (
          <span className={`${base} bg-slate-500/20 text-slate-400`}>
            {status}
          </span>
        );
    }
  };

  // Format date relative
  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    if (diffHours < 1) return "Just now";
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  };

  return (
    <div className="space-y-4">
      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div className="card p-4">
          <div className="text-xs text-slate-400">Total</div>
          <div className="text-2xl font-bold text-white tabular-nums">{summary?.total_current || 0}</div>
        </div>
        <div className="card p-4">
          <div className="flex items-center gap-1">
            <CheckCircle2 className="w-3 h-3 text-green-500" />
            <span className="text-xs text-slate-400">Passed</span>
          </div>
          <div className="text-2xl font-bold text-green-500 tabular-nums">
            {summary?.by_status?.passed || 0}
          </div>
        </div>
        <div className="card p-4">
          <div className="flex items-center gap-1">
            <XCircle className="w-3 h-3 text-red-500" />
            <span className="text-xs text-slate-400">Failed</span>
          </div>
          <div className="text-2xl font-bold text-red-500 tabular-nums">
            {summary?.by_status?.failed || 0}
          </div>
        </div>
        <div className="card p-4">
          <div className="flex items-center gap-1">
            <AlertTriangle className="w-3 h-3 text-yellow-500" />
            <span className="text-xs text-slate-400">Review</span>
          </div>
          <div className="text-2xl font-bold text-yellow-500 tabular-nums">
            {summary?.by_status?.needs_review || 0}
          </div>
        </div>
        <div className="card p-4">
          <div className="flex items-center gap-1">
            <Clock className="w-3 h-3 text-blue-400" />
            <span className="text-xs text-slate-400">Pending</span>
          </div>
          <div className="text-2xl font-bold text-blue-400 tabular-nums">
            {summary?.by_status?.pending || 0}
          </div>
        </div>
      </div>

      {/* Controls */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* View toggle */}
        <div className="flex rounded-lg overflow-hidden border border-slate-700">
          <button
            onClick={() => setViewMode("grid")}
            className={`px-3 py-1.5 text-xs font-medium flex items-center gap-1.5 transition-colors ${
              viewMode === "grid"
                ? "bg-phosphor-500/20 text-phosphor-400"
                : "text-slate-400 hover:text-white"
            }`}
          >
            <Grid3X3 className="w-3.5 h-3.5" />
            Grid
          </button>
          <button
            onClick={() => setViewMode("list")}
            className={`px-3 py-1.5 text-xs font-medium flex items-center gap-1.5 transition-colors ${
              viewMode === "list"
                ? "bg-phosphor-500/20 text-phosphor-400"
                : "text-slate-400 hover:text-white"
            }`}
          >
            <List className="w-3.5 h-3.5" />
            List
          </button>
        </div>

        {/* Status filter */}
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-phosphor-500"
        >
          <option value="all">All Status</option>
          <option value="passed">Passed</option>
          <option value="failed">Failed</option>
          <option value="needs_review">Needs Review</option>
          <option value="pending">Pending</option>
          <option value="migrated">Migrated</option>
        </select>

        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-[300px]">
          <Search className="absolute left-2.5 top-1/2 w-3.5 h-3.5 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            placeholder="Search capability/criterion..."
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setPage(0);
            }}
            className="w-full bg-slate-800 border border-slate-700 rounded-lg pl-8 pr-3 py-1.5 text-xs text-slate-300 placeholder-slate-500 focus:outline-none focus:border-phosphor-500"
          />
        </div>

        <div className="flex-1" />

        {/* Result count */}
        <span className="text-xs text-slate-500">
          {evidenceData?.total || 0} items
        </span>
      </div>

      {/* Content */}
      {evidenceLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-slate-600" />
        </div>
      ) : !evidenceData?.evidence.length ? (
        <div className="card p-12 text-center">
          <Camera className="w-12 h-12 mx-auto text-slate-600 mb-4" />
          <p className="text-slate-400">No evidence found</p>
          <p className="text-xs text-slate-500 mt-1">
            {searchQuery
              ? "Try adjusting your search"
              : "Evidence is captured when verifying capabilities"}
          </p>
        </div>
      ) : viewMode === "grid" ? (
        /* Grid View */
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
          {evidenceData.evidence.map((evidence) => (
            <div
              key={evidence.id}
              onClick={() => handleEvidenceClick(evidence)}
              className="card overflow-hidden cursor-pointer hover:border-phosphor-500/50 transition-colors group"
            >
              {/* Thumbnail */}
              <div className="aspect-video bg-slate-800 relative overflow-hidden">
                <Image
                  src={evidence.screenshotUrl}
                  alt={`${evidence.capabilityId} ${evidence.criterionId} evidence screenshot`}
                  fill
                  className="object-cover object-top group-hover:scale-105 transition-transform"
                  unoptimized
                  onError={(e) => {
                    e.currentTarget.style.display = "none";
                  }}
                />
                <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
              </div>
              {/* Info */}
              <div className="p-2 space-y-1">
                <div className="flex items-center justify-between gap-1">
                  <span className="text-xs font-mono text-white truncate">
                    {evidence.capabilityId}
                  </span>
                  <StatusBadge status={evidence.qualityStatus} />
                </div>
                <div className="flex items-center justify-between text-2xs text-slate-500">
                  <span>{evidence.criterionId}</span>
                  <span>v{evidence.version}</span>
                </div>
                <div className="flex items-center justify-between text-2xs text-slate-500">
                  <span>{formatDate(evidence.capturedAt)}</span>
                  {evidence.autoCaptured && (
                    <span className="flex items-center gap-0.5 text-purple-400" title="Auto-captured on test pass">
                      <Bot className="w-3 h-3" />
                    </span>
                  )}
                  {evidence.testRunId && !evidence.autoCaptured && (
                    <span className="flex items-center gap-0.5 text-cyan-400" title={`Test run #${evidence.testRunId}`}>
                      <TestTube className="w-3 h-3" />
                    </span>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* List View */
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-800/50 border-b border-slate-700">
              <tr>
                <th className="text-left px-3 py-2 font-medium text-slate-400 text-xs">
                  Capability
                </th>
                <th className="text-left px-3 py-2 font-medium text-slate-400 text-xs">
                  Criterion
                </th>
                <th className="text-left px-3 py-2 font-medium text-slate-400 text-xs">
                  Status
                </th>
                <th className="text-left px-3 py-2 font-medium text-slate-400 text-xs">
                  Version
                </th>
                <th className="text-left px-3 py-2 font-medium text-slate-400 text-xs">
                  Captured
                </th>
                <th className="text-left px-3 py-2 font-medium text-slate-400 text-xs">
                  Source
                </th>
                <th className="text-left px-3 py-2 font-medium text-slate-400 text-xs">
                  User
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {evidenceData.evidence.map((evidence) => (
                <tr
                  key={evidence.id}
                  onClick={() => handleEvidenceClick(evidence)}
                  className="hover:bg-slate-800/30 cursor-pointer transition-colors"
                >
                  <td className="px-3 py-2 font-mono text-xs text-white">
                    {evidence.capabilityId}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-slate-400">
                    {evidence.criterionId}
                  </td>
                  <td className="px-3 py-2">
                    <StatusBadge status={evidence.qualityStatus} />
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-400">v{evidence.version}</td>
                  <td className="px-3 py-2 text-xs text-slate-500">
                    {formatDate(evidence.capturedAt)}
                  </td>
                  <td className="px-3 py-2">
                    {evidence.autoCaptured ? (
                      <span className="inline-flex items-center gap-1 text-xs text-purple-400" title="Auto-captured on test pass">
                        <Bot className="w-3 h-3" />
                        Auto
                      </span>
                    ) : evidence.testRunId ? (
                      <span className="inline-flex items-center gap-1 text-xs text-cyan-400" title={`Test run #${evidence.testRunId}`}>
                        <TestTube className="w-3 h-3" />
                        Test
                      </span>
                    ) : (
                      <span className="text-xs text-slate-500">Manual</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {evidence.userApproved === true && (
                      <CheckCircle2 className="w-4 h-4 text-green-500" />
                    )}
                    {evidence.userApproved === false && (
                      <XCircle className="w-4 h-4 text-red-500" />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {evidenceData && evidenceData.total > pageSize && (
        <div className="flex items-center justify-between pt-2">
          <span className="text-xs text-slate-500">
            Showing {page * pageSize + 1} -{" "}
            {Math.min((page + 1) * pageSize, evidenceData.total)} of{" "}
            {evidenceData.total}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage(page - 1)}
              disabled={page === 0}
              className="px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-700 text-slate-400 hover:text-white hover:border-slate-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Previous
            </button>
            <button
              onClick={() => setPage(page + 1)}
              disabled={(page + 1) * pageSize >= evidenceData.total}
              className="px-3 py-1.5 text-xs font-medium rounded-lg border border-slate-700 text-slate-400 hover:text-white hover:border-slate-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {/* Evidence Viewer Modal */}
      {selectedEvidence && (
        <EvidenceViewerModal
          open={modalOpen}
          onOpenChange={setModalOpen}
          projectId={projectId}
          capabilityId={selectedEvidence.capabilityId}
          criterionId={selectedEvidence.criterionId}
        />
      )}
    </div>
  );
}
