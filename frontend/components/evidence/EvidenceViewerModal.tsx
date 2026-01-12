"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Image from "next/image";
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RefreshCw,
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
  fetchEvidenceData,
  submitEvidenceReview,
  getScreenshotUrl,
  type EvidenceResponse,
  type EvidenceData,
} from "@/lib/api/evidence";

interface EvidenceViewerModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  evidenceId: string;
  criterionText?: string;
}

export function EvidenceViewerModal({
  open,
  onOpenChange,
  projectId,
  evidenceId,
  criterionText,
}: EvidenceViewerModalProps) {
  const [userNotes, setUserNotes] = useState("");
  const [activeTab, setActiveTab] = useState("screenshot");
  const queryClient = useQueryClient();

  // Fetch evidence metadata
  const { data, isLoading, error } = useQuery<EvidenceResponse>({
    queryKey: ["evidence", projectId, evidenceId],
    queryFn: () => fetchEvidence(projectId, evidenceId, false),
    enabled: open && !!projectId && !!evidenceId,
    staleTime: 0,
    refetchOnMount: true,
    retry: 1,
  });

  // Fetch evidence.json data
  const { data: evidenceData } = useQuery<EvidenceData>({
    queryKey: ["evidence-data", projectId, evidenceId],
    queryFn: () => fetchEvidenceData(projectId, evidenceId),
    enabled: open && !!projectId && !!evidenceId,
    staleTime: 60000,
  });

  // Reset state when modal closes
  useEffect(() => {
    if (!open) {
      setUserNotes("");
      setActiveTab("screenshot");
    }
  }, [open]);

  // Submit review mutation
  const reviewMutation = useMutation({
    mutationFn: async ({
      approved,
      notes,
    }: {
      approved: boolean | null;
      notes: string;
    }) => {
      return submitEvidenceReview(projectId, evidenceId, approved, notes);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["evidence", projectId, evidenceId],
      });
    },
  });

  const evidence = data?.evidence;
  const screenshotUrl = data?.screenshotUrl
    ? `/api${data.screenshotUrl}`
    : getScreenshotUrl(projectId, evidenceId);

  // Status badge
  const StatusBadge = () => {
    if (!evidence) return null;
    const status = evidence.qualityStatus;
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
          <Badge
            variant="outline"
            className="gap-1 text-amber-400 border-amber-400/50"
          >
            <AlertTriangle className="h-3 w-3" />
            Needs Review
          </Badge>
        );
      default:
        return <Badge variant="secondary">{status}</Badge>;
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl max-h-[90vh] flex flex-col">
        <DialogHeader className="flex-none border-b border-slate-800 pb-4">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <DialogTitle className="flex items-center gap-2">
                <span className="font-mono text-phosphor-400">
                  {evidence?.taskId || `entry-${evidence?.explorerEntryId}`}
                </span>
                <span className="text-slate-400">/</span>
                <span className="text-slate-300">
                  {evidence?.evidenceType || "screenshot"}
                </span>
              </DialogTitle>
              <DialogDescription className="mt-1">
                <span className="font-mono text-xs text-slate-500">
                  {evidenceId}
                </span>
                {criterionText && (
                  <span className="block mt-1 text-slate-400">
                    {criterionText}
                  </span>
                )}
              </DialogDescription>
            </div>
            <div className="flex items-center gap-2">
              <StatusBadge />
              <span className="text-xs text-slate-500 tabular-nums">
                v{evidence?.version || 1}
              </span>
            </div>
          </div>
        </DialogHeader>

        <div className="flex-1 overflow-hidden">
          <Tabs
            value={activeTab}
            onValueChange={setActiveTab}
            className="h-full flex flex-col"
          >
            <TabsList className="flex-none">
              <TabsTrigger value="screenshot" className="gap-1.5">
                <ImageIcon className="h-3.5 w-3.5" />
                Screenshot
              </TabsTrigger>
              <TabsTrigger value="console" className="gap-1.5">
                <Terminal className="h-3.5 w-3.5" />
                Console
                {evidenceData?.console?.errorCount ? (
                  <Badge variant="rose" className="ml-1">
                    {evidenceData.console.errorCount}
                  </Badge>
                ) : null}
              </TabsTrigger>
              <TabsTrigger value="network" className="gap-1.5">
                <Network className="h-3.5 w-3.5" />
                Network
                {evidenceData?.network?.failedRequests ? (
                  <Badge variant="rose" className="ml-1">
                    {evidenceData.network.failedRequests}
                  </Badge>
                ) : null}
              </TabsTrigger>
              <TabsTrigger value="data" className="gap-1.5">
                <FileJson className="h-3.5 w-3.5" />
                Raw Data
              </TabsTrigger>
            </TabsList>

            <div className="flex-1 overflow-auto mt-4">
              {isLoading ? (
                <div className="flex items-center justify-center h-64">
                  <Loader2 className="h-8 w-8 animate-spin text-slate-600" />
                </div>
              ) : error ? (
                <div className="flex flex-col items-center justify-center h-64 text-slate-400">
                  <AlertTriangle className="h-8 w-8 mb-2" />
                  <p>Failed to load evidence</p>
                </div>
              ) : (
                <>
                  <TabsContent value="screenshot" className="m-0">
                    <div className="relative bg-slate-900 rounded-lg overflow-hidden">
                      <div className="aspect-video relative">
                        <Image
                          src={screenshotUrl}
                          alt="Evidence screenshot"
                          fill
                          className="object-contain"
                          unoptimized
                        />
                      </div>
                      <div className="absolute top-2 right-2 flex gap-2">
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => window.open(screenshotUrl, "_blank")}
                        >
                          <ExternalLink className="h-4 w-4 mr-1" />
                          Full Size
                        </Button>
                      </div>
                    </div>
                  </TabsContent>

                  <TabsContent value="console" className="m-0">
                    <div className="space-y-3">
                      {evidenceData?.console?.errors?.length ? (
                        evidenceData.console.errors.map((err, i) => (
                          <div
                            key={i}
                            className="p-3 rounded bg-red-950/30 border border-red-900/50"
                          >
                            <p className="font-mono text-sm text-red-400 whitespace-pre-wrap">
                              {err.text}
                            </p>
                            {err.source && (
                              <p className="mt-1 text-xs text-slate-500">
                                {err.source}
                              </p>
                            )}
                          </div>
                        ))
                      ) : (
                        <div className="text-center py-8 text-slate-500">
                          <CheckCircle2 className="h-8 w-8 mx-auto mb-2 text-green-500" />
                          <p>No console errors</p>
                        </div>
                      )}
                    </div>
                  </TabsContent>

                  <TabsContent value="network" className="m-0">
                    <div className="space-y-3">
                      {evidenceData?.network?.failures?.length ? (
                        evidenceData.network.failures.map((failure, i) => (
                          <div
                            key={i}
                            className="p-3 rounded bg-red-950/30 border border-red-900/50"
                          >
                            <p className="font-mono text-sm text-red-400 truncate">
                              {failure.url}
                            </p>
                            <p className="mt-1 text-xs text-slate-400">
                              Status: {failure.status}
                              {failure.error && ` - ${failure.error}`}
                            </p>
                          </div>
                        ))
                      ) : (
                        <div className="text-center py-8 text-slate-500">
                          <CheckCircle2 className="h-8 w-8 mx-auto mb-2 text-green-500" />
                          <p>No network failures</p>
                        </div>
                      )}
                    </div>
                  </TabsContent>

                  <TabsContent value="data" className="m-0">
                    <pre className="p-4 rounded bg-slate-900 overflow-auto text-xs font-mono text-slate-300 max-h-96">
                      {JSON.stringify(evidenceData, null, 2)}
                    </pre>
                  </TabsContent>
                </>
              )}
            </div>
          </Tabs>
        </div>

        {/* Review section */}
        {evidence && evidence.qualityStatus !== "passed" && (
          <div className="flex-none border-t border-slate-800 pt-4 space-y-3">
            <Textarea
              value={userNotes}
              onChange={(e) => setUserNotes(e.target.value)}
              placeholder="Add notes about this evidence..."
              className="min-h-[80px]"
            />
            <div className="flex items-center gap-2 justify-end">
              <Button
                variant="outline"
                onClick={() =>
                  reviewMutation.mutate({ approved: false, notes: userNotes })
                }
                disabled={reviewMutation.isPending}
              >
                <XCircle className="h-4 w-4 mr-1 text-red-400" />
                Reject
              </Button>
              <Button
                variant="primary"
                onClick={() =>
                  reviewMutation.mutate({ approved: true, notes: userNotes })
                }
                disabled={reviewMutation.isPending}
              >
                <CheckCircle2 className="h-4 w-4 mr-1" />
                Approve
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
