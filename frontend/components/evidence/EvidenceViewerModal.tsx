"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "motion/react";
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  Image as ImageIcon,
  Terminal,
  Network,
  FileJson,
  Loader2,
  ExternalLink,
  X,
} from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import {
  fetchEvidence,
  refreshEvidence,
  submitEvidenceReview,
  getScreenshotUrl,
  type ArtifactResponse,
} from "@/lib/api";

interface EvidenceViewerModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  featureId: string;
  criterionId: string;
  criterionText?: string;
  verificationUrl?: string;
}

export function EvidenceViewerModal({
  open,
  onOpenChange,
  projectId,
  featureId,
  criterionId,
  criterionText,
  verificationUrl,
}: EvidenceViewerModalProps) {
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [userNotes, setUserNotes] = useState("");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [activeTab, setActiveTab] = useState("screenshot");
  const queryClient = useQueryClient();

  // Fetch evidence data
  const { data, isLoading, error, refetch } = useQuery<ArtifactResponse>({
    queryKey: ["evidence", projectId, featureId, criterionId, selectedVersion],
    queryFn: () => fetchEvidence(projectId, featureId, criterionId, selectedVersion ?? undefined),
    enabled: open && !!projectId && !!featureId && !!criterionId,
    staleTime: 0,
    refetchOnMount: true,
    retry: 1,
  });

  // Set initial version from data
  useEffect(() => {
    if (data?.artifact && !selectedVersion) {
      setSelectedVersion(data.artifact.version);
    }
  }, [data, selectedVersion]);

  // Reset state when modal closes
  useEffect(() => {
    if (!open) {
      setSelectedVersion(null);
      setUserNotes("");
      setActiveTab("screenshot");
    }
  }, [open]);

  // Submit review mutation
  const reviewMutation = useMutation({
    mutationFn: async ({ approved, notes }: { approved: boolean | null; notes: string }) => {
      if (!data?.artifact) throw new Error("No artifact");
      return submitEvidenceReview(projectId, data.artifact.artifactId, approved, notes);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["evidence", projectId, featureId, criterionId],
      });
    },
  });

  // Navigate versions
  const handlePrevVersion = () => {
    if (data?.versions && selectedVersion) {
      const currentIdx = data.versions.findIndex((v) => v.version === selectedVersion);
      if (currentIdx < data.versions.length - 1) {
        setSelectedVersion(data.versions[currentIdx + 1].version);
      }
    }
  };

  const handleNextVersion = () => {
    if (data?.versions && selectedVersion) {
      const currentIdx = data.versions.findIndex((v) => v.version === selectedVersion);
      if (currentIdx > 0) {
        setSelectedVersion(data.versions[currentIdx - 1].version);
      }
    }
  };

  // Refresh evidence
  const handleRefresh = async () => {
    const captureUrl = data?.evidence?.metadata.url || verificationUrl;
    if (!captureUrl) return;

    setIsRefreshing(true);
    try {
      const result = await refreshEvidence(projectId, featureId, criterionId, captureUrl);
      if (result.success && result.version) {
        setSelectedVersion(result.version);
        await queryClient.invalidateQueries({
          queryKey: ["evidence", projectId, featureId, criterionId],
        });
        refetch();
      }
    } finally {
      setIsRefreshing(false);
    }
  };

  const evidence = data?.evidence;
  const artifact = data?.artifact;
  const versions = data?.versions || [];

  const getStatusBadgeVariant = (status: string) => {
    if (status === "passed") return "phosphor";
    if (status === "failed") return "rose";
    return "amber";
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!max-w-[95vw] w-fit min-w-[50vw] h-[95vh] flex flex-col p-0 gap-0 overflow-hidden">
        {/* Header */}
        <DialogHeader className="px-5 py-4 border-b border-slate-700 shrink-0 relative">
          <button
            onClick={() => onOpenChange(false)}
            className="absolute right-4 top-4 p-1.5 rounded-md text-slate-500 hover:text-phosphor-400 hover:bg-slate-800 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
          <DialogTitle className="flex items-center gap-3">
            <span className="mono text-phosphor-400">{featureId}</span>
            <span className="text-slate-600">/</span>
            <span className="mono text-slate-300">{criterionId}</span>
            {artifact && (
              <Badge variant={getStatusBadgeVariant(artifact.qualityStatus)}>
                {artifact.qualityStatus}
              </Badge>
            )}
          </DialogTitle>
          {criterionText && (
            <DialogDescription>{criterionText}</DialogDescription>
          )}
        </DialogHeader>

        {/* Content */}
        {isLoading ? (
          <div className="flex items-center justify-center py-12 flex-1">
            <div className="w-8 h-8 border-2 border-phosphor-500/30 border-t-phosphor-500 rounded-full animate-spin" />
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center py-12 gap-4 flex-1">
            <AlertTriangle className="h-12 w-12 text-amber-400" />
            <p className="text-sm text-slate-400">
              {error instanceof Error ? error.message : "Failed to load evidence"}
            </p>
            <Button variant="primary" onClick={handleRefresh} disabled={isRefreshing}>
              {isRefreshing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
              Capture Evidence
            </Button>
          </div>
        ) : evidence ? (
          <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
            {/* Version navigation */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-slate-800 bg-slate-900/50 shrink-0">
              <div className="flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handlePrevVersion}
                  disabled={!versions.length || selectedVersion === versions[versions.length - 1]?.version}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <span className="mono text-sm text-slate-400">
                  v{selectedVersion} / {versions.length}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleNextVersion}
                  disabled={!versions.length || selectedVersion === versions[0]?.version}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
                <span className="text-xs text-slate-600 ml-2">
                  {artifact?.capturedAt && new Date(artifact.capturedAt).toLocaleString()}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" onClick={handleRefresh} disabled={isRefreshing}>
                  {isRefreshing ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCw className="h-4 w-4" />
                  )}
                  Refresh
                </Button>
                <a
                  href={evidence.metadata.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-transparent text-slate-300 border border-slate-600 hover:border-phosphor-500/50 hover:text-phosphor-400 transition-all"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  Open Page
                </a>
              </div>
            </div>

            {/* Tabs */}
            <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col min-h-0 overflow-hidden">
              <div className="px-4 border-b border-slate-800 shrink-0">
                <TabsList className="gap-1 bg-transparent">
                  <TabsTrigger value="screenshot" className="gap-1.5">
                    <ImageIcon className="h-4 w-4" />
                    Screenshot
                  </TabsTrigger>
                  <TabsTrigger value="console" className="gap-1.5">
                    <Terminal className="h-4 w-4" />
                    Console
                    {evidence.console.errorCount > 0 && (
                      <Badge variant="rose" className="ml-1 h-5 px-1.5">
                        {evidence.console.errorCount}
                      </Badge>
                    )}
                  </TabsTrigger>
                  <TabsTrigger value="network" className="gap-1.5">
                    <Network className="h-4 w-4" />
                    Network
                    {evidence.network.failedRequests > 0 && (
                      <Badge variant="rose" className="ml-1 h-5 px-1.5">
                        {evidence.network.failedRequests}
                      </Badge>
                    )}
                  </TabsTrigger>
                  <TabsTrigger value="page" className="gap-1.5">
                    <FileJson className="h-4 w-4" />
                    Page State
                  </TabsTrigger>
                </TabsList>
              </div>

              <div className="flex-1 overflow-hidden relative bg-slate-950/50">
                <TabsContent value="screenshot" className="absolute inset-0 overflow-auto p-4">
                  <img
                    src={getScreenshotUrl(projectId, featureId, criterionId, artifact?.version ?? 1)}
                    alt="Page screenshot"
                    className="border border-slate-700 rounded shadow-lg"
                  />
                </TabsContent>

                <TabsContent value="console" className="absolute inset-0 overflow-auto p-4">
                  <div className="space-y-4 max-w-4xl mx-auto">
                    <div className="flex gap-4 text-sm font-medium">
                      <span className="text-rose-400 flex items-center gap-1">
                        <XCircle className="h-4 w-4" />
                        {evidence.console.errorCount} errors
                      </span>
                      <span className="text-amber-400 flex items-center gap-1">
                        <AlertTriangle className="h-4 w-4" />
                        {evidence.console.warningCount} warnings
                      </span>
                    </div>

                    {(evidence.console.errors?.length ?? 0) > 0 && (
                      <div className="space-y-2">
                        <h4 className="text-sm font-medium border-b border-slate-800 pb-1 text-slate-300">Errors</h4>
                        {evidence.console.errors.map((err, i) => (
                          <div key={i} className="rounded bg-rose-500/5 border border-rose-500/20 p-3">
                            <p className="text-sm text-rose-400 mono break-all whitespace-pre-wrap">
                              {err.text}
                            </p>
                            {err.source && (
                              <p className="text-xs text-slate-500 mt-1 border-t border-rose-500/10 pt-1">
                                {err.source}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    )}

                    {(evidence.console.warnings?.length ?? 0) > 0 && (
                      <div className="space-y-2">
                        <h4 className="text-sm font-medium border-b border-slate-800 pb-1 text-slate-300">Warnings</h4>
                        {evidence.console.warnings.map((warn, i) => (
                          <div key={i} className="rounded bg-amber-500/5 border border-amber-500/20 p-3">
                            <p className="text-sm text-amber-400 mono break-all whitespace-pre-wrap">
                              {warn.text}
                            </p>
                            {warn.source && (
                              <p className="text-xs text-slate-500 mt-1 border-t border-amber-500/10 pt-1">
                                {warn.source}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    )}

                    {(evidence.console.errors?.length ?? 0) === 0 && (evidence.console.warnings?.length ?? 0) === 0 && (
                      <div className="text-center py-12 text-slate-500">
                        <CheckCircle2 className="h-12 w-12 mx-auto mb-2 text-phosphor-500/30" />
                        <p>No console errors or warnings captured.</p>
                      </div>
                    )}
                  </div>
                </TabsContent>

                <TabsContent value="network" className="absolute inset-0 overflow-auto p-4">
                  <div className="space-y-6 max-w-4xl mx-auto">
                    <div className="grid grid-cols-3 gap-4">
                      <div className="p-4 rounded border border-slate-700 bg-slate-900/50">
                        <div className="text-2xl font-bold mono text-white">{evidence.network.totalRequests}</div>
                        <div className="text-sm text-slate-500">Total Requests</div>
                      </div>
                      <div className="p-4 rounded border border-slate-700 bg-slate-900/50">
                        <div className="text-2xl font-bold mono text-rose-400">{evidence.network.failedRequests}</div>
                        <div className="text-sm text-slate-500">Failed</div>
                      </div>
                      <div className="p-4 rounded border border-slate-700 bg-slate-900/50">
                        <div className="text-2xl font-bold mono text-amber-400">{evidence.network.slowRequests?.length ?? 0}</div>
                        <div className="text-sm text-slate-500">Slow ({">"}3s)</div>
                      </div>
                    </div>

                    {(evidence.network.failures?.length ?? 0) > 0 && (
                      <div className="space-y-2">
                        <h4 className="text-sm font-medium border-b border-slate-800 pb-1 text-slate-300">Failed Requests</h4>
                        {evidence.network.failures.map((fail, i) => (
                          <div key={i} className="rounded bg-rose-500/5 border border-rose-500/20 p-3">
                            <div className="flex items-start gap-2">
                              <Badge variant="rose" className="mt-0.5">{fail.status}</Badge>
                              <p className="text-sm mono break-all flex-1 text-slate-300">{fail.url}</p>
                            </div>
                            {fail.error && (
                              <p className="text-xs text-rose-300 mt-2 pl-12">Error: {fail.error}</p>
                            )}
                          </div>
                        ))}
                      </div>
                    )}

                    {(evidence.network.slowRequests?.length ?? 0) > 0 && (
                      <div className="space-y-2">
                        <h4 className="text-sm font-medium border-b border-slate-800 pb-1 text-slate-300">Slow Requests</h4>
                        {evidence.network.slowRequests.map((req, i) => (
                          <div key={i} className="rounded bg-amber-500/5 border border-amber-500/20 p-3 flex justify-between gap-4">
                            <p className="text-sm mono break-all flex-1 text-slate-300">{req.url}</p>
                            <span className="text-sm text-amber-400 mono whitespace-nowrap">{req.durationMs}ms</span>
                          </div>
                        ))}
                      </div>
                    )}

                    {(evidence.network.failures?.length ?? 0) === 0 && (evidence.network.slowRequests?.length ?? 0) === 0 && (
                      <div className="text-center py-12 text-slate-500">
                        <CheckCircle2 className="h-12 w-12 mx-auto mb-2 text-phosphor-500/30" />
                        <p>All network requests completed successfully.</p>
                      </div>
                    )}
                  </div>
                </TabsContent>

                <TabsContent value="page" className="absolute inset-0 overflow-auto p-4">
                  <div className="space-y-6 max-w-4xl mx-auto">
                    <div className="grid grid-cols-2 gap-4">
                      <div className="p-4 rounded border border-slate-700 bg-slate-900/50">
                        <h4 className="text-xs text-slate-500 uppercase tracking-wider mb-1">Page Title</h4>
                        <p className="text-sm text-white">{evidence.metadata.pageTitle}</p>
                      </div>
                      <div className="p-4 rounded border border-slate-700 bg-slate-900/50">
                        <h4 className="text-xs text-slate-500 uppercase tracking-wider mb-1">Viewport</h4>
                        <p className="text-sm mono text-white">{evidence.metadata.viewport.width} x {evidence.metadata.viewport.height}</p>
                      </div>
                    </div>

                    <div>
                      <h4 className="text-sm font-medium mb-3 text-slate-300">Key Elements Found</h4>
                      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                        {Object.entries(evidence.pageState.keyElements).map(([key, value]) => (
                          <div
                            key={key}
                            className={`p-3 rounded border flex justify-between items-center ${
                              key === "errorMessages" && value > 0
                                ? "border-rose-500/30 bg-rose-500/5"
                                : "border-slate-700 bg-slate-900/50"
                            }`}
                          >
                            <span className="text-sm text-slate-400 capitalize">
                              {key.replace(/([A-Z])/g, " $1").trim()}
                            </span>
                            <span className={`mono font-medium ${key === "errorMessages" && value > 0 ? "text-rose-400" : "text-white"}`}>
                              {value}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div>
                      <h4 className="text-sm font-medium mb-3 text-slate-300">Performance Metrics</h4>
                      <div className="grid grid-cols-3 gap-4">
                        <div className="p-3 rounded border border-slate-700 bg-slate-900/50">
                          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">Page Load</div>
                          <div className="text-xl mono text-white">
                            {evidence.performance.pageLoadMs ?? "N/A"}
                            <span className="text-sm text-slate-500 ml-1">ms</span>
                          </div>
                        </div>
                        <div className="p-3 rounded border border-slate-700 bg-slate-900/50">
                          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">DOM Ready</div>
                          <div className="text-xl mono text-white">
                            {evidence.performance.domContentLoadedMs ?? "N/A"}
                            <span className="text-sm text-slate-500 ml-1">ms</span>
                          </div>
                        </div>
                        <div className="p-3 rounded border border-slate-700 bg-slate-900/50">
                          <div className="text-xs text-slate-500 uppercase tracking-wider mb-1">LCP</div>
                          <div className="text-xl mono text-white">
                            {evidence.performance.largestContentfulPaintMs ?? "N/A"}
                            <span className="text-sm text-slate-500 ml-1">ms</span>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div>
                      <h4 className="text-sm font-medium mb-2 text-slate-300">Visible Text Sample</h4>
                      <div className="p-4 rounded border border-slate-700 bg-slate-950 text-sm mono text-slate-400">
                        {evidence.pageState.visibleTextSample || "No text content"}
                      </div>
                    </div>
                  </div>
                </TabsContent>
              </div>
            </Tabs>

            {/* Review section */}
            <div className="border-t border-slate-700 px-5 py-4 bg-slate-900/80 shrink-0">
              <div className="max-w-4xl mx-auto space-y-3">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-slate-300">Your Review:</span>
                  {artifact?.userApproved === true && (
                    <Badge variant="phosphor">Approved</Badge>
                  )}
                  {artifact?.userApproved === false && (
                    <Badge variant="rose">Rejected</Badge>
                  )}
                </div>
                <div className="flex gap-4">
                  <Textarea
                    placeholder="Add notes about this evidence..."
                    value={userNotes}
                    onChange={(e) => setUserNotes(e.target.value)}
                    rows={2}
                    className="flex-1"
                  />
                  <div className="flex flex-col gap-2 shrink-0 w-28">
                    <Button
                      variant="outline"
                      size="sm"
                      className="w-full border-phosphor-500/50 text-phosphor-400 hover:bg-phosphor-500/10"
                      onClick={() => reviewMutation.mutate({ approved: true, notes: userNotes })}
                      disabled={reviewMutation.isPending}
                    >
                      <CheckCircle2 className="h-4 w-4" />
                      Approve
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      className="w-full border-rose-500/50 text-rose-400 hover:bg-rose-500/10"
                      onClick={() => reviewMutation.mutate({ approved: false, notes: userNotes })}
                      disabled={reviewMutation.isPending}
                    >
                      <XCircle className="h-4 w-4" />
                      Reject
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
