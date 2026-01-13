"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import {
  ArrowLeft,
  Settings2,
  Loader2,
  Layers,
  Zap,
  Lightbulb,
} from "lucide-react";
import Link from "next/link";
import { clsx } from "clsx";
import {
  fetchProject,
  getAgentConfig,
  updateAgentConfig,
  getAutomationSettings,
  updateAutomationSettings,
  type AutomationSettings,
} from "@/lib/api";
import { AgentConfigPanel } from "@/components/settings/AgentConfigPanel";
import { AutonomousSettingsPanel } from "@/components/settings/AutonomousSettings";

const COMPONENT_SOURCE_OPTIONS = [
  {
    value: "manual",
    label: "Manual",
    description: "Create components manually in the UI",
  },
  {
    value: "pages",
    label: "Pages",
    description: "Suggest components from ungrouped pages",
  },
  {
    value: "endpoints",
    label: "Endpoints",
    description: "Suggest components from API endpoint groups",
  },
  {
    value: "directories",
    label: "Directories",
    description: "Suggest components from directory structure",
  },
] as const;

const SCHEDULE_PRESETS = [
  { value: "nightly", label: "Nightly", cron: "0 3 * * *" },
  { value: "weekly", label: "Weekly", cron: "0 3 * * 0" },
  { value: "monthly", label: "Monthly", cron: "0 3 1 * *" },
] as const;

const AGENT_OPTIONS = [
  {
    value: "gemini",
    label: "Gemini",
    description: "Cost-efficient, large context",
  },
  { value: "claude", label: "Claude", description: "High quality reasoning" },
] as const;

type SettingsTab = "general" | "automation" | "execution";

export default function ProjectSettingsPage() {
  const params = useParams();
  const projectId = params.id as string;
  const queryClient = useQueryClient();

  const [activeTab, setActiveTab] = useState<SettingsTab>("general");
  const [savingComponentSource, setSavingComponentSource] = useState(false);
  const [showAdvancedCron, setShowAdvancedCron] = useState(false);

  const { data: project, isLoading: projectLoading } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => fetchProject(projectId),
  });

  const { data: agentConfig, isLoading: configLoading } = useQuery({
    queryKey: ["agent-config", projectId],
    queryFn: () => getAgentConfig(projectId),
  });

  const { data: automationSettings, isLoading: automationLoading } = useQuery({
    queryKey: ["automation-settings", projectId],
    queryFn: () => getAutomationSettings(projectId),
  });

  const automationMutation = useMutation({
    mutationFn: (settings: Partial<AutomationSettings>) =>
      updateAutomationSettings(projectId, settings),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["automation-settings", projectId],
      });
    },
  });

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

  const handleSchedulePresetChange = (preset: string) => {
    const selected = SCHEDULE_PRESETS.find((p) => p.value === preset);
    if (selected) {
      automationMutation.mutate({
        schedule_preset: preset as AutomationSettings["schedule_preset"],
        cron_expression: selected.cron,
      });
    }
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

        {/* Tabs */}
        <div className="flex gap-1 border-b border-slate-700">
          <button
            onClick={() => setActiveTab("general")}
            className={clsx(
              "px-4 py-2 text-sm font-medium transition-colors flex items-center gap-2",
              activeTab === "general"
                ? "text-phosphor-400 border-b-2 border-phosphor-400"
                : "text-slate-400 hover:text-slate-200",
            )}
          >
            <Settings2 className="w-4 h-4" />
            General
          </button>
          <button
            onClick={() => setActiveTab("automation")}
            className={clsx(
              "px-4 py-2 text-sm font-medium transition-colors flex items-center gap-2",
              activeTab === "automation"
                ? "text-phosphor-400 border-b-2 border-phosphor-400"
                : "text-slate-400 hover:text-slate-200",
            )}
          >
            <Lightbulb className="w-4 h-4" />
            Automation
          </button>
          <button
            onClick={() => setActiveTab("execution")}
            className={clsx(
              "px-4 py-2 text-sm font-medium transition-colors flex items-center gap-2",
              activeTab === "execution"
                ? "text-phosphor-400 border-b-2 border-phosphor-400"
                : "text-slate-400 hover:text-slate-200",
            )}
          >
            <Zap className="w-4 h-4" />
            Execution
          </button>
        </div>
      </header>

      <section className="animate-fade-in">
        {activeTab === "general" && (
          <div className="max-w-xl space-y-6">
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
                          : "border-slate-600 hover:border-slate-500 bg-slate-800/50",
                      )}
                    >
                      <input
                        type="radio"
                        name="component_source"
                        value={option.value}
                        checked={agentConfig?.component_source === option.value}
                        onChange={() =>
                          handleComponentSourceChange(option.value)
                        }
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
                      {savingComponentSource &&
                        agentConfig?.component_source !== option.value && (
                          <Loader2 className="w-4 h-4 animate-spin text-slate-400" />
                        )}
                    </label>
                  ))}
                </div>
              )}
            </div>

            <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
              <h3 className="text-sm font-medium text-slate-200 mb-4">
                Default Agent Configuration
              </h3>
              <p className="text-xs text-slate-400 mb-4">
                Configure default AI agent settings for this project.
              </p>
              <AgentConfigPanel
                agentOverride={defaultAgent}
                modelOverride={defaultModel}
                onAgentChange={setDefaultAgent}
                onModelChange={setDefaultModel}
              />
              <p className="text-xs text-slate-500 mt-4">
                Note: Project-level default configuration is stored locally.
                Future versions will persist these settings to the server.
              </p>
            </div>
          </div>
        )}

        {activeTab === "automation" && (
          <div className="max-w-xl space-y-6">
            {automationLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
              </div>
            ) : (
              <>
                {/* Enabled Toggle */}
                <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-sm font-medium text-slate-200 flex items-center gap-2">
                        <Zap className="w-4 h-4 text-yellow-400" />
                        Automation Enabled
                      </h3>
                      <p className="text-xs text-slate-400 mt-1">
                        Enable automatic processing of crowdsourced ideas
                      </p>
                    </div>
                    <button
                      onClick={() =>
                        automationMutation.mutate({
                          enabled: !automationSettings?.enabled,
                        })
                      }
                      disabled={automationMutation.isPending}
                      className={clsx(
                        "relative w-12 h-6 rounded-full transition-colors",
                        automationSettings?.enabled
                          ? "bg-phosphor-500"
                          : "bg-slate-600",
                      )}
                    >
                      <span
                        className={clsx(
                          "absolute top-1 w-4 h-4 bg-white rounded-full transition-transform",
                          automationSettings?.enabled
                            ? "translate-x-7"
                            : "translate-x-1",
                        )}
                      />
                    </button>
                  </div>
                </div>

                {/* Schedule Section */}
                <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
                  <h3 className="text-sm font-medium text-slate-200 mb-2">
                    Schedule
                  </h3>
                  <p className="text-xs text-slate-400 mb-4">
                    When to process approved ideas automatically
                  </p>

                  <div className="space-y-3">
                    {SCHEDULE_PRESETS.map((preset) => (
                      <label
                        key={preset.value}
                        className={clsx(
                          "flex items-center gap-3 p-3 rounded-md border cursor-pointer transition-colors",
                          automationSettings?.schedule_preset === preset.value
                            ? "border-phosphor-500 bg-phosphor-500/10"
                            : "border-slate-600 hover:border-slate-500",
                        )}
                      >
                        <input
                          type="radio"
                          name="schedule_preset"
                          value={preset.value}
                          checked={
                            automationSettings?.schedule_preset === preset.value
                          }
                          onChange={() =>
                            handleSchedulePresetChange(preset.value)
                          }
                          disabled={automationMutation.isPending}
                          className="accent-phosphor-500"
                        />
                        <span className="text-sm text-slate-200">
                          {preset.label}
                        </span>
                        <span className="text-xs text-slate-500 ml-auto mono">
                          {preset.cron}
                        </span>
                      </label>
                    ))}
                  </div>

                  {/* Advanced Cron Toggle */}
                  <button
                    onClick={() => setShowAdvancedCron(!showAdvancedCron)}
                    className="mt-3 text-xs text-slate-400 hover:text-slate-300"
                  >
                    {showAdvancedCron ? "Hide" : "Show"} Advanced (Custom Cron)
                  </button>

                  {showAdvancedCron && (
                    <div className="mt-3">
                      <input
                        type="text"
                        value={automationSettings?.cron_expression || ""}
                        onChange={(e) =>
                          automationMutation.mutate({
                            cron_expression: e.target.value,
                          })
                        }
                        placeholder="0 3 * * *"
                        className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded text-sm text-slate-200 mono focus:border-phosphor-500 focus:outline-none"
                      />
                      <p className="text-xs text-slate-500 mt-1">
                        Standard cron format: minute hour day month weekday
                      </p>
                    </div>
                  )}
                </div>

                {/* Budget Section */}
                <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
                  <h3 className="text-sm font-medium text-slate-200 mb-2">
                    Daily Budget
                  </h3>
                  <p className="text-xs text-slate-400 mb-4">
                    Maximum spend per day on automated idea processing
                  </p>

                  <div className="flex items-center gap-2">
                    <span className="text-slate-400">$</span>
                    <input
                      type="number"
                      min="0"
                      step="0.50"
                      value={automationSettings?.daily_budget_usd || 5}
                      onChange={(e) =>
                        automationMutation.mutate({
                          daily_budget_usd: parseFloat(e.target.value) || 0,
                        })
                      }
                      className="w-24 px-3 py-2 bg-slate-900 border border-slate-600 rounded text-sm text-slate-200 focus:border-phosphor-500 focus:outline-none"
                    />
                    <span className="text-xs text-slate-400">USD per day</span>
                  </div>
                </div>

                {/* Agent Section */}
                <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
                  <h3 className="text-sm font-medium text-slate-200 mb-2">
                    AI Agents
                  </h3>
                  <p className="text-xs text-slate-400 mb-4">
                    Choose which AI agents process ideas
                  </p>

                  <div className="space-y-4">
                    {/* Primary Agent */}
                    <div>
                      <label className="text-xs text-slate-400 block mb-2">
                        Primary Agent
                      </label>
                      <select
                        value={automationSettings?.primary_agent || "gemini"}
                        onChange={(e) =>
                          automationMutation.mutate({
                            primary_agent: e.target
                              .value as AutomationSettings["primary_agent"],
                          })
                        }
                        className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded text-sm text-slate-200 focus:border-phosphor-500 focus:outline-none"
                      >
                        {AGENT_OPTIONS.map((agent) => (
                          <option key={agent.value} value={agent.value}>
                            {agent.label} - {agent.description}
                          </option>
                        ))}
                      </select>
                    </div>

                    {/* Secondary Agent */}
                    <div>
                      <label className="text-xs text-slate-400 block mb-2">
                        Secondary Agent (Fallback)
                      </label>
                      <select
                        value={automationSettings?.secondary_agent || "claude"}
                        onChange={(e) =>
                          automationMutation.mutate({
                            secondary_agent: e.target
                              .value as AutomationSettings["secondary_agent"],
                          })
                        }
                        className="w-full px-3 py-2 bg-slate-900 border border-slate-600 rounded text-sm text-slate-200 focus:border-phosphor-500 focus:outline-none"
                      >
                        {AGENT_OPTIONS.map((agent) => (
                          <option key={agent.value} value={agent.value}>
                            {agent.label} - {agent.description}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>
                </div>

                {/* Save indicator */}
                {automationMutation.isPending && (
                  <div className="flex items-center justify-center gap-2 text-sm text-slate-400">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Saving...
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {activeTab === "execution" && (
          <div className="max-w-xl">
            <AutonomousSettingsPanel projectId={projectId} />
          </div>
        )}
      </section>
    </main>
  );
}
