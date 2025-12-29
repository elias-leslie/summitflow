"use client";

import { memo } from "react";
import { clsx } from "clsx";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Plus, Wand2, Zap, FolderCode } from "lucide-react";
import { ChatStatusIndicator } from "./ChatStatusIndicator";
import { ToolToggle } from "./ToolToggle";
import { AgentConfigPanel, type AgentConfig } from "../settings/AgentConfigPanel";
import type { RoundtableMode, ToolStats, ToolsSettings } from "./RoundtableChat";

interface RoundtableHeaderProps {
  sessionId?: string;
  mode: RoundtableMode;
  onModeChange?: (mode: RoundtableMode) => void;
  connected: boolean;
  isLoading: boolean;
  isGenerating: boolean;
  streamingAgent: "claude" | "gemini" | null;
  hasMessages: boolean;
  onNewSession?: () => void;
  // Tools
  toolsEnabled: boolean;
  writeEnabled: boolean;
  yoloMode: boolean;
  toolStats?: ToolStats;
  onToolsChange?: (settings: Partial<ToolsSettings>) => void;
  // Agent config
  agentOverride: string | null;
  modelOverride: string | null;
  onAgentConfigChange?: (config: AgentConfig) => void;
}

const ModeSelector = memo(function ModeSelector({
  mode,
  onModeChange,
  disabled,
}: {
  mode: RoundtableMode;
  onModeChange?: (mode: RoundtableMode) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex rounded-lg bg-slate-800 p-1 gap-1">
      <button
        type="button"
        onClick={() => onModeChange?.("spec_driven")}
        disabled={disabled}
        className={clsx(
          "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors",
          mode === "spec_driven"
            ? "bg-phosphor-500 text-white"
            : "text-slate-400 hover:text-slate-200 hover:bg-slate-700"
        )}
      >
        <Wand2 className="w-3.5 h-3.5" />
        Spec-Driven
      </button>
      <button
        type="button"
        onClick={() => onModeChange?.("quick")}
        disabled={disabled}
        className={clsx(
          "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors",
          mode === "quick"
            ? "bg-phosphor-500 text-white"
            : "text-slate-400 hover:text-slate-200 hover:bg-slate-700"
        )}
      >
        <Zap className="w-3.5 h-3.5" />
        Quick
      </button>
    </div>
  );
});

export const RoundtableHeader = memo(function RoundtableHeader({
  sessionId,
  mode,
  onModeChange,
  connected,
  isLoading,
  isGenerating,
  streamingAgent,
  hasMessages,
  onNewSession,
  toolsEnabled,
  writeEnabled,
  yoloMode,
  toolStats,
  onToolsChange,
  agentOverride,
  modelOverride,
  onAgentConfigChange,
}: RoundtableHeaderProps) {
  return (
    <div className="flex flex-col gap-3 px-4 py-3 border-b border-slate-800">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-medium text-slate-200">Roundtable</h3>
          {sessionId && (
            <Badge variant="slate" className="text-xs mono">
              {sessionId.slice(0, 8)}
            </Badge>
          )}
          {hasMessages && onNewSession && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onNewSession}
              disabled={isLoading || !!streamingAgent}
              className="h-7 px-2 text-xs text-slate-400 hover:text-slate-200"
            >
              <Plus className="w-3.5 h-3.5 mr-1" />
              New Chat
            </Button>
          )}
        </div>

        <ChatStatusIndicator
          connected={connected}
          isLoading={isLoading}
          isGenerating={isGenerating}
          streamingAgent={streamingAgent}
        />
      </div>

      {/* Mode selector and tools toggle */}
      <div className="flex items-center justify-between gap-3">
        <ModeSelector
          mode={mode}
          onModeChange={onModeChange}
          disabled={isLoading || hasMessages}
        />

        {/* Tools/Codebase access toggles */}
        <div className="flex items-center gap-4">
          <ToolToggle
            id="tools-toggle"
            label="Read"
            checked={toolsEnabled}
            color="phosphor-400"
            icon={FolderCode}
            disabled={isLoading || !!streamingAgent}
            onChange={(enabled) => onToolsChange?.({ toolsEnabled: enabled })}
          />
          <ToolToggle
            id="write-toggle"
            label="Write"
            checked={writeEnabled}
            color="amber-400"
            disabled={isLoading || !!streamingAgent || !toolsEnabled}
            onChange={(enabled) => onToolsChange?.({ writeEnabled: enabled })}
          />
          <ToolToggle
            id="yolo-toggle"
            label="YOLO"
            checked={yoloMode}
            color="rose-400"
            disabled={isLoading || !!streamingAgent || !toolsEnabled}
            onChange={(enabled) => onToolsChange?.({ yoloMode: enabled })}
            title="Auto-approve all tool actions without prompts"
          />

          {/* Tool stats badge */}
          {toolStats && toolStats.total_calls > 0 && (
            <Badge variant="slate" className="text-2xs">
              {toolStats.total_calls} calls
              {toolStats.writes > 0 && ` (${toolStats.writes} writes)`}
            </Badge>
          )}

          {/* Agent config (for generation) */}
          {mode === "spec_driven" && onAgentConfigChange && (
            <div className="flex items-center gap-1.5 border-l border-slate-700 pl-3 ml-1">
              <span className="text-xs text-slate-500">Gen:</span>
              <AgentConfigPanel
                agentOverride={agentOverride}
                modelOverride={modelOverride}
                onAgentChange={(agent) => {
                  const newModel = agent === null ? null : modelOverride;
                  onAgentConfigChange({ agentOverride: agent, modelOverride: newModel });
                }}
                onModelChange={(model) => {
                  onAgentConfigChange({ agentOverride: agentOverride, modelOverride: model });
                }}
                disabled={isLoading || !!streamingAgent}
                compact
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
});
