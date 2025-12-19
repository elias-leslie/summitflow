"use client";

import { useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { Badge, SuccessBadge, ErrorBadge, WarningBadge } from "../ui/badge";
import { ScrollArea } from "../ui/scroll-area";
import {
  CheckCircle,
  XCircle,
  PlayCircle,
  PauseCircle,
  Clock,
  Loader2,
  WifiOff,
} from "lucide-react";

interface TaskLogViewerProps {
  projectId: string;
  taskId: string;
  className?: string;
  autoScroll?: boolean;
}

interface SSEEvent {
  type: "connected" | "log" | "status" | "complete" | "error";
  data: Record<string, unknown>;
}

type TaskStatus = "pending" | "running" | "paused" | "completed" | "failed";

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
}: TaskLogViewerProps) {
  const [log, setLog] = useState<string>("");
  const [status, setStatus] = useState<TaskStatus>("pending");
  const [tokensUsed, setTokensUsed] = useState<number>(0);
  const [connected, setConnected] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

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
