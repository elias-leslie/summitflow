"use client";

import { clsx } from "clsx";
import { Loader2, WifiOff, CircleDot } from "lucide-react";

export interface ChatStatusIndicatorProps {
  connected: boolean;
  isLoading: boolean;
  isGenerating: boolean;
  streamingAgent: "claude" | "gemini" | null;
}

export function ChatStatusIndicator({
  connected,
  isLoading,
  isGenerating,
  streamingAgent,
}: ChatStatusIndicatorProps) {
  // Streaming indicator
  if (streamingAgent) {
    return (
      <div
        className={clsx(
          "flex items-center gap-1.5 text-xs",
          streamingAgent === "claude" ? "text-amber-400" : "text-blue-400"
        )}
      >
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        <span>
          {streamingAgent === "claude" ? "Claude" : "Gemini"} is responding...
        </span>
      </div>
    );
  }

  // Loading indicator (general)
  if (isLoading || isGenerating) {
    return (
      <div className="flex items-center gap-1.5 text-blue-400 text-xs">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        <span>{isGenerating ? "Generating..." : "Thinking..."}</span>
      </div>
    );
  }

  // Connection status
  if (!connected) {
    return (
      <div className="flex items-center gap-1.5 text-rose-400 text-xs">
        <WifiOff className="w-3.5 h-3.5" />
        <span>Disconnected</span>
      </div>
    );
  }

  // Ready state
  return (
    <div className="flex items-center gap-1.5 text-emerald-400 text-xs">
      <CircleDot className="w-3.5 h-3.5" />
      <span>Ready</span>
    </div>
  );
}
