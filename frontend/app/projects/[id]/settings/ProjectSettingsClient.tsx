'use client'

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import {
  ArrowLeft,
  Layers,
  Lightbulb,
  Loader2,
  Settings2,
  Zap,
} from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useState } from 'react'
import { AgentConfigPanel } from '@/components/settings/AgentConfigPanel'
import { AutomationSettingsPanel } from '@/components/settings/AutomationSettingsPanel'
import { AutonomousSettingsPanel } from '@/components/settings/AutonomousSettings'
import { fetchProject, getAgentConfig, updateAgentConfig } from '@/lib/api'

const COMPONENT_SOURCE_OPTIONS = [
  {
    value: 'manual',
    label: 'Manual',
    description: 'Create components manually in the UI',
  },
  {
    value: 'pages',
    label: 'Pages',
    description: 'Suggest components from ungrouped pages',
  },
  {
    value: 'endpoints',
    label: 'Endpoints',
    description: 'Suggest components from API endpoint groups',
  },
  {
    value: 'directories',
    label: 'Directories',
    description: 'Suggest components from directory structure',
  },
] as const

type SettingsTab = 'general' | 'automation' | 'execution'

export function ProjectSettingsClient() {
  const params = useParams()
  const projectId = params.id as string
  const queryClient = useQueryClient()

  const [activeTab, setActiveTab] = useState<SettingsTab>('general')
  const [savingComponentSource, setSavingComponentSource] = useState(false)

  const { data: project, isLoading: projectLoading } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => fetchProject(projectId),
  })

  const { data: agentConfig, isLoading: configLoading } = useQuery({
    queryKey: ['agent-config', projectId],
    queryFn: () => getAgentConfig(projectId),
  })

  const [defaultAgent, setDefaultAgent] = useState<string | null>(null)
  const [defaultModel, setDefaultModel] = useState<string | null>(null)

  const handleComponentSourceChange = async (source: string) => {
    setSavingComponentSource(true)
    try {
      await updateAgentConfig(projectId, { component_source: source })
      queryClient.invalidateQueries({ queryKey: ['agent-config', projectId] })
    } finally {
      setSavingComponentSource(false)
    }
  }

  if (projectLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
      </div>
    )
  }

  if (!project) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <p className="text-slate-400">Project not found</p>
        <Link href="/" className="text-blue-400 hover:text-blue-300">
          Back to dashboard
        </Link>
      </div>
    )
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
            onClick={() => setActiveTab('general')}
            className={clsx(
              'px-4 py-2 text-sm font-medium transition-colors flex items-center gap-2',
              activeTab === 'general'
                ? 'text-phosphor-400 border-b-2 border-phosphor-400'
                : 'text-slate-400 hover:text-slate-200',
            )}
          >
            <Settings2 className="w-4 h-4" />
            General
          </button>
          <button
            onClick={() => setActiveTab('automation')}
            className={clsx(
              'px-4 py-2 text-sm font-medium transition-colors flex items-center gap-2',
              activeTab === 'automation'
                ? 'text-phosphor-400 border-b-2 border-phosphor-400'
                : 'text-slate-400 hover:text-slate-200',
            )}
          >
            <Lightbulb className="w-4 h-4" />
            Automation
          </button>
          <button
            onClick={() => setActiveTab('execution')}
            className={clsx(
              'px-4 py-2 text-sm font-medium transition-colors flex items-center gap-2',
              activeTab === 'execution'
                ? 'text-phosphor-400 border-b-2 border-phosphor-400'
                : 'text-slate-400 hover:text-slate-200',
            )}
          >
            <Zap className="w-4 h-4" />
            Execution
          </button>
        </div>
      </header>

      <section className="animate-fade-in">
        {activeTab === 'general' && (
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
                        'flex items-start gap-3 p-3 rounded-md border cursor-pointer transition-colors',
                        agentConfig?.component_source === option.value
                          ? 'border-phosphor-500 bg-phosphor-500/10'
                          : 'border-slate-600 hover:border-slate-500 bg-slate-800/50',
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

        {activeTab === 'automation' && (
          <div className="max-w-xl">
            <AutomationSettingsPanel projectId={projectId} />
          </div>
        )}

        {activeTab === 'execution' && (
          <div className="max-w-xl">
            <AutonomousSettingsPanel projectId={projectId} />
          </div>
        )}
      </section>
    </main>
  )
}
