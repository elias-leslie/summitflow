"use client";

import { useState, useCallback } from "react";
import { useMutation } from "@tanstack/react-query";
import { motion, AnimatePresence } from "motion/react";
import {
  X,
  AlertTriangle,
  AlertCircle,
  CheckCircle2,
  Loader2,
  Bot,
  Terminal,
  Network,
  Gauge,
  FileCode,
  Plus,
  Edit3,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";

interface Issue {
  id: string;
  severity: "critical" | "high" | "medium" | "low";
  category: string;
  title: string;
  description: string;
  evidence: string;
  proposed_fix?: {
    feature_name: string;
    description: string;
    acceptance_criteria: string[];
  };
}

interface AgentAnalysis {
  issues: Issue[];
  overall: {
    score: number;
    status: string;
    summary: string;
  };
  raw_analysis?: string;
}

interface AgentReviewResponse {
  success: boolean;
  agent: string;
  model: string;
  analysis: AgentAnalysis;
  quality_status: string;
  confidence: number;
}

interface EvidenceReviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  evidenceId: string;
  screenshotUrl: string;
  capabilityId: string;
  criterionId: string;
  onFeaturesCreated?: (features: Array<{ id: string; name: string }>) => void;
}

async function requestAgentReview(
  projectId: string,
  evidenceId: string,
  agent: "claude" | "gemini"
): Promise<AgentReviewResponse> {
  const res = await fetch(
    `/api/projects/${projectId}/evidence/${evidenceId}/agent-review`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent }),
    }
  );
  if (!res.ok) {
    const error = await res.json();
    throw new Error(error.detail || "Agent review failed");
  }
  return res.json();
}

export function EvidenceReviewDialog({
  open,
  onOpenChange,
  projectId,
  evidenceId,
  screenshotUrl,
  capabilityId,
  criterionId,
  onFeaturesCreated,
}: EvidenceReviewDialogProps) {
  const [selectedAgent, setSelectedAgent] = useState<"claude" | "gemini">("gemini");
  const [analysis, setAnalysis] = useState<AgentAnalysis | null>(null);
  const [expandedIssues, setExpandedIssues] = useState<Set<string>>(new Set());
  const [editingFeature, setEditingFeature] = useState<string | null>(null);
  const [editedFeatures, setEditedFeatures] = useState<Record<string, Issue["proposed_fix"]>>({});

  // Agent review mutation
  const reviewMutation = useMutation({
    mutationFn: () => requestAgentReview(projectId, evidenceId, selectedAgent),
    onSuccess: (data) => {
      setAnalysis(data.analysis);
      // Expand all issues by default
      setExpandedIssues(new Set(data.analysis.issues.map((i) => i.id)));
    },
    onError: (error) => {
      toast.error(error instanceof Error ? error.message : "Review failed");
    },
  });

  const toggleIssue = useCallback((issueId: string) => {
    setExpandedIssues((prev) => {
      const next = new Set(prev);
      if (next.has(issueId)) {
        next.delete(issueId);
      } else {
        next.add(issueId);
      }
      return next;
    });
  }, []);

  const handleEditFeature = useCallback((issueId: string) => {
    setEditingFeature(issueId);
  }, []);

  const handleSaveFeature = useCallback((issueId: string, feature: Issue["proposed_fix"]) => {
    if (feature) {
      setEditedFeatures((prev) => ({ ...prev, [issueId]: feature }));
    }
    setEditingFeature(null);
  }, []);

  const handleAcceptFeature = useCallback(async (issue: Issue) => {
    const feature = editedFeatures[issue.id] || issue.proposed_fix;
    if (!feature) {
      toast.error("No feature to accept");
      return;
    }

    // TODO: Call API to create feature
    toast.success(`Created feature: ${feature.feature_name}`);
    onFeaturesCreated?.([{ id: `FEAT-NEW`, name: feature.feature_name }]);
  }, [editedFeatures, onFeaturesCreated]);

  const getSeverityBadge = (severity: string) => {
    switch (severity) {
      case "critical":
        return <Badge variant="rose">Critical</Badge>;
      case "high":
        return <Badge variant="amber">High</Badge>;
      case "medium":
        return <Badge variant="default">Medium</Badge>;
      case "low":
        return <Badge variant="phosphor">Low</Badge>;
      default:
        return <Badge>{severity}</Badge>;
    }
  };

  const getCategoryIcon = (category: string) => {
    switch (category) {
      case "error":
        return <AlertCircle className="h-4 w-4 text-rose-400" />;
      case "performance":
        return <Gauge className="h-4 w-4 text-amber-400" />;
      case "ux":
        return <FileCode className="h-4 w-4 text-blue-400" />;
      case "accessibility":
        return <Terminal className="h-4 w-4 text-purple-400" />;
      default:
        return <Network className="h-4 w-4 text-slate-400" />;
    }
  };

  const getScoreColor = (score: number) => {
    if (score >= 80) return "text-phosphor-400";
    if (score >= 50) return "text-amber-400";
    return "text-rose-400";
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!max-w-[90vw] !w-[85vw] !h-[85vh] !fixed !top-1/2 !left-1/2 !-translate-x-1/2 !-translate-y-1/2 flex flex-col p-0 gap-0 overflow-hidden">
        {/* Header */}
        <DialogHeader className="px-5 py-4 border-b border-slate-700 shrink-0 relative">
          <button
            onClick={() => onOpenChange(false)}
            className="absolute right-4 top-4 p-1.5 rounded-md text-slate-500 hover:text-phosphor-400 hover:bg-slate-800 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
          <DialogTitle className="flex items-center gap-3">
            <Bot className="h-5 w-5 text-phosphor-400" />
            <span>Agent Review</span>
            <span className="mono text-sm text-slate-400">{evidenceId}</span>
          </DialogTitle>
          <DialogDescription>
            AI agent analyzes captured evidence and proposes fixes
          </DialogDescription>
        </DialogHeader>

        {/* Content */}
        <div className="flex-1 flex min-h-0 overflow-hidden">
          {/* Left: Screenshot preview */}
          <div className="w-1/3 border-r border-slate-700 p-4 overflow-auto bg-slate-900/50">
            <h3 className="text-sm font-medium text-slate-300 mb-3">Captured Evidence</h3>
            <div className="rounded border border-slate-700 overflow-hidden mb-4">
              <img
                src={screenshotUrl}
                alt="Evidence screenshot"
                className="w-full"
              />
            </div>
            <div className="text-xs text-slate-500">
              <div className="flex items-center gap-2 mb-1">
                <span>Feature:</span>
                <span className="mono text-phosphor-400">{capabilityId}</span>
              </div>
              <div className="flex items-center gap-2">
                <span>Criterion:</span>
                <span className="mono text-slate-300">{criterionId}</span>
              </div>
            </div>
          </div>

          {/* Right: Analysis */}
          <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
            {!analysis ? (
              /* No analysis yet - show agent selection */
              <div className="flex-1 flex flex-col items-center justify-center p-8">
                <Bot className="h-16 w-16 text-slate-600 mb-6" />
                <h3 className="text-lg font-medium text-white mb-2">
                  Request Agent Analysis
                </h3>
                <p className="text-sm text-slate-400 text-center max-w-md mb-6">
                  An AI agent will analyze the captured evidence to identify issues,
                  potential bugs, and propose features to fix them.
                </p>

                <div className="flex items-center gap-3 mb-6">
                  <Button
                    variant={selectedAgent === "gemini" ? "primary" : "outline"}
                    size="sm"
                    onClick={() => setSelectedAgent("gemini")}
                  >
                    Gemini (Fast)
                  </Button>
                  <Button
                    variant={selectedAgent === "claude" ? "primary" : "outline"}
                    size="sm"
                    onClick={() => setSelectedAgent("claude")}
                  >
                    Claude (Detailed)
                  </Button>
                </div>

                <Button
                  variant="primary"
                  onClick={() => reviewMutation.mutate()}
                  disabled={reviewMutation.isPending}
                  className="gap-2"
                >
                  {reviewMutation.isPending ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Analyzing...
                    </>
                  ) : (
                    <>
                      <Bot className="h-4 w-4" />
                      Analyze with {selectedAgent === "gemini" ? "Gemini" : "Claude"}
                    </>
                  )}
                </Button>
              </div>
            ) : (
              /* Analysis results */
              <div className="flex-1 overflow-auto p-4">
                {/* Overall score */}
                <div className="flex items-center gap-4 mb-6 p-4 rounded-lg bg-slate-800/50 border border-slate-700">
                  <div className={`text-4xl font-bold mono ${getScoreColor(analysis.overall.score)}`}>
                    {analysis.overall.score}
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <Badge
                        variant={
                          analysis.overall.status === "good"
                            ? "phosphor"
                            : analysis.overall.status === "acceptable"
                            ? "amber"
                            : "rose"
                        }
                      >
                        {analysis.overall.status}
                      </Badge>
                      <span className="text-xs text-slate-500">
                        {analysis.issues.length} issue(s) found
                      </span>
                    </div>
                    <p className="text-sm text-slate-300">{analysis.overall.summary}</p>
                  </div>
                </div>

                {/* Issues list */}
                <h3 className="text-sm font-medium text-slate-300 mb-3">
                  Issues & Proposed Fixes
                </h3>

                {analysis.issues.length === 0 ? (
                  <div className="text-center py-8 text-slate-500">
                    <CheckCircle2 className="h-12 w-12 mx-auto mb-2 text-phosphor-500/30" />
                    <p>No issues found!</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {analysis.issues.map((issue) => {
                      const isExpanded = expandedIssues.has(issue.id);
                      const isEditing = editingFeature === issue.id;
                      const currentFeature = editedFeatures[issue.id] || issue.proposed_fix;

                      return (
                        <div
                          key={issue.id}
                          className="rounded-lg border border-slate-700 bg-slate-800/30 overflow-hidden"
                        >
                          {/* Issue header */}
                          <button
                            onClick={() => toggleIssue(issue.id)}
                            className="w-full flex items-center gap-3 p-3 text-left hover:bg-slate-700/30"
                          >
                            {isExpanded ? (
                              <ChevronDown className="h-4 w-4 text-slate-500 shrink-0" />
                            ) : (
                              <ChevronRight className="h-4 w-4 text-slate-500 shrink-0" />
                            )}
                            {getCategoryIcon(issue.category)}
                            <span className="flex-1 text-sm font-medium text-white truncate">
                              {issue.title}
                            </span>
                            {getSeverityBadge(issue.severity)}
                          </button>

                          {/* Issue details */}
                          <AnimatePresence>
                            {isExpanded && (
                              <motion.div
                                initial={{ height: 0, opacity: 0 }}
                                animate={{ height: "auto", opacity: 1 }}
                                exit={{ height: 0, opacity: 0 }}
                                className="border-t border-slate-700/50"
                              >
                                <div className="p-4 space-y-4">
                                  <div>
                                    <h4 className="text-xs text-slate-500 uppercase mb-1">
                                      Description
                                    </h4>
                                    <p className="text-sm text-slate-300">{issue.description}</p>
                                  </div>

                                  <div>
                                    <h4 className="text-xs text-slate-500 uppercase mb-1">
                                      Evidence
                                    </h4>
                                    <p className="text-sm text-slate-400 italic">
                                      {issue.evidence}
                                    </p>
                                  </div>

                                  {/* Proposed fix */}
                                  {currentFeature && (
                                    <div className="rounded border border-phosphor-500/30 bg-phosphor-500/5 p-3">
                                      <div className="flex items-center justify-between mb-2">
                                        <h4 className="text-xs text-phosphor-400 uppercase">
                                          Proposed Fix
                                        </h4>
                                        <Button
                                          variant="ghost"
                                          size="sm"
                                          onClick={() => handleEditFeature(issue.id)}
                                          className="h-6 px-2"
                                        >
                                          <Edit3 className="h-3 w-3 mr-1" />
                                          Edit
                                        </Button>
                                      </div>

                                      {isEditing ? (
                                        <div className="space-y-3">
                                          <div>
                                            <label className="text-xs text-slate-500 block mb-1">
                                              Feature Name
                                            </label>
                                            <Input
                                              value={currentFeature.feature_name}
                                              onChange={(e) =>
                                                setEditedFeatures((prev) => ({
                                                  ...prev,
                                                  [issue.id]: {
                                                    ...currentFeature,
                                                    feature_name: e.target.value,
                                                  },
                                                }))
                                              }
                                              className="h-8"
                                            />
                                          </div>
                                          <div>
                                            <label className="text-xs text-slate-500 block mb-1">
                                              Description
                                            </label>
                                            <Textarea
                                              value={currentFeature.description}
                                              onChange={(e) =>
                                                setEditedFeatures((prev) => ({
                                                  ...prev,
                                                  [issue.id]: {
                                                    ...currentFeature,
                                                    description: e.target.value,
                                                  },
                                                }))
                                              }
                                              rows={2}
                                            />
                                          </div>
                                          <div className="flex justify-end gap-2">
                                            <Button
                                              variant="ghost"
                                              size="sm"
                                              onClick={() => setEditingFeature(null)}
                                            >
                                              Cancel
                                            </Button>
                                            <Button
                                              variant="primary"
                                              size="sm"
                                              onClick={() =>
                                                handleSaveFeature(issue.id, currentFeature)
                                              }
                                            >
                                              Save
                                            </Button>
                                          </div>
                                        </div>
                                      ) : (
                                        <>
                                          <div className="text-sm font-medium text-white mb-1">
                                            {currentFeature.feature_name}
                                          </div>
                                          <p className="text-sm text-slate-400 mb-2">
                                            {currentFeature.description}
                                          </p>
                                          {currentFeature.acceptance_criteria.length > 0 && (
                                            <div className="text-xs">
                                              <span className="text-slate-500">Criteria: </span>
                                              <span className="text-slate-400">
                                                {currentFeature.acceptance_criteria.join(", ")}
                                              </span>
                                            </div>
                                          )}
                                        </>
                                      )}
                                    </div>
                                  )}

                                  {/* Actions */}
                                  {currentFeature && !isEditing && (
                                    <div className="flex justify-end">
                                      <Button
                                        variant="primary"
                                        size="sm"
                                        onClick={() => handleAcceptFeature(issue)}
                                        className="gap-1.5"
                                      >
                                        <Plus className="h-4 w-4" />
                                        Create Feature
                                      </Button>
                                    </div>
                                  )}
                                </div>
                              </motion.div>
                            )}
                          </AnimatePresence>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Raw analysis fallback */}
                {analysis.raw_analysis && (
                  <div className="mt-6 p-4 rounded border border-slate-700 bg-slate-900">
                    <h4 className="text-xs text-slate-500 uppercase mb-2">Raw Analysis</h4>
                    <pre className="text-xs text-slate-400 whitespace-pre-wrap font-mono">
                      {analysis.raw_analysis}
                    </pre>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        {analysis && (
          <div className="border-t border-slate-700 px-5 py-3 bg-slate-900/80 flex justify-between items-center">
            <div className="text-xs text-slate-500">
              Reviewed by {reviewMutation.data?.agent} ({reviewMutation.data?.model})
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setAnalysis(null);
                  setExpandedIssues(new Set());
                  setEditedFeatures({});
                }}
              >
                Re-analyze
              </Button>
              <Button variant="primary" size="sm" onClick={() => onOpenChange(false)}>
                Done
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
