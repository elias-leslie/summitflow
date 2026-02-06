'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  GitBranch,
  RefreshCw,
  GitPullRequest,
  Check,
  Clock,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  XCircle,
  Loader2,
  Sparkles
} from 'lucide-react'
import { WorktreeList } from '@/components/git/WorktreeList'
import { fetchGitStatus, smartSyncProject, type RepoStatus } from '@/lib/api'
import { useState } from 'react'

// --- Design System Tokens (Stitch "Outrun" Theme) ---
const THEME = {
  colors: {
    void: 'bg-[#0a0612]', // Deep Void
    card: 'bg-gradient-to-br from-slate-900 to-[#0f0a18]', // Elevated Surface
    border: 'border-slate-800',
    borderGlow: 'hover:border-pink-500/30 hover:shadow-[0_0_15px_rgba(255,0,102,0.15)]',
    text: {
      primary: 'text-slate-200',
      secondary: 'text-slate-500',
      header: 'font-display tracking-tight text-white',
      mono: 'font-mono text-cyan-400',
    },
    accent: {
      pink: 'text-[#ff0066]',
      cyan: 'text-[#00f5ff]',
      amber: 'text-amber-400',
    }
  }
}

function getStateInfo(state: RepoStatus['state']) {
  switch (state) {
    case 'clean':
      return { label: 'Clean', icon: Check, color: 'text-emerald-400', bg: 'bg-emerald-500/10' }
    case 'dirty':
      return { label: 'Dirty', icon: AlertCircle, color: THEME.colors.accent.pink, bg: 'bg-pink-500/10' }
    case 'behind':
      return { label: 'Behind', icon: ArrowDown, color: THEME.colors.accent.amber, bg: 'bg-amber-500/10' }
    case 'ahead':
      return { label: 'Ahead', icon: ArrowUp, color: THEME.colors.accent.cyan, bg: 'bg-cyan-500/10' }
    default:
      return { label: state, icon: GitBranch, color: 'text-slate-400', bg: 'bg-slate-500/10' }
  }
}

function StatsWidget({ label, value, icon: Icon, color }: { label: string, value: number, icon: any, color: string }) {
  return (
    <div className="flex flex-col p-4 rounded-lg bg-slate-900/50 border border-slate-800">
      <div className="flex items-center gap-2 mb-1">
        <Icon className={clsx("w-4 h-4", color)} />
        <span className="text-xs text-slate-500 uppercase tracking-wider">{label}</span>
      </div>
      <span className={clsx("text-2xl font-bold font-mono", color)}>{value}</span>
    </div>
  )
}

function GitProjectCard({ repo }: { repo: RepoStatus }) {
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

export function GitClient() {
  const { data: gitStatus, isLoading, isError, refetch } = useQuery({
    queryKey: ['git-status'],
    queryFn: fetchGitStatus,
    staleTime: 30000,
    refetchInterval: 60000,
  })

  // Derived Stats
  const totalRepos = gitStatus?.total ?? 0
  const dirtyCount = gitStatus?.repositories.filter(r => r.state === 'dirty').length ?? 0
  const syncCount = gitStatus?.repositories.filter(r => r.behind > 0 || r.ahead > 0).length ?? 0

  return (
    <div className="p-6 space-y-8 max-w-7xl mx-auto">
      {/* Header Section */}
      <section className="flex flex-col md:flex-row md:items-end justify-between gap-4 animate-in fade-in slide-in-from-top-4 duration-500">
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight flex items-center gap-3 mb-2">
            <div className="p-2 rounded bg-pink-500/10 border border-pink-500/20">
              <GitBranch className="w-6 h-6 text-pink-500" />
            </div>
            Git Operations
          </h1>
          <p className="text-slate-400 max-w-2xl">
            Command center for version control across all managed workspaces.
          </p>
        </div>

        <button
          onClick={() => refetch()}
          className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-md border border-slate-700 transition-all shadow-lg hover:shadow-cyan-500/10 hover:border-cyan-500/30"
        >
          <RefreshCw className={clsx('w-4 h-4', isLoading && 'animate-spin')} />
          <span>Refresh All</span>
        </button>
      </section>

      <WorktreeList />

      {/* Stats Dashboard */}
      {gitStatus && (
        <section className="grid grid-cols-1 md:grid-cols-3 gap-4 animate-in fade-in slide-in-from-top-8 delay-100 duration-500">
          <StatsWidget
            label="Total Repositories"
            value={totalRepos}
            icon={GitPullRequest}
            color="text-white"
          />
          <StatsWidget
            label="Changes Pending"
            value={dirtyCount}
            icon={AlertCircle}
            color={dirtyCount > 0 ? "text-pink-500" : "text-slate-500"}
          />
          <StatsWidget
            label="Sync Required"
            value={syncCount}
            icon={Clock}
            color={syncCount > 0 ? "text-cyan-400" : "text-emerald-500"}
          />
        </section>
      )}

      {/* Loading State */}
      {isLoading && (
        <div className="h-64 flex items-center justify-center border border-dashed border-slate-800 rounded-xl bg-slate-900/20">
          <div className="flex flex-col items-center gap-3 text-slate-500">
            <RefreshCw className="w-8 h-8 animate-spin text-cyan-500" />
            <p>Scanning workspaces...</p>
          </div>
        </div>
      )}

      {/* Error State */}
      {isError && (
        <div className="p-6 rounded-xl bg-red-500/10 border border-red-500/20 text-red-200 flex items-center gap-3">
          <XCircle className="w-6 h-6 text-red-500" />
          <div>
            <h3 className="font-semibold text-white">Connection Failed</h3>
            <p className="text-sm opacity-80">Unable to reach the Git service. Please verify the backend is running.</p>
          </div>
        </div>
      )}

      {/* Main Grid */}
      {gitStatus && !isLoading && (
        <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 animate-in fade-in slide-in-from-bottom-8 delay-200 duration-500">
          {gitStatus.repositories.map((repo) => (
            <GitProjectCard key={repo.path} repo={repo} />
          ))}
        </section>
      )}

      {/* Empty State */}
      {gitStatus?.repositories.length === 0 && (
        <div className="text-center py-20">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-slate-800/50 mb-4">
            <GitBranch className="w-8 h-8 text-slate-600" />
          </div>
          <h3 className="text-xl font-semibold text-white mb-2">No Repositories Found</h3>
          <p className="text-slate-400 max-w-sm mx-auto">
            Your workspace appears empty. Initialize a git repository to see it here.
          </p>
        </div>
      )}
    </div>
  )
}
