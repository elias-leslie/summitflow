"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Settings2, Download, FileText, Loader2, Layers } from "lucide-react";
import Link from "next/link";
import { clsx } from "clsx";
import {
  fetchProject,
  getExtractionPrompts,
  updateExtractionPrompt,
  deleteExtractionPrompt,
  exportExtractionPrompts,
  getAgentConfig,
  updateAgentConfig,
  type ExtractionPrompt,
  type ExtractionPromptType,
  type ExtractionPromptUpdate,
} from "@/lib/api";
import { PromptEditor } from "@/components/settings/PromptEditor";
import { AgentConfigPanel } from "@/components/settings/AgentConfigPanel";
import { ExtractionThrottlePanel } from "@/components/settings/ExtractionThrottlePanel";

type SettingsTab = "prompts" | "defaults";

const COMPONENT_SOURCE_OPTIONS = [
  { value: "manual", label: "Manual", description: "Create components manually in the UI" },
  { value: "pages", label: "Pages", description: "Suggest components from ungrouped pages" },
  { value: "endpoints", label: "Endpoints", description: "Suggest components from API endpoint groups" },
  { value: "directories", label: "Directories", description: "Suggest components from directory structure" },
] as const;

export default function ProjectSettingsPage() {
  const params = useParams();
  const projectId = params.id as string;
  const queryClient = useQueryClient();

  const [activeTab, setActiveTab] = useState<SettingsTab>("prompts");
  const [exporting, setExporting] = useState(false);
  const [savingComponentSource, setSavingComponentSource] = useState(false);
  const [savingExtraction, setSavingExtraction] = useState(false);

  // Fetch project details
  const { data: project, isLoading: projectLoading } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => fetchProject(projectId),
  });

  // Fetch extraction prompts
  const {
    data: prompts,
    isLoading: promptsLoading,
    refetch: refetchPrompts,
  } = useQuery({
    queryKey: ["extraction-prompts", projectId],
    queryFn: () => getExtractionPrompts(projectId),
  });

  // Fetch agent config
  const { data: agentConfig, isLoading: configLoading } = useQuery({
    queryKey: ["agent-config", projectId],
    queryFn: () => getAgentConfig(projectId),
  });

  // Agent config state (for defaults tab)
  const [defaultAgent, setDefaultAgent] = useState<string | null>(null);
  const [defaultModel, setDefaultModel] = useState<string | null>(null);

  const handleComponentSourceChange = async (source: string) => {
    setSavingComponentSource(true);
    try {
      await updateAgentConfig(projectId, { component_source: source });
      queryClient.invalidateQueries({ queryKey: ["agent-config", projectId] });
    } finally {
      setSavingComponentSource(false);
    }
  };

  const handleExtractionEnabledChange = async (enabled: boolean) => {
    setSavingExtraction(true);
    try {
      await updateAgentConfig(projectId, { extraction_enabled: enabled });
      queryClient.invalidateQueries({ queryKey: ["agent-config", projectId] });
    } finally {
      setSavingExtraction(false);
    }
  };

  const handleExtractionRpmChange = async (rpm: number) => {
    setSavingExtraction(true);
    try {
      await updateAgentConfig(projectId, { extraction_rpm_limit: rpm });
      queryClient.invalidateQueries({ queryKey: ["agent-config", projectId] });
    } finally {
      setSavingExtraction(false);
    }
  };

  const handleSavePrompt = async (
    promptType: ExtractionPromptType,
    config: ExtractionPromptUpdate
  ) => {
    await updateExtractionPrompt(projectId, promptType, config);
    refetchPrompts();
  };

  const handleResetPrompt = async (promptType: ExtractionPromptType) => {
    await deleteExtractionPrompt(projectId, promptType);
    refetchPrompts();
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      const exportData = await exportExtractionPrompts(projectId);

      // Create and download JSON file
      const blob = new Blob([JSON.stringify(exportData, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${projectId}-extraction-prompts.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  };

  const getPromptByType = (type: ExtractionPromptType): ExtractionPrompt | undefined => {
    return prompts?.find((p) => p.prompt_type === type);
  };

  if (projectLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
      </div>
    );
  }

  if (!project) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <p className="text-slate-400">Project not found</p>
        <Link href="/" className="text-blue-400 hover:text-blue-300">
          Back to dashboard
        </Link>
      </div>
    );
  }

  return (
    <main className="content-container py-8">
      {/* Header */}
      <header className="mb-8">
        <div className="flex items-center gap-4 mb-4">
          <Link
            href={`/projects/${projectId}`}
            className="text-slate-400 hover:text-slate-200 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="text-2xl font-semibold text-slate-100 flex items-center gap-3">
              <Settings2 className="w-6 h-6 text-slate-400" />
              Project Settings
            </h1>
            <p className="text-sm text-slate-400 mt-1">{project.name}</p>
          </div>
        </div>
      </header>

      {/* Tab Navigation */}
      <nav className="border-b border-slate-700 mb-6">
        <div className="flex gap-1">
          <button
            onClick={() => setActiveTab("prompts")}
            className={clsx(
              "px-4 py-2.5 text-sm font-medium transition-colors relative",
              activeTab === "prompts"
                ? "text-phosphor-400"
                : "text-slate-500 hover:text-slate-300"
            )}
          >
            <div className="flex items-center gap-2">
              <FileText className="w-4 h-4" />
              Extraction Prompts
            </div>
            {activeTab === "prompts" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-phosphor-500" />
            )}
          </button>
          <button
            onClick={() => setActiveTab("defaults")}
            className={clsx(
              "px-4 py-2.5 text-sm font-medium transition-colors relative",
              activeTab === "defaults"
                ? "text-phosphor-400"
                : "text-slate-500 hover:text-slate-300"
            )}
          >
            <div className="flex items-center gap-2">
              <Settings2 className="w-4 h-4" />
              Agent Defaults
            </div>
            {activeTab === "defaults" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-phosphor-500" />
            )}
          </button>
        </div>
      </nav>

      {/* Tab Content */}
      <section className="animate-fade-in">
        {activeTab === "prompts" && (
          <div className="space-y-6">
            {/* Export Button */}
            <div className="flex justify-end">
              <button
                onClick={handleExport}
                disabled={exporting}
                className="flex items-center gap-2 px-4 py-2 text-sm bg-slate-700 text-slate-200
                           hover:bg-slate-600 rounded-md transition-colors disabled:opacity-50"
              >
                {exporting ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Download className="w-4 h-4" />
                )}
                Export Prompts
              </button>
            </div>

            {/* Prompt Editors */}
            {promptsLoading ? (
              <div className="flex items-center justify-center h-64">
                <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
              </div>
            ) : (
              <div className="space-y-6">
                {/* Feature Extraction */}
                {getPromptByType("feature_extraction") && (
                  <PromptEditor
                    prompt={getPromptByType("feature_extraction")!}
                    promptType="feature_extraction"
                    onSave={(config) => handleSavePrompt("feature_extraction", config)}
                    onResetToDefault={() => handleResetPrompt("feature_extraction")}
                  />
                )}

                {/* Vision Extraction */}
                {getPromptByType("vision_extraction") && (
                  <PromptEditor
                    prompt={getPromptByType("vision_extraction")!}
                    promptType="vision_extraction"
                    onSave={(config) => handleSavePrompt("vision_extraction", config)}
                    onResetToDefault={() => handleResetPrompt("vision_extraction")}
                  />
                )}

                {/* Goals Extraction */}
                {getPromptByType("goals_extraction") && (
                  <PromptEditor
                    prompt={getPromptByType("goals_extraction")!}
                    promptType="goals_extraction"
                    onSave={(config) => handleSavePrompt("goals_extraction", config)}
                    onResetToDefault={() => handleResetPrompt("goals_extraction")}
                  />
                )}
              </div>
            )}
          </div>
        )}

        {activeTab === "defaults" && (
          <div className="max-w-xl space-y-6">
            {/* Extraction Throttle - Primary cost control */}
            {configLoading ? (
              <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
                </div>
              </div>
            ) : (
              <ExtractionThrottlePanel
                enabled={agentConfig?.extraction_enabled ?? true}
                rpmLimit={agentConfig?.extraction_rpm_limit ?? 10}
                onEnabledChange={handleExtractionEnabledChange}
                onRpmChange={handleExtractionRpmChange}
                saving={savingExtraction}
              />
            )}

            {/* Component Source Setting */}
            <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
              <h3 className="text-sm font-medium text-slate-200 mb-2 flex items-center gap-2">
                <Layers className="w-4 h-4 text-slate-400" />
                Component Source
              </h3>
              <p className="text-xs text-slate-400 mb-4">
                Choose how component suggestions are generated for this project.
              </p>
              {configLoading ? (
                <div className="flex items-center justify-center py-4">
                  <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
                </div>
              ) : (
                <div className="space-y-2">
                  {COMPONENT_SOURCE_OPTIONS.map((option) => (
                    <label
                      key={option.value}
                      className={clsx(
                        "flex items-start gap-3 p-3 rounded-md border cursor-pointer transition-colors",
                        agentConfig?.component_source === option.value
                          ? "border-phosphor-500 bg-phosphor-500/10"
                          : "border-slate-600 hover:border-slate-500 bg-slate-800/50"
                      )}
                    >
                      <input
                        type="radio"
                        name="component_source"
                        value={option.value}
                        checked={agentConfig?.component_source === option.value}
                        onChange={() => handleComponentSourceChange(option.value)}
                        disabled={savingComponentSource}
                        className="mt-0.5 accent-phosphor-500"
                      />
                      <div className="flex-1">
                        <div className="text-sm font-medium text-slate-200">
                          {option.label}
                        </div>
                        <div className="text-xs text-slate-400">
                          {option.description}
                        </div>
                      </div>
                      {savingComponentSource && agentConfig?.component_source !== option.value && (
                        <Loader2 className="w-4 h-4 animate-spin text-slate-400" />
                      )}
                    </label>
                  ))}
                </div>
              )}
            </div>

            {/* Agent Defaults */}
            <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
              <h3 className="text-sm font-medium text-slate-200 mb-4">
                Default Agent Configuration
              </h3>
              <p className="text-xs text-slate-400 mb-4">
                These settings apply to new roundtable sessions. Each session can override
                these defaults.
              </p>
              <AgentConfigPanel
                agentOverride={defaultAgent}
                modelOverride={defaultModel}
                onAgentChange={setDefaultAgent}
                onModelChange={setDefaultModel}
              />
              <p className="text-xs text-slate-500 mt-4">
                Note: Project-level default configuration is stored locally. Future versions
                will persist these settings to the server.
              </p>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
