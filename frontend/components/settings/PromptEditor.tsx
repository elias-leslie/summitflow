"use client";

import { useState, useEffect } from "react";
import { clsx } from "clsx";
import { Bot, Sparkles, RotateCcw, Save, X, CheckCircle2, Loader2 } from "lucide-react";
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "../ui/select";
import { Switch } from "../ui/switch";
import { ExtractionPrompt, ExtractionPromptUpdate, ExtractionPromptType } from "@/lib/api";

interface PromptEditorProps {
  prompt: ExtractionPrompt;
  promptType: ExtractionPromptType;
  onSave: (config: ExtractionPromptUpdate) => Promise<void>;
  onResetToDefault: () => Promise<void>;
  disabled?: boolean;
  className?: string;
}

// Available agents and their models
const AGENTS = [
  { id: "claude", label: "Claude", icon: Sparkles },
  { id: "gemini", label: "Gemini", icon: Bot },
] as const;

const CLAUDE_MODELS = [
  { id: "claude-opus-4-5", label: "Claude Opus 4.5" },
  { id: "claude-sonnet-4-5", label: "Claude Sonnet 4.5" },
  { id: "claude-haiku-4-5", label: "Claude Haiku 4.5" },
];

const GEMINI_MODELS = [
  { id: "gemini-3-pro-preview", label: "Gemini 3 Pro" },
  { id: "gemini-3-flash-preview", label: "Gemini 3 Flash" },
];

// Prompt type labels
const PROMPT_TYPE_LABELS: Record<ExtractionPromptType, string> = {
  feature_extraction: "Feature Extraction",
  vision_extraction: "Vision Extraction",
  goals_extraction: "Goals Extraction",
};

export function PromptEditor({
  prompt,
  promptType,
  onSave,
  onResetToDefault,
  disabled = false,
  className,
}: PromptEditorProps) {
  // Local state for editing
  const [promptText, setPromptText] = useState(prompt.prompt_text);
  const [primaryAgent, setPrimaryAgent] = useState<"claude" | "gemini">(prompt.primary_agent);
  const [primaryModel, setPrimaryModel] = useState(prompt.primary_model);
  const [verificationEnabled, setVerificationEnabled] = useState(prompt.verification_enabled);
  const [verificationAgent, setVerificationAgent] = useState<"claude" | "gemini" | null>(
    prompt.verification_agent
  );
  const [verificationModel, setVerificationModel] = useState<string | null>(
    prompt.verification_model
  );
  const [verificationPrompt, setVerificationPrompt] = useState<string | null>(
    prompt.verification_prompt
  );

  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);

  // Track if user has made changes
  useEffect(() => {
    const changed =
      promptText !== prompt.prompt_text ||
      primaryAgent !== prompt.primary_agent ||
      primaryModel !== prompt.primary_model ||
      verificationEnabled !== prompt.verification_enabled ||
      verificationAgent !== prompt.verification_agent ||
      verificationModel !== prompt.verification_model ||
      verificationPrompt !== prompt.verification_prompt;
    setHasChanges(changed);
  }, [
    promptText,
    primaryAgent,
    primaryModel,
    verificationEnabled,
    verificationAgent,
    verificationModel,
    verificationPrompt,
    prompt,
  ]);

  // Reset local state when prompt changes
  useEffect(() => {
    setPromptText(prompt.prompt_text);
    setPrimaryAgent(prompt.primary_agent);
    setPrimaryModel(prompt.primary_model);
    setVerificationEnabled(prompt.verification_enabled);
    setVerificationAgent(prompt.verification_agent);
    setVerificationModel(prompt.verification_model);
    setVerificationPrompt(prompt.verification_prompt);
  }, [prompt]);

  const handleAgentChange = (agent: "claude" | "gemini") => {
    setPrimaryAgent(agent);
    // Reset model to first available for this agent
    const models = agent === "claude" ? CLAUDE_MODELS : GEMINI_MODELS;
    setPrimaryModel(models[0].id);
  };

  const handleVerificationAgentChange = (agent: "claude" | "gemini") => {
    setVerificationAgent(agent);
    const models = agent === "claude" ? CLAUDE_MODELS : GEMINI_MODELS;
    setVerificationModel(models[0].id);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave({
        prompt_text: promptText,
        primary_agent: primaryAgent,
        primary_model: primaryModel,
        verification_enabled: verificationEnabled,
        verification_agent: verificationEnabled ? verificationAgent : null,
        verification_model: verificationEnabled ? verificationModel : null,
        verification_prompt: verificationEnabled ? verificationPrompt : null,
      });
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    setResetting(true);
    try {
      await onResetToDefault();
    } finally {
      setResetting(false);
    }
  };

  const handleCancel = () => {
    // Reset to original values
    setPromptText(prompt.prompt_text);
    setPrimaryAgent(prompt.primary_agent);
    setPrimaryModel(prompt.primary_model);
    setVerificationEnabled(prompt.verification_enabled);
    setVerificationAgent(prompt.verification_agent);
    setVerificationModel(prompt.verification_model);
    setVerificationPrompt(prompt.verification_prompt);
  };

  const primaryModels = primaryAgent === "claude" ? CLAUDE_MODELS : GEMINI_MODELS;
  const verificationModels =
    verificationAgent === "claude" ? CLAUDE_MODELS : GEMINI_MODELS;

  return (
    <div
      className={clsx(
        "flex flex-col gap-4 p-4 bg-slate-800/50 rounded-lg border border-slate-700",
        disabled && "opacity-50 pointer-events-none",
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-slate-200">
          {PROMPT_TYPE_LABELS[promptType]}
        </h3>
        <div className="flex items-center gap-2">
          {prompt.is_default ? (
            <span className="text-xs px-2 py-0.5 bg-slate-700 text-slate-300 rounded">
              Default
            </span>
          ) : (
            <span className="text-xs px-2 py-0.5 bg-blue-900/50 text-blue-300 rounded flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" />
              Custom
            </span>
          )}
        </div>
      </div>

      {/* Prompt Text */}
      <div className="flex flex-col gap-2">
        <label className="text-xs text-slate-400">Prompt Text</label>
        <textarea
          value={promptText}
          onChange={(e) => setPromptText(e.target.value)}
          rows={6}
          className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-md text-sm text-slate-200
                     placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent
                     resize-y min-h-[120px]"
          placeholder="Enter the extraction prompt..."
        />
      </div>

      {/* Primary Agent/Model */}
      <div className="grid grid-cols-2 gap-4">
        <div className="flex flex-col gap-2">
          <label className="text-xs text-slate-400">Primary Agent</label>
          <Select value={primaryAgent} onValueChange={(v) => handleAgentChange(v as "claude" | "gemini")}>
            <SelectTrigger className="w-full">
              <SelectValue />
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

        <div className="flex flex-col gap-2">
          <label className="text-xs text-slate-400">Model</label>
          <Select value={primaryModel} onValueChange={setPrimaryModel}>
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {primaryModels.map((model) => (
                <SelectItem key={model.id} value={model.id}>
                  {model.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Verification Toggle */}
      <div className="flex items-center justify-between py-2 border-t border-slate-700">
        <div>
          <p className="text-sm text-slate-200">Enable Verification</p>
          <p className="text-xs text-slate-500">
            Use a second agent to verify/refine extraction results
          </p>
        </div>
        <Switch
          checked={verificationEnabled}
          onCheckedChange={setVerificationEnabled}
        />
      </div>

      {/* Verification Fields (conditional) */}
      {verificationEnabled && (
        <div className="flex flex-col gap-4 pl-4 border-l-2 border-slate-600">
          <div className="grid grid-cols-2 gap-4">
            <div className="flex flex-col gap-2">
              <label className="text-xs text-slate-400">Verification Agent</label>
              <Select
                value={verificationAgent || "claude"}
                onValueChange={(v) => handleVerificationAgentChange(v as "claude" | "gemini")}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
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

            <div className="flex flex-col gap-2">
              <label className="text-xs text-slate-400">Verification Model</label>
              <Select
                value={verificationModel || verificationModels[0].id}
                onValueChange={setVerificationModel}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {verificationModels.map((model) => (
                    <SelectItem key={model.id} value={model.id}>
                      {model.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <label className="text-xs text-slate-400">Verification Prompt</label>
            <textarea
              value={verificationPrompt || ""}
              onChange={(e) => setVerificationPrompt(e.target.value || null)}
              rows={4}
              className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded-md text-sm text-slate-200
                         placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent
                         resize-y min-h-[80px]"
              placeholder="Enter the verification prompt (optional)..."
            />
          </div>
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex items-center justify-between pt-4 border-t border-slate-700">
        <button
          onClick={handleReset}
          disabled={resetting || prompt.is_default}
          className={clsx(
            "flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md transition-colors",
            prompt.is_default
              ? "text-slate-500 cursor-not-allowed"
              : "text-slate-400 hover:text-slate-200 hover:bg-slate-700"
          )}
        >
          {resetting ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <RotateCcw className="w-4 h-4" />
          )}
          Reset to Default
        </button>

        <div className="flex items-center gap-2">
          {hasChanges && (
            <button
              onClick={handleCancel}
              disabled={saving}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-slate-400 hover:text-slate-200
                         hover:bg-slate-700 rounded-md transition-colors"
            >
              <X className="w-4 h-4" />
              Cancel
            </button>
          )}

          <button
            onClick={handleSave}
            disabled={saving || !hasChanges}
            className={clsx(
              "flex items-center gap-1.5 px-4 py-1.5 text-sm rounded-md transition-colors",
              hasChanges
                ? "bg-blue-600 text-white hover:bg-blue-500"
                : "bg-slate-700 text-slate-500 cursor-not-allowed"
            )}
          >
            {saving ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
