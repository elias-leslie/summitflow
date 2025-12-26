"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Lightbulb, Plus, Loader2, FolderTree, Globe, FileCode } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  fetchComponentSuggestions,
  getAgentConfig,
  createTddComponent,
  type ComponentSuggestion,
} from "@/lib/api";

interface ComponentSuggestionsProps {
  projectId: string;
  onComponentCreated?: () => void;
}

const TYPE_ICONS = {
  page_group: Globe,
  endpoint_group: FileCode,
  directory: FolderTree,
} as const;

const TYPE_LABELS = {
  page_group: "Pages",
  endpoint_group: "Endpoints",
  directory: "Directory",
} as const;

export function ComponentSuggestions({
  projectId,
  onComponentCreated,
}: ComponentSuggestionsProps) {
  const [creatingId, setCreatingId] = useState<string | null>(null);

  // Fetch agent config to get component_source setting
  const { data: agentConfig, isLoading: configLoading } = useQuery({
    queryKey: ["agent-config", projectId],
    queryFn: () => getAgentConfig(projectId),
  });

  const componentSource = agentConfig?.component_source || "manual";

  // Fetch suggestions based on source setting
  const { data: suggestions = [], isLoading: suggestionsLoading } = useQuery({
    queryKey: ["component-suggestions", projectId, componentSource],
    queryFn: () => fetchComponentSuggestions(projectId, componentSource),
    enabled: componentSource !== "manual",
  });

  const handleCreateFromSuggestion = async (suggestion: ComponentSuggestion) => {
    const suggestionKey = `${suggestion.type}-${suggestion.path}`;
    setCreatingId(suggestionKey);

    try {
      // Generate component_id from suggested name
      const componentId = suggestion.suggested_name
        .toLowerCase()
        .replace(/[^a-z0-9\s]/g, "")
        .replace(/\s+/g, "_")
        .slice(0, 50);

      await createTddComponent(projectId, {
        component_id: componentId,
        name: suggestion.suggested_name,
        description: `Auto-created from ${TYPE_LABELS[suggestion.type].toLowerCase()} at ${suggestion.path}`,
        explorer_entry_id: suggestion.entries[0]?.id,
      });

      onComponentCreated?.();
    } catch {
      console.error("Failed to create component from suggestion");
    } finally {
      setCreatingId(null);
    }
  };

  // Don't show anything in manual mode
  if (componentSource === "manual") {
    return null;
  }

  if (configLoading || suggestionsLoading) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
        <div className="flex items-center gap-2 text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span className="text-sm">Loading suggestions...</span>
        </div>
      </div>
    );
  }

  if (suggestions.length === 0) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
        <div className="flex items-center gap-2 text-slate-500">
          <Lightbulb className="h-4 w-4" />
          <span className="text-sm">
            No suggestions available for {componentSource} source. Try running a scan.
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/50">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-700">
        <Lightbulb className="h-4 w-4 text-amber-400" />
        <span className="text-sm font-medium text-slate-200">
          Component Suggestions
        </span>
        <span className="text-xs text-slate-500">
          ({suggestions.length} from {componentSource})
        </span>
      </div>

      <div className="divide-y divide-slate-700/50">
        {suggestions.slice(0, 5).map((suggestion) => {
          const Icon = TYPE_ICONS[suggestion.type];
          const suggestionKey = `${suggestion.type}-${suggestion.path}`;
          const isCreating = creatingId === suggestionKey;

          return (
            <div
              key={suggestionKey}
              className="flex items-center justify-between px-4 py-3 hover:bg-slate-800/50 transition-colors"
            >
              <div className="flex items-center gap-3 min-w-0">
                <Icon className="h-4 w-4 text-slate-400 shrink-0" />
                <div className="min-w-0">
                  <div className="text-sm font-medium text-slate-200 truncate">
                    {suggestion.suggested_name}
                  </div>
                  <div className="text-xs text-slate-500 truncate">
                    {suggestion.path} ({suggestion.entry_count} items)
                  </div>
                </div>
              </div>

              <Button
                size="sm"
                variant="ghost"
                onClick={() => handleCreateFromSuggestion(suggestion)}
                disabled={isCreating}
                className="shrink-0 text-phosphor-400 hover:text-phosphor-300 hover:bg-phosphor-500/10"
              >
                {isCreating ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Plus className="h-4 w-4" />
                )}
                <span className="ml-1.5">Create</span>
              </Button>
            </div>
          );
        })}
      </div>

      {suggestions.length > 5 && (
        <div className="px-4 py-2 border-t border-slate-700 text-xs text-slate-500">
          +{suggestions.length - 5} more suggestions available
        </div>
      )}
    </div>
  );
}
