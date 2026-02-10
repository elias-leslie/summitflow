'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  GitBranch,
  Loader2,
  Sparkles,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronRight
} from 'lucide-react'
import { smartSyncProject, type RepoStatus } from '@/lib/api'
import { useState } from 'react'
import { THEME } from './theme'
import { getStateInfo } from './utils'

interface GitProjectCardProps {
  repo: RepoStatus
}

export function GitProjectCard({ repo }: GitProjectCardProps) {
  const stateInfo = getStateInfo(repo.state)
  const StateIcon = stateInfo.icon
  const queryClient = useQueryClient()
  const [showDetails, setShowDetails] = useState(false)

  const syncMutation = useMutation({
    mutationFn: () => smartSyncProject(repo.name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['git-status'] })
    }
  })

  const isWorking = syncMutation.isPending
  const result = syncMutation.data

  return (
    <div
      className={clsx(
        'group relative overflow-hidden rounded-xl border transition-all duration-300',
        THEME.colors.card,
        THEME.colors.border,
        THEME.colors.borderGlow
      )}
    >
      {/* Dirty Pulse Effect */}
      {repo.state === 'dirty' && (
        <div className="absolute top-0 right-0 w-2 h-2 m-3 rounded-full bg-pink-500 animate-pulse shadow-[0_0_10px_#ff0066]" />
      )}

      <div className="p-5">
        {/* Header */}
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-slate-800/50 flex items-center justify-center border border-slate-700/50">
              <GitBranch className={clsx("w-5 h-5", THEME.colors.accent.cyan)} />
            </div>
            <div>
              <h3 className={clsx("font-semibold text-lg", THEME.colors.text.header)}>{repo.name}</h3>
              <p className="text-xs text-slate-500 mono truncate max-w-[180px]">{repo.path}</p>
            </div>
          </div>
        </div>

        {/* Branch Info */}
        <div className="flex items-center gap-3 mb-4 p-2 rounded bg-slate-950/50 border border-slate-800/50">
          <GitBranch className="w-3.5 h-3.5 text-slate-600" />
          <span className={clsx("text-sm", THEME.colors.text.mono)}>{repo.branch}</span>
          <div className="h-4 w-[1px] bg-slate-800 mx-1" />
          <span className={clsx("text-xs flex items-center gap-1.5", stateInfo.color)}>
            <StateIcon className="w-3 h-3" />
            {stateInfo.label}
          </span>
        </div>

        {/* Sync Stats */}
        <div className="grid grid-cols-3 gap-2 mb-5">
          <div className="text-center p-2 rounded bg-slate-900/40">
            <span className={clsx("block text-sm font-bold", repo.uncommitted > 0 ? "text-pink-400" : "text-slate-600")}>
              {repo.uncommitted}
            </span>
            <span className="text-[10px] text-slate-500 uppercase">Changes</span>
          </div>
          <div className="text-center p-2 rounded bg-slate-900/40">
            <span className={clsx("block text-sm font-bold", repo.ahead > 0 ? "text-cyan-400" : "text-slate-600")}>
              {repo.ahead}
            </span>
            <span className="text-[10px] text-slate-500 uppercase">Ahead</span>
          </div>
          <div className="text-center p-2 rounded bg-slate-900/40">
            <span className={clsx("block text-sm font-bold", repo.behind > 0 ? "text-amber-400" : "text-slate-600")}>
              {repo.behind}
            </span>
            <span className="text-[10px] text-slate-500 uppercase">Behind</span>
          </div>
        </div>

        {/* Smart Sync Action */}
        <div className="border-t border-slate-800/60 pt-4">
          <button
            disabled={isWorking}
            onClick={() => syncMutation.mutate()}
            className={clsx(
              "w-full flex items-center justify-center gap-2 p-3 rounded-lg font-medium transition-all shadow-lg",
              isWorking
                ? "bg-slate-800 text-slate-400 cursor-not-allowed"
                : "bg-gradient-to-r from-pink-600 to-purple-600 hover:from-pink-500 hover:to-purple-500 text-white shadow-pink-500/20 hover:shadow-pink-500/40"
            )}
          >
            {isWorking ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Running Checks...</span>
              </>
            ) : (
              <>
                <Sparkles className="w-4 h-4" />
                <span>Smart Sync</span>
              </>
            )}
          </button>
        </div>

        {/* Sync Result / Gate Keeper */}
        {result && (
          <div className={clsx(
            "mt-4 rounded border p-3",
            result.success
              ? "bg-emerald-500/5 border-emerald-500/20"
              : "bg-pink-500/5 border-pink-500/20"
          )}>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                {result.success ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                ) : (
                  <XCircle className="w-4 h-4 text-pink-500" />
                )}
                <span className={clsx("text-sm font-medium", result.success ? "text-emerald-400" : "text-pink-400")}>
                  {result.reason === 'pushed_existing' ? 'PUSHED' : result.reason === 'no_changes' ? 'SKIP' : result.status}
                </span>
                {result.pushed && (
                  <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                    PUSHED
                  </span>
                )}
              </div>
            </div>

            {/* Quality Gates */}
            {result.gates && (
              <div className="flex flex-wrap gap-1.5 mb-2">
                {result.gates.split('|').filter(Boolean).map((gate) => {
                  const [name, status] = gate.split(':')
                  const passed = status === 'PASS' || status === 'SKIP'
                  const isWarn = status?.startsWith('WARN')
                  return (
                    <span
                      key={gate}
                      className={clsx(
                        "text-[10px] font-mono px-1.5 py-0.5 rounded border inline-flex items-center gap-1",
                        passed
                          ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
                          : isWarn
                            ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
                            : "bg-pink-500/10 text-pink-400 border-pink-500/20"
                      )}
                    >
                      <span className={clsx("w-1.5 h-1.5 rounded-full", passed ? "bg-emerald-400" : isWarn ? "bg-amber-400" : "bg-pink-400")} />
                      {name}
                    </span>
                  )
                })}
              </div>
            )}

            {/* Error Messages */}
            {result.errors.length > 0 && (
              <div className="mb-2 space-y-1">
                {result.errors.map((error, i) => (
                  <div key={i} className="text-xs font-mono text-pink-400 bg-pink-500/5 px-2 py-1 rounded border border-pink-500/10">
                    {error}
                  </div>
                ))}
              </div>
            )}

            {/* AI Message Preview */}
            {result.message && (
              <div className="mb-2 text-xs font-mono text-slate-400 bg-slate-950/50 p-2 rounded border border-slate-800">
                <span className="text-purple-400">$</span> {result.message}
              </div>
            )}

            {/* Details Accordion */}
            <button
              onClick={() => setShowDetails(!showDetails)}
              className="w-full flex items-center justify-between text-[10px] text-slate-500 hover:text-slate-300 uppercase tracking-wider"
            >
              <span>View Log Output</span>
              {showDetails ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            </button>

            {showDetails && (
              <div className="mt-2 bg-black/80 rounded p-2 overflow-x-auto border border-slate-800">
                <pre className="text-[10px] font-mono leading-relaxed text-slate-300">
                  {result.raw_output}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
