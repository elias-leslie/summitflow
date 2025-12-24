"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Image as ImageIcon,
  Calendar,
  Filter,
  Search,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  ChevronLeft,
  ChevronRight,
  Loader2,
  FileJson,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EvidenceViewerModal } from "./EvidenceViewerModal";

interface EvidenceItem {
  id: number;
  evidenceId: string;
  capabilityId: string;
  criterionId: string;
  version: number;
  isCurrent: boolean;
  capturedAt: string;
  expiresAt: string | null;
  qualityStatus: string;
  confidence: number | null;
  userApproved: boolean | null;
  userNotes: string | null;
  fileSizeBytes: number | null;
  screenshotUrl: string;
}

interface EvidenceListResponse {
  evidence: EvidenceItem[];
  total: number;
  limit: number;
  offset: number;
}

interface EvidenceGalleryProps {
  projectId: string;
}

async function fetchEvidenceList(
  projectId: string,
  params: {
    limit: number;
    offset: number;
    capabilityId?: string;
    status?: string;
    search?: string;
  }
): Promise<EvidenceListResponse> {
  const searchParams = new URLSearchParams({
    limit: params.limit.toString(),
    offset: params.offset.toString(),
  });
  if (params.capabilityId) searchParams.set("capability_id", params.capabilityId);
  if (params.status) searchParams.set("status", params.status);
  if (params.search) searchParams.set("search", params.search);

  const res = await fetch(
    `/api/projects/${projectId}/evidence?${searchParams.toString()}`
  );
  if (!res.ok) throw new Error("Failed to fetch evidence");
  return res.json();
}

export function EvidenceGallery({ projectId }: EvidenceGalleryProps) {
  const [page, setPage] = useState(0);
  const [featureFilter, setFeatureFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceItem | null>(null);
  const pageSize = 12;

  // Fetch evidence with filters
  const { data, isLoading, error } = useQuery<EvidenceListResponse>({
    queryKey: [
      "evidence-list",
      projectId,
      page,
      featureFilter,
      statusFilter,
      searchQuery,
    ],
    queryFn: () =>
      fetchEvidenceList(projectId, {
        limit: pageSize,
        offset: page * pageSize,
        capabilityId: featureFilter !== "all" ? featureFilter : undefined,
        status: statusFilter !== "all" ? statusFilter : undefined,
        search: searchQuery || undefined,
      }),
  });

  // Get unique feature IDs for filter dropdown
  const capabilityIds = useMemo(() => {
    if (!data?.evidence) return [];
    const ids = new Set(data.evidence.map((e) => e.capabilityId));
    return Array.from(ids).sort();
  }, [data]);

  const totalPages = data ? Math.ceil(data.total / pageSize) : 0;

  const getStatusBadge = (status: string, userApproved: boolean | null) => {
    if (userApproved === true) {
      return (
        <Badge variant="phosphor" className="gap-1">
          <CheckCircle2 className="h-3 w-3" />
          Approved
        </Badge>
      );
    }
    if (userApproved === false) {
      return (
        <Badge variant="rose" className="gap-1">
          <XCircle className="h-3 w-3" />
          Rejected
        </Badge>
      );
    }
    switch (status) {
      case "passed":
        return (
          <Badge variant="phosphor" className="gap-1">
            <CheckCircle2 className="h-3 w-3" />
            Passed
          </Badge>
        );
      case "failed":
        return (
          <Badge variant="rose" className="gap-1">
            <XCircle className="h-3 w-3" />
            Failed
          </Badge>
        );
      case "needs_review":
        return (
          <Badge variant="amber" className="gap-1">
            <AlertTriangle className="h-3 w-3" />
            Needs Review
          </Badge>
        );
      default:
        return (
          <Badge variant="default" className="gap-1">
            <Clock className="h-3 w-3" />
            Pending
          </Badge>
        );
    }
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const formatFileSize = (bytes: number | null) => {
    if (!bytes) return "—";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="h-full flex flex-col">
      {/* Filters */}
      <div className="flex items-center gap-4 p-4 border-b border-slate-700 bg-slate-900/50">
        <div className="flex items-center gap-2 flex-1">
          <Filter className="h-4 w-4 text-slate-500" />
          <span className="text-sm text-slate-400">Filters:</span>

          {/* Feature filter */}
          <Select value={featureFilter} onValueChange={setFeatureFilter}>
            <SelectTrigger className="w-40 h-8 text-xs">
              <SelectValue placeholder="All Features" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Features</SelectItem>
              {capabilityIds.map((id) => (
                <SelectItem key={id} value={id}>
                  {id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Status filter */}
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-36 h-8 text-xs">
              <SelectValue placeholder="All Statuses" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Statuses</SelectItem>
              <SelectItem value="passed">Passed</SelectItem>
              <SelectItem value="failed">Failed</SelectItem>
              <SelectItem value="needs_review">Needs Review</SelectItem>
              <SelectItem value="pending">Pending</SelectItem>
            </SelectContent>
          </Select>

          {/* Search */}
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search..."
              className="pl-8 h-8 w-48 text-xs"
            />
          </div>
        </div>

        {/* Stats */}
        {data && (
          <div className="text-sm text-slate-400">
            {data.total} evidence capture{data.total !== 1 && "s"}
          </div>
        )}
      </div>

      {/* Gallery content */}
      <div className="flex-1 overflow-auto p-4">
        {isLoading ? (
          <div className="flex items-center justify-center h-64">
            <Loader2 className="h-8 w-8 animate-spin text-phosphor-400" />
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center h-64 text-slate-400">
            <AlertTriangle className="h-12 w-12 text-amber-400 mb-4" />
            <p>Failed to load evidence</p>
          </div>
        ) : data?.evidence.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-slate-400">
            <ImageIcon className="h-12 w-12 text-slate-600 mb-4" />
            <p>No evidence captured yet</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {data?.evidence.map((item) => (
              <button
                key={item.evidenceId}
                onClick={() => setSelectedEvidence(item)}
                className="group text-left rounded-lg border border-slate-700 bg-slate-800/30 overflow-hidden hover:border-phosphor-500/50 transition-colors"
              >
                {/* Thumbnail */}
                <div className="relative aspect-video bg-slate-900 overflow-hidden">
                  <img
                    src={item.screenshotUrl}
                    alt={`${item.capabilityId} / ${item.criterionId}`}
                    className="w-full h-full object-cover object-top group-hover:scale-105 transition-transform duration-300"
                  />
                  {item.version > 1 && (
                    <div className="absolute top-2 right-2">
                      <Badge variant="default" className="text-xs">
                        v{item.version}
                      </Badge>
                    </div>
                  )}
                </div>

                {/* Info */}
                <div className="p-3 space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 min-w-0">
                      <FileJson className="h-4 w-4 text-slate-500 shrink-0" />
                      <span className="mono text-sm text-phosphor-400 truncate">
                        {item.capabilityId}
                      </span>
                    </div>
                    {getStatusBadge(item.qualityStatus, item.userApproved)}
                  </div>

                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    <span className="mono">{item.criterionId}</span>
                    <span className="text-slate-600">•</span>
                    <span>{formatFileSize(item.fileSizeBytes)}</span>
                  </div>

                  <div className="flex items-center gap-1 text-xs text-slate-500">
                    <Calendar className="h-3.5 w-3.5" />
                    <span>{formatDate(item.capturedAt)}</span>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 p-4 border-t border-slate-700 bg-slate-900/50">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={page === 0}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="text-sm text-slate-400">
            Page {page + 1} of {totalPages}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={page >= totalPages - 1}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}

      {/* Evidence Viewer Modal */}
      {selectedEvidence && (
        <EvidenceViewerModal
          open={!!selectedEvidence}
          onOpenChange={(open) => !open && setSelectedEvidence(null)}
          projectId={projectId}
          capabilityId={selectedEvidence.capabilityId}
          criterionId={selectedEvidence.criterionId}
        />
      )}
    </div>
  );
}
