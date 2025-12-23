"use client";

import { useState, useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import dynamic from "next/dynamic";
import {
  X,
  Save,
  RotateCcw,
  Sparkles,
  Wrench,
  AlertCircle,
  Check,
} from "lucide-react";
import clsx from "clsx";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  updatePrompt,
  deletePrompt,
  type Prompt,
  type PromptUpdate,
  type PromptCategory,
} from "@/lib/api";

// Dynamic import Monaco to avoid SSR issues
const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => <Skeleton className="h-[300px] w-full" />,
});

interface PromptEditorProps {
  prompt: Prompt;
  projectId: string;
  defaultPrompt?: Prompt;
  onClose: () => void;
}

const AVAILABLE_TOOLS = [
  "read_file",
  "write_file",
  "glob",
  "grep",
  "bash",
  "edit",
];

const CATEGORIES: PromptCategory[] = ["spec", "recovery", "qa", "extraction"];

export function PromptEditor({
  prompt,
  projectId,
  defaultPrompt,
  onClose,
}: PromptEditorProps) {
  const queryClient = useQueryClient();

  const [promptText, setPromptText] = useState(prompt.prompt_text);
  const [category, setCategory] = useState<PromptCategory>(prompt.category);
  const [thinkingBudget, setThinkingBudget] = useState(prompt.thinking_budget);
  const [toolsEnabled, setToolsEnabled] = useState<string[]>(
    prompt.tools_enabled
  );
  const [primaryAgent, setPrimaryAgent] = useState(prompt.primary_agent);
  const [primaryModel, setPrimaryModel] = useState(prompt.primary_model);
  const [showDiff, setShowDiff] = useState(false);

  const hasChanges = useMemo(() => {
    return (
      promptText !== prompt.prompt_text ||
      category !== prompt.category ||
      thinkingBudget !== prompt.thinking_budget ||
      JSON.stringify(toolsEnabled) !== JSON.stringify(prompt.tools_enabled) ||
      primaryAgent !== prompt.primary_agent ||
      primaryModel !== prompt.primary_model
    );
  }, [
    promptText,
    category,
    thinkingBudget,
    toolsEnabled,
    primaryAgent,
    primaryModel,
    prompt,
  ]);

  const isModifiedFromDefault = useMemo(() => {
    if (!defaultPrompt) return !prompt.is_default;
    return (
      promptText !== defaultPrompt.prompt_text ||
      category !== defaultPrompt.category ||
      thinkingBudget !== defaultPrompt.thinking_budget ||
      JSON.stringify(toolsEnabled) !==
        JSON.stringify(defaultPrompt.tools_enabled)
    );
  }, [promptText, category, thinkingBudget, toolsEnabled, defaultPrompt, prompt]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const update: PromptUpdate = {
        prompt_text: promptText,
        category,
        thinking_budget: thinkingBudget,
        tools_enabled: toolsEnabled,
        primary_agent: primaryAgent,
        primary_model: primaryModel,
      };
      return updatePrompt(projectId, prompt.prompt_type, update);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["prompts", projectId] });
      onClose();
    },
  });

  const resetMutation = useMutation({
    mutationFn: async () => {
      return deletePrompt(projectId, prompt.prompt_type);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["prompts", projectId] });
      onClose();
    },
  });

  const toggleTool = (tool: string) => {
    setToolsEnabled((prev) =>
      prev.includes(tool) ? prev.filter((t) => t !== tool) : [...prev, tool]
    );
  };

  const formatPromptType = (type: string) => {
    return type
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
      <div className="bg-slate-900 rounded-lg border border-slate-700 max-w-4xl w-full max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-slate-700 flex items-center justify-between flex-shrink-0">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-white">
              {formatPromptType(prompt.prompt_type)}
            </h2>
            {prompt.is_default ? (
              <Badge
                variant="outline"
                className="text-slate-500 border-slate-600"
              >
                Default
              </Badge>
            ) : (
              <Badge className="bg-phosphor-500/20 text-phosphor-400 border-phosphor-500/30">
                Custom
              </Badge>
            )}
            {hasChanges && (
              <Badge className="bg-amber-500/20 text-amber-400 border-amber-500/30">
                Unsaved
              </Badge>
            )}
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white p-1"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto p-4 space-y-6">
          {/* Metadata Row */}
          <div className="grid grid-cols-4 gap-4">
            <div>
              <Label className="text-xs text-slate-500 uppercase">
                Category
              </Label>
              <Select
                value={category}
                onValueChange={(v) => setCategory(v as PromptCategory)}
              >
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORIES.map((cat) => (
                    <SelectItem key={cat} value={cat}>
                      {cat.charAt(0).toUpperCase() + cat.slice(1)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="text-xs text-slate-500 uppercase">
                Thinking Budget
              </Label>
              <div className="relative mt-1">
                <Sparkles className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-amber-400" />
                <Input
                  type="number"
                  value={thinkingBudget}
                  onChange={(e) =>
                    setThinkingBudget(parseInt(e.target.value) || 0)
                  }
                  className="pl-9"
                  min={0}
                  max={100000}
                  step={1000}
                />
              </div>
            </div>

            <div>
              <Label className="text-xs text-slate-500 uppercase">Agent</Label>
              <Select value={primaryAgent} onValueChange={setPrimaryAgent}>
                <SelectTrigger className="mt-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="claude">Claude</SelectItem>
                  <SelectItem value="gemini">Gemini</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="text-xs text-slate-500 uppercase">Model</Label>
              <Input
                value={primaryModel}
                onChange={(e) => setPrimaryModel(e.target.value)}
                className="mt-1"
                placeholder="claude-sonnet-4-5"
              />
            </div>
          </div>

          {/* Tools */}
          <div>
            <Label className="text-xs text-slate-500 uppercase flex items-center gap-2">
              <Wrench className="w-3.5 h-3.5" />
              Tools Enabled
            </Label>
            <div className="flex gap-2 mt-2 flex-wrap">
              {AVAILABLE_TOOLS.map((tool) => (
                <button
                  key={tool}
                  onClick={() => toggleTool(tool)}
                  className={clsx(
                    "px-3 py-1.5 rounded text-sm font-medium transition-all",
                    toolsEnabled.includes(tool)
                      ? "bg-phosphor-500/20 text-phosphor-400 border border-phosphor-500/30"
                      : "bg-slate-800 text-slate-500 border border-slate-700 hover:border-slate-500"
                  )}
                >
                  {tool}
                </button>
              ))}
            </div>
          </div>

          {/* Prompt Text Editor with Monaco */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <Label className="text-xs text-slate-500 uppercase">
                Prompt Text
              </Label>
              {defaultPrompt && isModifiedFromDefault && (
                <button
                  onClick={() => setShowDiff(!showDiff)}
                  className="text-xs text-slate-400 hover:text-white"
                >
                  {showDiff ? "Hide" : "Show"} diff from default
                </button>
              )}
            </div>

            {showDiff && defaultPrompt ? (
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-xs text-slate-500 mb-1">Default</div>
                  <div className="rounded border border-slate-700 overflow-hidden">
                    <MonacoEditor
                      height="300px"
                      defaultLanguage="markdown"
                      value={defaultPrompt.prompt_text}
                      theme="vs-dark"
                      options={{
                        readOnly: true,
                        minimap: { enabled: false },
                        fontSize: 12,
                        lineNumbers: "off",
                        wordWrap: "on",
                        scrollBeyondLastLine: false,
                        padding: { top: 12, bottom: 12 },
                      }}
                    />
                  </div>
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">Current</div>
                  <div className="rounded border border-slate-700 overflow-hidden">
                    <MonacoEditor
                      height="300px"
                      defaultLanguage="markdown"
                      value={promptText}
                      onChange={(value) => setPromptText(value || "")}
                      theme="vs-dark"
                      options={{
                        minimap: { enabled: false },
                        fontSize: 12,
                        lineNumbers: "off",
                        wordWrap: "on",
                        scrollBeyondLastLine: false,
                        padding: { top: 12, bottom: 12 },
                      }}
                    />
                  </div>
                </div>
              </div>
            ) : (
              <div className="rounded border border-slate-700 overflow-hidden">
                <MonacoEditor
                  height="300px"
                  defaultLanguage="markdown"
                  value={promptText}
                  onChange={(value) => setPromptText(value || "")}
                  theme="vs-dark"
                  options={{
                    minimap: { enabled: false },
                    fontSize: 13,
                    lineNumbers: "off",
                    wordWrap: "on",
                    scrollBeyondLastLine: false,
                    padding: { top: 12, bottom: 12 },
                  }}
                />
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-slate-700 flex items-center justify-between flex-shrink-0">
          <div>
            {!prompt.is_default && (
              <Button
                variant="outline"
                onClick={() => resetMutation.mutate()}
                disabled={resetMutation.isPending}
                className="text-amber-400 border-amber-500/30 hover:bg-amber-500/10"
              >
                <RotateCcw className="w-4 h-4 mr-1.5" />
                Reset to Default
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button
              onClick={() => saveMutation.mutate()}
              disabled={!hasChanges || saveMutation.isPending}
            >
              {saveMutation.isPending ? (
                <div className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-1.5" />
              ) : (
                <Save className="w-4 h-4 mr-1.5" />
              )}
              Save Changes
            </Button>
          </div>
        </div>

        {/* Error/Success Messages */}
        {saveMutation.isError && (
          <div className="p-3 bg-rose-500/10 border-t border-rose-500/30 text-rose-400 text-sm flex items-center gap-2">
            <AlertCircle className="w-4 h-4" />
            Failed to save prompt
          </div>
        )}
        {saveMutation.isSuccess && (
          <div className="p-3 bg-phosphor-500/10 border-t border-phosphor-500/30 text-phosphor-400 text-sm flex items-center gap-2">
            <Check className="w-4 h-4" />
            Prompt saved successfully
          </div>
        )}
      </div>
    </div>
  );
}
