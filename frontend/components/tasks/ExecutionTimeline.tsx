"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  Loader2,
  MessageSquare,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  Zap,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Send,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// ============================================================================
// Types
// ============================================================================

interface TimelineMessage {
  type:
    | "log"
    | "progress"
    | "model_change"
    | "chat_message"
    | "error"
    | "connected";
  task_id: string;
  data: Record<string, unknown>;
  timestamp: string;
  sequence: number;
}

interface ExecutionTimelineProps {
  taskId: string;
  /** Whether to auto-connect on mount */
  autoConnect?: boolean;
  /** Show chat input at bottom */
  showChatInput?: boolean;
  /** Whether chat input is enabled (task must be executing) */
  chatEnabled?: boolean;
  /** Optional class name */
  className?: string;
}

// ============================================================================
// WebSocket URL helper
// ============================================================================

function getWebSocketUrl(taskId: string, fromSequence?: number): string {
  // Use the API base URL but replace http with ws
  const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";
  const wsBase = apiBase.replace(/^http/, "ws");
  const url = `${wsBase}/ws/execution/${taskId}`;
  return fromSequence ? `${url}?from_sequence=${fromSequence}` : url;
}

// ============================================================================
// Message Component
// ============================================================================

function TimelineEvent({ message }: { message: TimelineMessage }) {
  const time = new Date(message.timestamp).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  // Log message
  if (message.type === "log") {
    const level = message.data.level as string;
    const text = message.data.message as string;
    const source = message.data.source as string;

    const levelColors: Record<string, string> = {
      debug: "text-slate-500",
      info: "text-slate-400",
      warning: "text-amber-400",
      error: "text-red-400",
    };

    return (
      <div className="flex gap-3 py-1.5 px-3 hover:bg-slate-800/30">
        <span className="text-2xs text-slate-600 mono shrink-0 w-16">
          {time}
        </span>
        <span
          className={`text-2xs mono shrink-0 w-12 ${levelColors[level] || "text-slate-400"}`}
        >
          {level.toUpperCase()}
        </span>
        <span className="text-sm text-slate-300 break-words">{text}</span>
        {source && source !== "orchestrator" && (
          <span className="text-2xs text-slate-600 ml-auto shrink-0">
            [{source}]
          </span>
        )}
      </div>
    );
  }

  // Progress update
  if (message.type === "progress") {
    const subtaskId = message.data.subtask_id as string | null;
    const step = message.data.step as number | null;
    const status = message.data.status as string;
    const completed = message.data.completed_subtasks as number | null;
    const total = message.data.total_subtasks as number | null;

    const statusIcons: Record<string, React.ReactNode> = {
      in_progress: <Loader2 className="h-3 w-3 animate-spin text-blue-400" />,
      completed: <CheckCircle2 className="h-3 w-3 text-phosphor-400" />,
      failed: <XCircle className="h-3 w-3 text-red-400" />,
    };

    return (
      <div className="flex items-center gap-3 py-1.5 px-3 bg-slate-800/20">
        <span className="text-2xs text-slate-600 mono shrink-0 w-16">
          {time}
        </span>
        {statusIcons[status] || <div className="w-3" />}
        <span className="text-sm text-slate-300">
          {subtaskId && (
            <>
              <span className="text-slate-500">Subtask</span>{" "}
              <span className="mono text-phosphor-400">{subtaskId}</span>
              {step !== null && (
                <>
                  {" "}
                  <span className="text-slate-500">step</span>{" "}
                  <span className="mono">{step}</span>
                </>
              )}
            </>
          )}
          {completed !== null && total !== null && (
            <span className="text-slate-500 ml-2">
              ({completed}/{total} subtasks)
            </span>
          )}
        </span>
      </div>
    );
  }

  // Model change
  if (message.type === "model_change") {
    const model = message.data.model as string;
    const reason = message.data.reason as string;

    return (
      <div className="flex items-center gap-3 py-1.5 px-3 bg-purple-950/20 border-l-2 border-purple-500">
        <span className="text-2xs text-slate-600 mono shrink-0 w-16">
          {time}
        </span>
        <Zap className="h-3 w-3 text-purple-400" />
        <span className="text-sm text-purple-300">
          Switched to <span className="font-medium">{model}</span>
          {reason && (
            <span className="text-purple-400/70 ml-1">— {reason}</span>
          )}
        </span>
      </div>
    );
  }

  // Chat message
  if (message.type === "chat_message") {
    const text = message.data.message as string;
    const sender = message.data.sender as string | undefined;
    const isUser = sender === "user" || !sender;

    return (
      <div className="flex gap-3 py-2 px-3 bg-blue-950/20 border-l-2 border-blue-500">
        <span className="text-2xs text-slate-600 mono shrink-0 w-16">
          {time}
        </span>
        <MessageSquare className="h-3 w-3 text-blue-400 mt-0.5" />
        <div className="flex-1">
          <span className="text-xs font-medium text-blue-400">
            {isUser ? "You:" : "Agent:"}
          </span>
          <p className="text-sm text-slate-300 mt-0.5">{text}</p>
        </div>
      </div>
    );
  }

  // Error
  if (message.type === "error") {
    const error = message.data.error as string;
    const recoverable = message.data.recoverable as boolean;

    return (
      <div className="flex items-center gap-3 py-2 px-3 bg-red-950/20 border-l-2 border-red-500">
        <span className="text-2xs text-slate-600 mono shrink-0 w-16">
          {time}
        </span>
        <AlertCircle className="h-3 w-3 text-red-400" />
        <span className="text-sm text-red-300">{error}</span>
        {!recoverable && (
          <span className="text-2xs px-1.5 py-0.5 bg-red-500/20 text-red-400 rounded">
            Fatal
          </span>
        )}
      </div>
    );
  }

  // Connected
  if (message.type === "connected") {
    return (
      <div className="flex items-center gap-3 py-1 px-3 text-xs text-slate-600">
        <span className="mono shrink-0 w-16">{time}</span>
        <span>Connected to execution stream</span>
      </div>
    );
  }

  return null;
}

// ============================================================================
// Execution Timeline Component
// ============================================================================

export function ExecutionTimeline({
  taskId,
  autoConnect = true,
  showChatInput = false,
  chatEnabled = false,
  className = "",
}: ExecutionTimelineProps) {
  const [messages, setMessages] = useState<TimelineMessage[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPrevious, setShowPrevious] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [isSending, setIsSending] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastSequenceRef = useRef<number>(0);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptRef = useRef<number>(0);
  const maxReconnectDelay = 30000; // Cap at 30 seconds

  // Auto-scroll to bottom when new messages arrive
  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  // Connect to WebSocket
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const ws = new WebSocket(
        getWebSocketUrl(taskId, lastSequenceRef.current),
      );

      ws.onopen = () => {
        setIsConnected(true);
        setError(null);
        reconnectAttemptRef.current = 0; // Reset on successful connection
      };

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as TimelineMessage;
          lastSequenceRef.current = Math.max(
            lastSequenceRef.current,
            message.sequence,
          );
          setMessages((prev) => [...prev, message]);
          // Auto-scroll after DOM update
          setTimeout(scrollToBottom, 10);
        } catch (err) {
          console.error("Failed to parse message:", err);
        }
      };

      ws.onerror = () => {
        setError("Connection error");
        setIsConnected(false);
      };

      ws.onclose = () => {
        setIsConnected(false);
        // Auto-reconnect with exponential backoff
        if (autoConnect) {
          const attempt = reconnectAttemptRef.current;
          const delay = Math.min(
            1000 * Math.pow(2, attempt),
            maxReconnectDelay,
          );
          reconnectAttemptRef.current = attempt + 1;
          reconnectTimeoutRef.current = setTimeout(connect, delay);
        }
      };

      wsRef.current = ws;
    } catch (err) {
      console.error("Failed to connect:", err);
      setError("Failed to connect to execution stream");
    }
  }, [taskId, autoConnect, scrollToBottom]);

  // Disconnect from WebSocket
  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  // Connect on mount if autoConnect is true
  useEffect(() => {
    if (autoConnect) {
      connect();
    }
    return () => {
      disconnect();
    };
  }, [autoConnect, connect, disconnect]);

  // Send chat message
  const sendChatMessage = useCallback((text: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: "chat_message",
          data: { message: text, sender: "user" },
        }),
      );
    }
  }, []);

  // Send stop signal
  const sendStopSignal = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "stop_signal" }));
    }
  }, []);

  // Expose methods via ref if needed
  // We'll add this later when integrating with TaskModal

  return (
    <div className={`flex flex-col ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700">
        <h3 className="text-sm font-medium text-slate-400">
          Execution Timeline
        </h3>
        <div className="flex items-center gap-2">
          {isConnected ? (
            <span className="flex items-center gap-1 text-xs text-phosphor-400">
              <span className="w-1.5 h-1.5 bg-phosphor-400 rounded-full animate-pulse" />
              Live
            </span>
          ) : error ? (
            <button
              onClick={connect}
              className="flex items-center gap-1 text-xs text-amber-400 hover:text-amber-300"
            >
              <RefreshCw className="h-3 w-3" />
              Reconnect
            </button>
          ) : (
            <span className="text-xs text-slate-600">Connecting...</span>
          )}
        </div>
      </div>

      {/* Previous executions toggle */}
      <button
        onClick={() => setShowPrevious(!showPrevious)}
        className="flex items-center gap-2 px-3 py-1.5 text-xs text-slate-500 hover:text-slate-400 hover:bg-slate-800/30"
      >
        {showPrevious ? (
          <ChevronUp className="h-3 w-3" />
        ) : (
          <ChevronDown className="h-3 w-3" />
        )}
        Previous Executions
      </button>

      <AnimatePresence>
        {showPrevious && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="border-b border-slate-800 bg-slate-900/50 overflow-hidden"
          >
            <div className="p-3 text-xs text-slate-500 italic">
              No previous executions found
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Timeline content */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto min-h-[200px] max-h-[400px] bg-slate-950/30"
      >
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-600 py-8">
            {isConnected ? (
              <>
                <Loader2 className="h-5 w-5 animate-spin mb-2" />
                <span className="text-sm">Waiting for execution events...</span>
              </>
            ) : error ? (
              <>
                <AlertCircle className="h-5 w-5 mb-2 text-amber-500" />
                <span className="text-sm text-amber-500">{error}</span>
              </>
            ) : (
              <>
                <Loader2 className="h-5 w-5 animate-spin mb-2" />
                <span className="text-sm">Connecting...</span>
              </>
            )}
          </div>
        ) : (
          <div className="py-2">
            {messages.map((message, idx) => (
              <TimelineEvent
                key={`${message.sequence}-${idx}`}
                message={message}
              />
            ))}
          </div>
        )}
      </div>

      {/* Chat Input */}
      {showChatInput && (
        <div className="border-t border-slate-700 px-3 py-2">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (!chatInput.trim() || !chatEnabled || isSending) return;
              setIsSending(true);
              sendChatMessage(chatInput.trim());
              setChatInput("");
              setIsSending(false);
            }}
            className="flex items-center gap-2"
          >
            <Input
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              placeholder={
                chatEnabled
                  ? "Send direction to agent..."
                  : "Chat disabled (not executing)"
              }
              disabled={!chatEnabled}
              className="flex-1 h-8 text-sm"
            />
            <Button
              type="submit"
              variant="outline"
              size="sm"
              disabled={!chatEnabled || !chatInput.trim() || isSending}
              className="h-8 px-3"
            >
              <Send className="h-4 w-4" />
            </Button>
          </form>
        </div>
      )}
    </div>
  );
}

// Export helper types and methods for external use
export type { TimelineMessage };
export { getWebSocketUrl };
