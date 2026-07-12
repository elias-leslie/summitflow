'use client'

import clsx from 'clsx'
import {
  Bot,
  ClipboardList,
  GitBranch,
  ShieldCheck,
  Workflow,
} from 'lucide-react'
import type { Task } from '@/lib/api'
import { hasVerifiedEvidence } from '@/lib/task-verification'

interface JennyExecutionStripProps {
  tasks: Task[]
}

function taskTokenBand(tokens: number): string {
  if (tokens <= 0) return '0'
  if (tokens < 1000) return '<1k'
  if (tokens < 10000) return `${Math.round(tokens / 1000)}k`
  return `${Math.round(tokens / 1000)}k+`
}

export function JennyExecutionStrip({ tasks }: JennyExecutionStripProps) {
  const readyTasks = tasks.filter((task) => task.status === 'pending')
  const activeTasks = tasks.filter((task) => task.status === 'running')
  const verifierTasks = tasks.filter((task) =>
    hasVerifiedEvidence(task.verification_result),
  )
  const agentSessions = tasks.reduce(
    (total, task) => total + (task.agent_hub_session_ids?.length ?? 0),
    0,
  )
  const tokenTotal = tasks.reduce(
    (total, task) => total + (task.total_tokens_used ?? 0),
    0,
  )

  const stats = [
    {
      icon: ClipboardList,
      label: 'Ready',
      value: readyTasks.length,
      tone: 'text-slate-300',
    },
    {
      icon: Workflow,
      label: 'Active',
      value: activeTasks.length,
      tone: activeTasks.length ? 'text-phosphor-300' : 'text-slate-400',
    },
    {
      icon: ShieldCheck,
      label: 'Verified',
      value: verifierTasks.length,
      tone: verifierTasks.length ? 'text-emerald-300' : 'text-slate-400',
    },
    {
      icon: GitBranch,
      label: 'Agent sessions',
      value: agentSessions,
      tone: agentSessions ? 'text-outrun-300' : 'text-slate-400',
    },
  ]

  return (
    <section className="rounded-lg border border-slate-800/80 bg-slate-950/72 px-3 py-2 shadow-[0_12px_28px_-24px_rgba(0,0,0,0.9)]">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex min-w-0 items-center gap-2 pr-2">
          <Bot className="h-4 w-4 shrink-0 text-phosphor-300" />
          <div className="min-w-0">
            <div className="text-xs font-medium text-slate-200">
              Jenny execution
            </div>
            <div className="truncate text-[10px] text-slate-500">
              Auto-managed project tasks · force verifier/model/parallelism from
              task detail or Work Chat
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {stats.map((stat) => {
            const Icon = stat.icon
            return (
              <div
                key={stat.label}
                className="flex h-7 items-center gap-1.5 rounded border border-slate-800 bg-slate-900/70 px-2"
              >
                <Icon className={clsx('h-3.5 w-3.5', stat.tone)} />
                <span className="text-[10px] text-slate-500">{stat.label}</span>
                <span className={clsx('font-mono text-xs', stat.tone)}>
                  {stat.value}
                </span>
              </div>
            )
          })}
          <div className="flex h-7 items-center gap-1.5 rounded border border-slate-800 bg-slate-900/70 px-2">
            <span className="text-[10px] text-slate-500">Tokens</span>
            <span className="font-mono text-xs text-slate-300">
              {taskTokenBand(tokenTotal)}
            </span>
          </div>
        </div>
      </div>
    </section>
  )
}
