"use client";

import { clsx } from "clsx";
import { Bot, Sparkles, Settings2 } from "lucide-react";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "../ui/select";

export interface AgentConfig {
  agentOverride: string | null;
  modelOverride: string | null;
}

interface AgentConfigPanelProps {
  agentOverride: string | null;
  modelOverride: string | null;
  onAgentChange: (agent: string | null) => void;
  onModelChange: (model: string | null) => void;
  disabled?: boolean;
  compact?: boolean;
  className?: string;
}

// Available agents and their default models
const AGENTS = [
  { id: "default", label: "Auto (default)", icon: Settings2 },
  { id: "claude", label: "Claude", icon: Sparkles },
  { id: "gemini", label: "Gemini", icon: Bot },
];

const CLAUDE_MODELS = [
  { id: "default", label: "Default (Claude Sonnet 4.5)" },
  { id: "claude-opus-4-5", label: "Claude Opus 4.5" },
  { id: "claude-sonnet-4-5", label: "Claude Sonnet 4.5" },
  { id: "claude-haiku-4-5", label: "Claude Haiku 4.5" },
];

const GEMINI_MODELS = [
  { id: "default", label: "Default (Gemini 3 Flash)" },
  { id: "gemini-3-pro-preview", label: "Gemini 3 Pro" },
  { id: "gemini-3-flash-preview", label: "Gemini 3 Flash" },
];

export function AgentConfigPanel({
  agentOverride,
  modelOverride,
  onAgentChange,
  onModelChange,
  disabled = false,
  compact = false,
  className,
}: AgentConfigPanelProps) {
  const selectedAgent = agentOverride || "default";
  const models = selectedAgent === "claude" ? CLAUDE_MODELS : GEMINI_MODELS;
  const selectedModel = modelOverride || "default";

  const handleAgentChange = (value: string) => {
    if (value === "default") {
      onAgentChange(null);
      onModelChange(null);
    } else {
      onAgentChange(value);
    }
  };

  const handleModelChange = (value: string) => {
    if (value === "default") {
      onModelChange(null);
    } else {
      onModelChange(value);
    }
  };

  if (compact) {
    return (
      <div className={clsx("flex items-center gap-2", disabled && "opacity-50 pointer-events-none", className)}>
        <Select value={selectedAgent} onValueChange={handleAgentChange}>
          <SelectTrigger className="h-8 min-w-[100px] text-xs">
            <SelectValue placeholder="Agent" />
          </SelectTrigger>
          <SelectContent>
            {AGENTS.map((agent) => (
              <SelectItem key={agent.id} value={agent.id}>
                <span className="flex items-center gap-1.5">
                  <agent.icon className="w-3 h-3" />
                  {agent.label}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {selectedAgent !== "default" && (
          <Select value={selectedModel} onValueChange={handleModelChange}>
            <SelectTrigger className="h-8 min-w-[120px] text-xs">
              <SelectValue placeholder="Model" />
            </SelectTrigger>
            <SelectContent>
              {models.map((model) => (
                <SelectItem key={model.id} value={model.id}>
                  {model.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>
    );
  }

  return (
    <div className={clsx("flex flex-col gap-3", disabled && "opacity-50 pointer-events-none", className)}>
      <h4 className="text-sm font-medium text-slate-200 flex items-center gap-2">
        <Settings2 className="w-4 h-4 text-slate-400" />
        Agent Configuration
      </h4>

      <div className="flex flex-col gap-2">
        <label className="text-xs text-slate-400">Agent Override</label>
        <Select value={selectedAgent} onValueChange={handleAgentChange}>
          <SelectTrigger className="w-full">
            <SelectValue placeholder="Select agent" />
          </SelectTrigger>
          <SelectContent>
            {AGENTS.map((agent) => (
              <SelectItem key={agent.id} value={agent.id}>
                <span className="flex items-center gap-2">
                  <agent.icon className="w-4 h-4" />
                  {agent.label}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {selectedAgent !== "default" && (
        <div className="flex flex-col gap-2">
          <label className="text-xs text-slate-400">Model Override</label>
          <Select value={selectedModel} onValueChange={handleModelChange}>
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Select model" />
            </SelectTrigger>
            <SelectContent>
              {models.map((model) => (
                <SelectItem key={model.id} value={model.id}>
                  {model.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {selectedAgent !== "default" && (
        <p className="text-xs text-slate-500">
          {selectedAgent === "claude" ? "Claude" : "Gemini"} will be used for
          vision, goals, and features extraction.
        </p>
      )}
    </div>
  );
}
