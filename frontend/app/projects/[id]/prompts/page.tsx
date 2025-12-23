"use client";

import { useState, useMemo } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Brain,
  Wrench,
  FileCode,
  FlaskConical,
  RefreshCw,
  ChevronRight,
  Sparkles,
} from "lucide-react";
import clsx from "clsx";

import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { fetchPrompts, type Prompt, type PromptCategory } from "@/lib/api";

interface TabConfig {
  id: PromptCategory;
  label: string;
  icon: React.ElementType;
  color: string;
}

const tabs: TabConfig[] = [
  { id: "spec", label: "Spec Pipeline", icon: FileCode, color: "emerald" },
  { id: "recovery", label: "Recovery", icon: Wrench, color: "orange" },
  { id: "qa", label: "QA", icon: FlaskConical, color: "cyan" },
  { id: "extraction", label: "Extraction", icon: Brain, color: "purple" },
];

function PromptsPageSkeleton() {
  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        {tabs.map((_, i) => (
          <Skeleton key={i} className="h-10 w-32" />
        ))}
      </div>
      <div className="space-y-3">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-24 w-full rounded-lg" />
        ))}
      </div>
    </div>
  );
}

function PromptCard({
  prompt,
  onClick,
}: {
  prompt: Prompt;
  onClick: () => void;
}) {
  const formatPromptType = (type: string) => {
    return type
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  };

  return (
    <button
      onClick={onClick}
      className={clsx(
        "w-full text-left p-4 rounded-lg border transition-all duration-200",
        "bg-slate-900/50 border-slate-700",
        "hover:border-slate-500 hover:bg-slate-800/50"
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-sm font-medium text-white truncate">
              {formatPromptType(prompt.prompt_type)}
            </h3>
            {prompt.is_default ? (
              <Badge variant="outline" className="text-slate-500 border-slate-600 text-xs">
                Default
              </Badge>
            ) : (
              <Badge className="bg-phosphor-500/20 text-phosphor-400 border-phosphor-500/30 text-xs">
                Custom
              </Badge>
            )}
          </div>
          <p className="text-xs text-slate-500 line-clamp-2">
            {prompt.prompt_text.slice(0, 150)}...
          </p>
        </div>
        <div className="flex items-center gap-4 flex-shrink-0">
          {prompt.thinking_budget > 0 && (
            <div className="flex items-center gap-1.5 text-xs text-slate-400">
              <Sparkles className="w-3.5 h-3.5 text-amber-400" />
              <span>{(prompt.thinking_budget / 1000).toFixed(0)}k</span>
            </div>
          )}
          {prompt.tools_enabled.length > 0 && (
            <div className="flex items-center gap-1.5 text-xs text-slate-400">
              <Wrench className="w-3.5 h-3.5" />
              <span>{prompt.tools_enabled.length}</span>
            </div>
          )}
          <ChevronRight className="w-4 h-4 text-slate-500" />
        </div>
      </div>
    </button>
  );
}

export default function PromptsPage() {
  const params = useParams();
  const projectId = params.id as string;
  const [activeTab, setActiveTab] = useState<PromptCategory>("spec");
  const [selectedPrompt, setSelectedPrompt] = useState<Prompt | null>(null);

  const {
    data: prompts = [],
    isLoading,
    refetch,
  } = useQuery({
    queryKey: ["prompts", projectId],
    queryFn: () => fetchPrompts(projectId),
  });

  const groupedPrompts = useMemo(() => {
    const groups: Record<PromptCategory, Prompt[]> = {
      spec: [],
      recovery: [],
      qa: [],
      extraction: [],
    };
    for (const prompt of prompts) {
      const cat = prompt.category as PromptCategory;
      if (groups[cat]) {
        groups[cat].push(prompt);
      }
    }
    return groups;
  }, [prompts]);

  const currentPrompts = groupedPrompts[activeTab] || [];

  if (isLoading) {
    return (
      <div className="h-full overflow-auto p-4">
        <PromptsPageSkeleton />
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto p-4 space-y-4">
      {/* Category Tabs */}
      <div className="flex items-center gap-2 flex-wrap">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          const count = groupedPrompts[tab.id].length;

          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={clsx(
                "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all",
                isActive
                  ? `bg-${tab.color}-500/15 text-${tab.color}-400`
                  : "text-slate-500 hover:text-slate-300 hover:bg-slate-800"
              )}
              style={
                isActive
                  ? {
                      backgroundColor: `rgb(var(--${tab.color}-500) / 0.15)`,
                      color: `rgb(var(--${tab.color}-400))`,
                    }
                  : undefined
              }
            >
              <Icon className="w-4 h-4" />
              <span>{tab.label}</span>
              {count > 0 && (
                <span
                  className={clsx(
                    "px-1.5 py-0.5 rounded text-xs",
                    isActive ? "bg-white/10" : "bg-slate-700"
                  )}
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}

        <div className="flex-1" />

        <Button variant="outline" size="sm" onClick={() => refetch()}>
          <RefreshCw className="h-4 w-4 mr-1.5" />
          Refresh
        </Button>
      </div>

      {/* Results count */}
      <div className="text-sm text-slate-500">
        {currentPrompts.length > 0
          ? `${currentPrompts.length} prompt${currentPrompts.length !== 1 ? "s" : ""} in ${
              tabs.find((t) => t.id === activeTab)?.label
            }`
          : `No prompts in ${tabs.find((t) => t.id === activeTab)?.label}`}
      </div>

      {/* Prompts List */}
      <div className="space-y-3">
        {currentPrompts.map((prompt) => (
          <PromptCard
            key={prompt.prompt_type}
            prompt={prompt}
            onClick={() => setSelectedPrompt(prompt)}
          />
        ))}
      </div>

      {/* Selected Prompt Detail (simple for now, PromptEditor in task 16.6) */}
      {selectedPrompt && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
          <div className="bg-slate-900 rounded-lg border border-slate-700 max-w-2xl w-full max-h-[80vh] overflow-auto">
            <div className="p-4 border-b border-slate-700 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">
                {selectedPrompt.prompt_type
                  .split("_")
                  .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
                  .join(" ")}
              </h2>
              <button
                onClick={() => setSelectedPrompt(null)}
                className="text-slate-400 hover:text-white"
              >
                Close
              </button>
            </div>
            <div className="p-4 space-y-4">
              <div>
                <label className="text-xs text-slate-500 uppercase tracking-wide">
                  Category
                </label>
                <p className="text-sm text-slate-300">{selectedPrompt.category}</p>
              </div>
              <div>
                <label className="text-xs text-slate-500 uppercase tracking-wide">
                  Thinking Budget
                </label>
                <p className="text-sm text-slate-300">
                  {selectedPrompt.thinking_budget.toLocaleString()} tokens
                </p>
              </div>
              {selectedPrompt.tools_enabled.length > 0 && (
                <div>
                  <label className="text-xs text-slate-500 uppercase tracking-wide">
                    Tools Enabled
                  </label>
                  <div className="flex gap-1 mt-1">
                    {selectedPrompt.tools_enabled.map((tool) => (
                      <Badge key={tool} variant="outline" className="text-xs">
                        {tool}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
              <div>
                <label className="text-xs text-slate-500 uppercase tracking-wide">
                  Prompt Text
                </label>
                <pre className="mt-1 p-3 bg-slate-800 rounded text-xs text-slate-300 whitespace-pre-wrap overflow-auto max-h-[300px]">
                  {selectedPrompt.prompt_text}
                </pre>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
