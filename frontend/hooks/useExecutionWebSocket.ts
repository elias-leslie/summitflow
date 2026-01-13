"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  ExecutionLog,
  ExecutionState,
} from "@/components/kanban/ExecutionPanel";

// Message types from backend
type MessageType =
  | "log"
  | "progress"
  | "model_change"
  | "chat_message"
  | "stop_signal"
  | "connected"
  | "error";

interface WebSocketMessage {
  type: MessageType;
  task_id: string;
  data: Record<string, unknown>;
  timestamp: string;
  sequence: number;
}

interface UseExecutionWebSocketOptions {
  taskId: string;
  enabled?: boolean;
  onError?: (error: string) => void;
}

interface UseExecutionWebSocketReturn {
  execution: ExecutionState;
  connected: boolean;
  connecting: boolean;
  sendMessage: (message: string) => void;
  sendStop: () => void;
}

// Exponential backoff config
const INITIAL_RECONNECT_DELAY = 1000;
const MAX_RECONNECT_DELAY = 30000;
const RECONNECT_MULTIPLIER = 2;

export function useExecutionWebSocket({
  taskId,
  enabled = true,
  onError,
}: UseExecutionWebSocketOptions): UseExecutionWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectDelayRef = useRef(INITIAL_RECONNECT_DELAY);
  const lastSequenceRef = useRef(0);

  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [execution, setExecution] = useState<ExecutionState>({
    status: "idle",
    progress: 0,
    currentModel: "Flash",
    logs: [],
  });

  const connect = useCallback(() => {
    if (!enabled || !taskId) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    setConnecting(true);

    // Build WebSocket URL with replay support
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.hostname;
    const port =
      process.env.NODE_ENV === "development" ? "8001" : window.location.port;
    let url = `${protocol}//${host}:${port}/ws/execution/${taskId}`;

    // Add sequence for replay on reconnection
    if (lastSequenceRef.current > 0) {
      url += `?from_sequence=${lastSequenceRef.current}`;
    }

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      setConnecting(false);
      reconnectDelayRef.current = INITIAL_RECONNECT_DELAY;
    };

    ws.onclose = () => {
      setConnected(false);
      setConnecting(false);
      wsRef.current = null;

      // Schedule reconnection with exponential backoff
      if (enabled) {
        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectDelayRef.current = Math.min(
            reconnectDelayRef.current * RECONNECT_MULTIPLIER,
            MAX_RECONNECT_DELAY,
          );
          connect();
        }, reconnectDelayRef.current);
      }
    };

    ws.onerror = () => {
      onError?.("WebSocket connection error");
    };

    ws.onmessage = (event) => {
      try {
        const msg: WebSocketMessage = JSON.parse(event.data);
        lastSequenceRef.current = msg.sequence;

        switch (msg.type) {
          case "connected":
            setExecution((prev) => ({ ...prev, status: "running" }));
            break;

          case "log": {
            const logData = msg.data as { level?: string; message?: string };
            const newLog: ExecutionLog = {
              id: `${msg.sequence}`,
              timestamp: msg.timestamp,
              level: (logData.level as ExecutionLog["level"]) || "info",
              message: String(logData.message || ""),
            };
            setExecution((prev) => ({
              ...prev,
              logs: [...prev.logs.slice(-99), newLog], // Keep last 100 logs
            }));
            break;
          }

          case "progress": {
            const progressData = msg.data as {
              completed_subtasks?: number;
              total_subtasks?: number;
              status?: string;
            };
            const completed = progressData.completed_subtasks || 0;
            const total = progressData.total_subtasks || 1;
            const progress = Math.round((completed / total) * 100);
            setExecution((prev) => ({
              ...prev,
              progress,
              currentStep: progressData.status,
            }));
            break;
          }

          case "model_change": {
            const modelData = msg.data as { model?: string };
            setExecution((prev) => ({
              ...prev,
              currentModel: String(modelData.model || prev.currentModel),
            }));
            break;
          }

          case "stop_signal":
            setExecution((prev) => ({ ...prev, status: "stopped" }));
            break;

          case "error": {
            const errorData = msg.data as { error?: string };
            onError?.(String(errorData.error || "Unknown error"));
            break;
          }

          case "chat_message":
            // Chat messages from other clients - could show in logs
            break;
        }
      } catch (e) {
        console.error("Failed to parse WebSocket message:", e);
      }
    };
  }, [taskId, enabled, onError]);

  // Connect on mount, disconnect on unmount
  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  const sendMessage = useCallback((message: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: "chat_message",
          data: { message },
        }),
      );
    }
  }, []);

  const sendStop = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: "stop_signal",
          data: {},
        }),
      );
    }
  }, []);

  return {
    execution,
    connected,
    connecting,
    sendMessage,
    sendStop,
  };
}
