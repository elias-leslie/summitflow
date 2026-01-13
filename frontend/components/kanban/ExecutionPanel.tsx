"use client";

import { useState } from "react";
import { motion } from "motion/react";
import {
  StopCircle,
  Send,
  Bot,
  Loader2,
  Wifi,
  WifiOff,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { ScrollArea } from "../ui/scroll-area";
import { Progress } from "../ui/progress";
import { Badge } from "../ui/badge";
import { Input } from "../ui/input";

export interface ExecutionLog {
  id: string;
  timestamp: string;
  level: "info" | "warn" | "error" | "success";
  message: string;
}

export interface ExecutionState {
  status: "idle" | "running" | "paused" | "stopped";
  progress: number;
  currentModel: string;
  currentStep?: string;
  logs: ExecutionLog[];
}

interface ExecutionPanelProps {
  taskId: string;
  execution: ExecutionState;
  connected: boolean;
  onStop: () => void;
  onSendMessage: (message: string) => void;
}

const logLevelStyles: Record<ExecutionLog["level"], string> = {
  info: "text-slate-400",
  warn: "text-amber-400",
  error: "text-red-400",
  success: "text-phosphor-400",
};

export function ExecutionPanel({
  taskId,
  execution,
  connected,
  onStop,
  onSendMessage,
}: ExecutionPanelProps) {
  const [chatInput, setChatInput] = useState("");
  const [showLogs, setShowLogs] = useState(true);

  const handleSend = () => {
    if (chatInput.trim()) {
      onSendMessage(chatInput.trim());
      setChatInput("");
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <motion.div
      initial={{ height: 0, opacity: 0 }}
      animate={{ height: "auto", opacity: 1 }}
      exit={{ height: 0, opacity: 0 }}
      transition={{ duration: 0.2, ease: "easeInOut" }}
      className="overflow-hidden"
    >
      <div className="mt-3 pt-3 border-t border-slate-700/50 space-y-3">
        {/* Header: Connection + Model + Progress */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            {/* Connection Status */}
            {connected ? (
              <Badge variant="phosphor" className="gap-1">
                <Wifi className="w-3 h-3" />
                Live
              </Badge>
            ) : (
              <Badge variant="slate" className="gap-1">
                <WifiOff className="w-3 h-3" />
                Disconnected
              </Badge>
            )}

            {/* Current Model */}
            <Badge variant="violet" className="gap-1">
              <Bot className="w-3 h-3" />
              {execution.currentModel || "Flash"}
            </Badge>
          </div>

          {/* Progress */}
          <div className="flex items-center gap-2 flex-1 max-w-[200px]">
            <Progress value={execution.progress} className="h-1.5" />
            <span className="text-xs text-slate-400 mono">
              {execution.progress}%
            </span>
          </div>
        </div>

        {/* Current Step */}
        {execution.currentStep && (
          <div className="flex items-center gap-2 text-xs">
            <Loader2 className="w-3 h-3 animate-spin text-blue-400" />
            <span className="text-slate-300 truncate">
              {execution.currentStep}
            </span>
          </div>
        )}

        {/* Log Viewer */}
        <div className="rounded-md bg-slate-950/50 border border-slate-800">
          <button
            onClick={() => setShowLogs(!showLogs)}
            className="w-full flex items-center justify-between px-2 py-1.5 text-xs text-slate-400 hover:bg-slate-800/50 transition-colors"
          >
            <span>Execution Logs ({execution.logs.length})</span>
            {showLogs ? (
              <ChevronUp className="w-3 h-3" />
            ) : (
              <ChevronDown className="w-3 h-3" />
            )}
          </button>

          {showLogs && (
            <ScrollArea className="h-32 px-2 pb-2">
              <div className="space-y-0.5 font-mono text-xs">
                {execution.logs.length === 0 ? (
                  <div className="text-slate-600 italic py-2">
                    No logs yet...
                  </div>
                ) : (
                  execution.logs.map((log) => (
                    <div key={log.id} className="flex gap-2">
                      <span className="text-slate-600 shrink-0">
                        {new Date(log.timestamp).toLocaleTimeString()}
                      </span>
                      <span className={logLevelStyles[log.level]}>
                        {log.message}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </ScrollArea>
          )}
        </div>

        {/* Chat Input + Actions */}
        <div className="flex items-center gap-2">
          <Input
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Send direction to agent..."
            className="h-8 text-xs"
            disabled={!connected || execution.status !== "running"}
          />

          <button
            onClick={handleSend}
            disabled={
              !chatInput.trim() || !connected || execution.status !== "running"
            }
            className="p-2 rounded-md bg-phosphor-500/20 text-phosphor-400 hover:bg-phosphor-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            title="Send message"
          >
            <Send className="w-4 h-4" />
          </button>

          <button
            onClick={onStop}
            disabled={execution.status !== "running"}
            className="p-2 rounded-md bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            title="Stop execution"
          >
            <StopCircle className="w-4 h-4" />
          </button>
        </div>
      </div>
    </motion.div>
  );
}
