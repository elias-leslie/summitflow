'use client'

import { useEffect, useState } from 'react'
import { ChevronDown, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { CodingAgent } from '@/lib/api/tasks'
import { fetchCodingAgents } from '@/lib/api/tasks'

interface AgentSelectorProps {
  autonomous?: boolean
  agentOverride?: string | null
  taskType: string
  isRunning: boolean
  onAgentOverrideChange?: (agentSlug: string | null) => void
}

// Map task_type to default agent slug (mirrors backend TASK_TYPE_AGENT_MAP)
const TASK_TYPE_AGENT_MAP: Record<string, string> = {
  refactor: 'refactor',
}
const DEFAULT_AGENT = 'coder'

function getDefaultAgentForTask(taskType: string): string {
  return TASK_TYPE_AGENT_MAP[taskType] || DEFAULT_AGENT
}

export function AgentSelector({
  autonomous,
  agentOverride,
  taskType,
  isRunning,
  onAgentOverrideChange,
}: AgentSelectorProps) {
  const [codingAgents, setCodingAgents] = useState<CodingAgent[]>([])
  const [isLoadingAgents, setIsLoadingAgents] = useState(false)
  const [isAgentDropdownOpen, setIsAgentDropdownOpen] = useState(false)

  // Fetch coding agents when autonomous is enabled
  useEffect(() => {
    if (autonomous && codingAgents.length === 0) {
      setIsLoadingAgents(true)
      fetchCodingAgents()
        .then((data) => setCodingAgents(data.agents))
        .catch(() => setCodingAgents([]))
        .finally(() => setIsLoadingAgents(false))
    }
  }, [autonomous, codingAgents.length])

  // Don't render if not autonomous or no handler
  if (!autonomous || !onAgentOverrideChange) {
    return null
  }

  // Resolve which agent will be used
  const resolvedAgent = agentOverride || getDefaultAgentForTask(taskType)
  const currentAgentName =
    codingAgents.find((a) => a.slug === resolvedAgent)?.name || resolvedAgent

  return (
    <div className="relative">
      <Button
        variant="outline"
        className={`gap-2 min-w-[140px] justify-between ${
          agentOverride
            ? 'border-cyan-500/30 text-cyan-400'
            : 'border-slate-600 text-slate-400'
        }`}
        onClick={() => setIsAgentDropdownOpen(!isAgentDropdownOpen)}
        disabled={isRunning || isLoadingAgents}
        title="Select which agent executes this task"
      >
        {isLoadingAgents ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <>
            <span className="truncate">
              {currentAgentName}
              {!agentOverride && <span className="text-slate-500 ml-1">(auto)</span>}
            </span>
            <ChevronDown className="h-4 w-4 shrink-0" />
          </>
        )}
      </Button>

      {isAgentDropdownOpen && (
        <>
          {/* Backdrop to close dropdown */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setIsAgentDropdownOpen(false)}
          />
          {/* Dropdown menu */}
          <div className="absolute top-full left-0 mt-1 z-50 min-w-[180px] bg-slate-800 border border-slate-700 rounded-md shadow-lg py-1">
            {/* Auto option */}
            <button
              className={`w-full px-3 py-2 text-left text-sm hover:bg-slate-700 flex items-center justify-between ${
                !agentOverride ? 'text-cyan-400' : 'text-slate-300'
              }`}
              onClick={() => {
                onAgentOverrideChange(null)
                setIsAgentDropdownOpen(false)
              }}
            >
              <span>Auto</span>
              <span className="text-slate-500 text-xs">
                ({getDefaultAgentForTask(taskType)})
              </span>
            </button>

            <div className="border-t border-slate-700 my-1" />

            {/* Agent options */}
            {codingAgents.map((agent) => (
              <button
                key={agent.slug}
                className={`w-full px-3 py-2 text-left text-sm hover:bg-slate-700 ${
                  agentOverride === agent.slug ? 'text-cyan-400' : 'text-slate-300'
                }`}
                onClick={() => {
                  onAgentOverrideChange(agent.slug)
                  setIsAgentDropdownOpen(false)
                }}
              >
                <div className="font-medium">{agent.name}</div>
                {agent.description && (
                  <div className="text-xs text-slate-500 truncate">
                    {agent.description}
                  </div>
                )}
              </button>
            ))}

            {codingAgents.length === 0 && !isLoadingAgents && (
              <div className="px-3 py-2 text-sm text-slate-500">
                No coding agents available
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
