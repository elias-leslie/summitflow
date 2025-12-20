"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { clsx } from "clsx";
import { Badge, SuccessBadge, ErrorBadge, WarningBadge } from "../ui/badge";
import { ScrollArea } from "../ui/scroll-area";
import { Button } from "../ui/button";
import {
  CheckCircle,
  XCircle,
  PlayCircle,
  PauseCircle,
  Clock,
  Loader2,
  WifiOff,
  Pause,
  Play,
  RefreshCw,
  FileCode,
} from "lucide-react";
import { updateTaskStatus, startTask, TaskStatus, AgentType } from "@/lib/api";

interface FeatureContext {
  id: string;
  name: string;
  description?: string;
}

interface TaskLogViewerProps {
  projectId: string;
  taskId: string;
  className?: string;
  autoScroll?: boolean;
  /** Agent type used to start the task (needed for resume) */
  agentType?: AgentType;
  /** Model used (optional, for resume) */
  model?: string;
  /** Whether delegation was enabled (optional, for resume) */
  allowDelegation?: boolean;
  /** Optional feature context to display above the log */
  feature?: FeatureContext;
}

interface SSEEvent {
  type: "connected" | "log" | "status" | "complete" | "error";
  data: Record<string, unknown>;
}

const statusConfig: Record<TaskStatus, { icon: typeof CheckCircle; variant: "phosphor" | "amber" | "rose" | "slate" }> = {
  pending: { icon: Clock, variant: "slate" },
  running: { icon: PlayCircle, variant: "phosphor" },
  paused: { icon: PauseCircle, variant: "amber" },
  completed: { icon: CheckCircle, variant: "phosphor" },
  failed: { icon: XCircle, variant: "rose" },
};

export function TaskLogViewer({
  projectId,
  taskId,
  className,
  autoScroll = true,
  agentType = "gemini",
  model,
  allowDelegation,
  feature,
}: TaskLogViewerProps) {
  const [log, setLog] = useState<string>("");
  const [status, setStatus] = useState<TaskStatus>("pending");
  const [tokensUsed, setTokensUsed] = useState<number>(0);
  const [connected, setConnected] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [isUpdating, setIsUpdating] = useState<boolean>(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  // Pause the task
  const handlePause = useCallback(async () => {
    if (isUpdating) return;
    setIsUpdating(true);
    try {
      await updateTaskStatus(projectId, taskId, "paused");
      setStatus("paused");
      setLog((prev) => prev + "\n[PAUSED] Task paused by user.\n");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to pause task");
    } finally {
      setIsUpdating(false);
    }
  }, [projectId, taskId, isUpdating]);

  // Resume the task (for paused status)
  const handleResume = useCallback(async () => {
    if (isUpdating) return;
    setIsUpdating(true);
    try {
      // Resume by starting the task again with the same parameters
      await startTask(projectId, taskId, {
        agent_type: agentType,
        model,
        allow_delegation: allowDelegation,
      });
      setStatus("running");
      setLog((prev) => prev + "\n[RESUMED] Task resumed by user.\n");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to resume task");
    } finally {
      setIsUpdating(false);
    }
  }, [projectId, taskId, agentType, model, allowDelegation, isUpdating]);

  // Retry the task (for failed status)
  const handleRetry = useCallback(async () => {
    if (isUpdating) return;
    setIsUpdating(true);
    try {
      // First reset status to pending, then start
      await updateTaskStatus(projectId, taskId, "pending");
      await startTask(projectId, taskId, {
        agent_type: agentType,
        model,
        allow_delegation: allowDelegation,
      });
      setStatus("running");
      setError(null);
      setLog((prev) => prev + "\n[RETRY] Task retried by user.\n");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to retry task");
    } finally {
      setIsUpdating(false);
    }
  }, [projectId, taskId, agentType, model, allowDelegation, isUpdating]);

  // Connect to SSE stream
  useEffect(() => {
    const url = `/api/projects/${projectId}/tasks/${taskId}/stream`;
    const eventSource = new EventSource(url);
    eventSourceRef.current = eventSource;

    eventSource.onopen = () => {
      setConnected(true);
      setError(null);
    };

    eventSource.onerror = () => {
      setConnected(false);
      setError("Connection lost. Retrying...");
    };

    // Handle specific event types
    eventSource.addEventListener("connected", (event) => {
      const data = JSON.parse(event.data);
      setStatus(data.status as TaskStatus);
      setConnected(true);
    });

    eventSource.addEventListener("log", (event) => {
      const data = JSON.parse(event.data);
      setLog((prev) => prev + data.content);
    });

    eventSource.addEventListener("status", (event) => {
      const data = JSON.parse(event.data);
      setStatus(data.status as TaskStatus);
      setTokensUsed(data.total_tokens_used || 0);
    });

    eventSource.addEventListener("complete", (event) => {
      const data = JSON.parse(event.data);
      setStatus(data.status as TaskStatus);
      if (data.error_message) {
        setError(data.error_message);
      }
      // Close connection when complete
      eventSource.close();
    });

    eventSource.addEventListener("error", (event) => {
      try {
        const data = JSON.parse((event as MessageEvent).data);
        setError(data.message);
      } catch {
        setError("Connection error");
      }
    });

    return () => {
      eventSource.close();
      eventSourceRef.current = null;
    };
  }, [projectId, taskId]);

  // Auto-scroll to bottom
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [log, autoScroll]);

  const StatusIcon = statusConfig[status]?.icon || Clock;
  const statusVariant = statusConfig[status]?.variant || "slate";

  return (
    <div className={clsx("flex flex-col bg-slate-900 rounded-lg border border-slate-800", className)}>
      {/* Feature Context (if provided) */}
      {feature && (
        <div className="px-4 py-3 border-b border-slate-800 bg-slate-800/30">
          <div className="flex items-start gap-3">
            <FileCode className="w-5 h-5 text-blue-400 mt-0.5 shrink-0" />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500 mono">{feature.id}</span>
              </div>
              <h4 className="text-sm font-medium text-white truncate">{feature.name}</h4>
              {feature.description && (
                <p className="text-xs text-slate-400 mt-1 line-clamp-2">{feature.description}</p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <Badge variant={statusVariant} className="flex items-center gap-1.5">
            {status === "running" ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <StatusIcon className="w-3.5 h-3.5" />
            )}
            <span className="capitalize">{status}</span>
          </Badge>

          {tokensUsed > 0 && (
            <span className="text-xs text-slate-500 mono">
              {tokensUsed.toLocaleString()} tokens
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* Pause/Resume buttons */}
          {status === "running" && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handlePause}
              disabled={isUpdating}
              className="h-7 px-2 text-amber-400 hover:text-amber-300 hover:bg-amber-950/30"
            >
              {isUpdating ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Pause className="w-4 h-4" />
              )}
              <span className="ml-1.5 text-xs">Pause</span>
            </Button>
          )}
          {status === "paused" && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleResume}
              disabled={isUpdating}
              className="h-7 px-2 text-emerald-400 hover:text-emerald-300 hover:bg-emerald-950/30"
            >
              {isUpdating ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Play className="w-4 h-4" />
              )}
              <span className="ml-1.5 text-xs">Resume</span>
            </Button>
          )}
          {status === "failed" && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleRetry}
              disabled={isUpdating}
              className="h-7 px-2 text-amber-400 hover:text-amber-300 hover:bg-amber-950/30"
            >
              {isUpdating ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <RefreshCw className="w-4 h-4" />
              )}
              <span className="ml-1.5 text-xs">Retry</span>
            </Button>
          )}

          {!connected && error && (
            <div className="flex items-center gap-1.5 text-rose-400 text-xs">
              <WifiOff className="w-3.5 h-3.5" />
              <span>Disconnected</span>
            </div>
          )}
          {connected && (
            <div className="flex items-center gap-1.5 text-emerald-400 text-xs">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span>Live</span>
            </div>
          )}
        </div>
      </div>

      {/* Log Content */}
      <ScrollArea
        ref={scrollRef}
        className="flex-1 min-h-[200px] max-h-[600px] p-4"
      >
        {log ? (
          <pre className="text-sm text-slate-300 mono whitespace-pre-wrap break-words">
            {log}
          </pre>
        ) : (
          <div className="flex items-center justify-center h-full text-slate-500">
            {connected ? (
              <span>Waiting for output...</span>
            ) : (
              <span>Connecting...</span>
            )}
          </div>
        )}
      </ScrollArea>

      {/* Error Footer */}
      {error && status !== "completed" && (
        <div className="px-4 py-2 border-t border-slate-800 bg-rose-950/30">
          <p className="text-xs text-rose-400">{error}</p>
        </div>
      )}
    </div>
  );
}
