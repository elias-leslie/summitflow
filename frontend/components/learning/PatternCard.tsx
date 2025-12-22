"use client";

import { useState } from "react";
import { clsx } from "clsx";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import {
  Check,
  X,
  Undo2,
  GitMerge,
  Plus,
  Pencil,
  Trash2,
  FileCode,
  ChevronDown,
  ChevronUp,
} from "lucide-react";

interface PatternCardProps {
  pattern: Pattern;
  projectPath?: string;
  onApprove?: (patternId: string) => Promise<void>;
  onReject?: (patternId: string) => Promise<void>;
  onApply?: (patternId: string) => Promise<void>;
  onUndo?: (patternId: string) => Promise<void>;
  className?: string;
}

interface Pattern {
  id: string;
  project_id: string;
  pattern_type: string;
  title: string;
  content: string;
  rationale: string | null;
  source_diary_ids: string[] | null;
  source_observation_ids: string[] | null;
  action: "add" | "update" | "remove" | "merge";
  target_pattern_id: string | null;
  status: "pending" | "approved" | "applied" | "rejected" | "merged";
  confidence: number | null;
  usage_count: number | null;
  last_used_at: string | null;
  applied_to_rules_at: string | null;
  created_at: string | null;
}

const ACTION_CONFIG = {
  add: {
    icon: Plus,
    color: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20",
    label: "Add",
  },
  update: {
    icon: Pencil,
    color: "bg-blue-500/10 text-blue-500 border-blue-500/20",
    label: "Update",
  },
  remove: {
    icon: Trash2,
    color: "bg-red-500/10 text-red-500 border-red-500/20",
    label: "Remove",
  },
  merge: {
    icon: GitMerge,
    color: "bg-purple-500/10 text-purple-500 border-purple-500/20",
    label: "Merge",
  },
};

const STATUS_CONFIG = {
  pending: {
    color: "bg-amber-500/10 text-amber-500",
    label: "Pending Review",
  },
  approved: {
    color: "bg-blue-500/10 text-blue-500",
    label: "Approved",
  },
  applied: {
    color: "bg-emerald-500/10 text-emerald-500",
    label: "Applied",
  },
  rejected: {
    color: "bg-red-500/10 text-red-500",
    label: "Rejected",
  },
  merged: {
    color: "bg-purple-500/10 text-purple-500",
    label: "Merged",
  },
};

export function PatternCard({
  pattern,
  projectPath,
  onApprove,
  onReject,
  onApply,
  onUndo,
  className,
}: PatternCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState<string | null>(null);

  const actionConfig = ACTION_CONFIG[pattern.action];
  const statusConfig = STATUS_CONFIG[pattern.status];
  const ActionIcon = actionConfig.icon;

  const confidencePercent = pattern.confidence
    ? Math.round(pattern.confidence * 100)
    : null;

  const handleAction = async (
    action: string,
    handler?: (id: string) => Promise<void>
  ) => {
    if (!handler) return;
    setLoading(action);
    try {
      await handler(pattern.id);
    } finally {
      setLoading(null);
    }
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return null;
    return new Date(dateStr).toLocaleDateString();
  };

  return (
    <Card className={clsx("overflow-hidden", className)}>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge variant="outline" className={clsx("gap-1", actionConfig.color)}>
              <ActionIcon className="h-3 w-3" />
              {actionConfig.label}
            </Badge>
            <Badge variant="outline" className={statusConfig.color}>
              {statusConfig.label}
            </Badge>
            {confidencePercent !== null && (
              <Badge
                variant="outline"
                className={clsx(
                  confidencePercent >= 90
                    ? "bg-emerald-500/10 text-emerald-500"
                    : confidencePercent >= 70
                    ? "bg-amber-500/10 text-amber-500"
                    : "bg-gray-500/10 text-gray-500"
                )}
              >
                {confidencePercent}% confidence
              </Badge>
            )}
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setExpanded(!expanded)}
            className="shrink-0"
          >
            {expanded ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </Button>
        </div>
        <CardTitle className="text-base leading-tight mt-2">
          {pattern.title}
        </CardTitle>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* Pattern content */}
        <div className="text-sm text-muted-foreground bg-muted/50 rounded-md p-3">
          {pattern.content}
        </div>

        {/* Expanded details */}
        {expanded && (
          <div className="space-y-3 pt-2 border-t">
            {/* Rationale */}
            {pattern.rationale && (
              <div>
                <h4 className="text-xs font-medium text-muted-foreground mb-1">
                  Rationale
                </h4>
                <p className="text-sm">{pattern.rationale}</p>
              </div>
            )}

            {/* Source info */}
            {pattern.source_diary_ids && pattern.source_diary_ids.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-muted-foreground mb-1">
                  Source Entries
                </h4>
                <div className="flex gap-1 flex-wrap">
                  {pattern.source_diary_ids.map((id) => (
                    <Badge key={id} variant="secondary" className="text-xs">
                      <FileCode className="h-3 w-3 mr-1" />
                      {id.slice(0, 8)}...
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {/* Target pattern for update/remove */}
            {pattern.target_pattern_id && (
              <div>
                <h4 className="text-xs font-medium text-muted-foreground mb-1">
                  Target Pattern
                </h4>
                <Badge variant="outline">
                  {pattern.target_pattern_id.slice(0, 8)}...
                </Badge>
              </div>
            )}

            {/* Usage stats for applied patterns */}
            {pattern.status === "applied" && (
              <div className="flex gap-4 text-xs text-muted-foreground">
                <span>Used: {pattern.usage_count || 0} times</span>
                {pattern.last_used_at && (
                  <span>Last used: {formatDate(pattern.last_used_at)}</span>
                )}
                {pattern.applied_to_rules_at && (
                  <span>Applied: {formatDate(pattern.applied_to_rules_at)}</span>
                )}
              </div>
            )}

            {/* Created date */}
            <div className="text-xs text-muted-foreground">
              Created: {formatDate(pattern.created_at) || "Unknown"}
            </div>
          </div>
        )}

        {/* Action buttons */}
        <div className="flex gap-2 flex-wrap pt-2">
          {pattern.status === "pending" && (
            <>
              <Button
                size="sm"
                onClick={() => handleAction("approve", onApprove)}
                disabled={loading !== null}
                className="gap-1"
              >
                <Check className="h-3 w-3" />
                {loading === "approve" ? "Approving..." : "Approve"}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => handleAction("reject", onReject)}
                disabled={loading !== null}
                className="gap-1"
              >
                <X className="h-3 w-3" />
                {loading === "reject" ? "Rejecting..." : "Reject"}
              </Button>
            </>
          )}

          {pattern.status === "approved" && projectPath && (
            <Button
              size="sm"
              onClick={() => handleAction("apply", onApply)}
              disabled={loading !== null}
              className="gap-1"
            >
              <FileCode className="h-3 w-3" />
              {loading === "apply" ? "Applying..." : "Apply to Rules"}
            </Button>
          )}

          {pattern.status === "applied" && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => handleAction("undo", onUndo)}
              disabled={loading !== null}
              className="gap-1"
            >
              <Undo2 className="h-3 w-3" />
              {loading === "undo" ? "Undoing..." : "Undo"}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
