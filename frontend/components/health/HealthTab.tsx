'use client'

import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Settings,
  Zap,
} from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'

// Types for API responses
interface HealthSummary {
  project_id: string
  overall_pass: boolean
  total_unfixed: number
  checks: Record<
    string,
    {
      status: string
      error_count: number
      warning_count: number
      last_run: string
    }
  >
}

interface CheckResult {
  id: number
  project_id: string
  check_type: string
  check_name: string | null
  status: string
  error_count: number
  warning_count: number
  error_message: string | null
  file_path: string | null
  line_number: number | null
  column_number: number | null
  run_duration_ms: number | null
  git_sha: string | null
  triggered_by: string | null
  fix_attempted: boolean
  fix_attempts: number
  fixed_at: string | null
  fixed_by: string | null
  created_at: string
  updated_at: string
  escalation_task_id: string | null
}

interface CheckResultsResponse {
  items: CheckResult[]
  total: number
  unfixed_count: number
}

interface HealthTabProps {
  projectId: string
}

// Filter type
type ActivityFilter = 'all' | 'fixed' | 'escalated'

// Badge colors by check type
const CHECK_TYPE_COLORS: Record<string, { bg: string; text: string }> = {
  ruff: { bg: 'bg-orange-500/20', text: 'text-orange-400' },
  mypy: { bg: 'bg-yellow-500/20', text: 'text-yellow-400' },
  biome: { bg: 'bg-blue-500/20', text: 'text-blue-400' },
  tsc: { bg: 'bg-cyan-500/20', text: 'text-cyan-400' },
  pytest: { bg: 'bg-purple-500/20', text: 'text-purple-400' },
}

export function HealthTab({ projectId }: HealthTabProps) {
  const [filter, setFilter] = useState<ActivityFilter>('all')
  const [expandedId, setExpandedId] = useState<number | null>(null)

  // Fetch health summary
  // Use relative URLs for Next.js rewrites (CF Access compatibility)
  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ['quality-health', projectId],
    queryFn: async () => {
      const res = await fetch(`/api/projects/${projectId}/quality/health`)
      if (!res.ok) throw new Error('Failed to fetch health')
      return res.json() as Promise<HealthSummary>
    },
    refetchInterval: 30000,
  })

  // Fetch recent results (activity feed)
  const { data: recentResults } = useQuery({
    queryKey: ['quality-results', projectId, 'recent'],
    queryFn: async () => {
      const res = await fetch(
        `/api/projects/${projectId}/quality/results?limit=50`,
      )
      if (!res.ok) throw new Error('Failed to fetch results')
      return res.json() as Promise<CheckResultsResponse>
    },
    refetchInterval: 30000,
  })

  // Fetch unfixed (needs attention)
  const { data: unfixedResults } = useQuery({
    queryKey: ['quality-results', projectId, 'unfixed'],
    queryFn: async () => {
      const res = await fetch(
        `/api/projects/${projectId}/quality/results?unfixed_only=true&limit=10`,
      )
      if (!res.ok) throw new Error('Failed to fetch unfixed')
      return res.json() as Promise<CheckResultsResponse>
    },
    refetchInterval: 30000,
  })

  // Compute metrics
  const fixedToday =
    recentResults?.items.filter((r) => {
      if (!r.fixed_at) return false
      const fixedDate = new Date(r.fixed_at)
      const today = new Date()
      return fixedDate.toDateString() === today.toDateString()
    }).length ?? 0

  const inProgress =
    unfixedResults?.items.filter((r) => r.fix_attempted && !r.fixed_at)
      .length ?? 0
  const escalated =
    unfixedResults?.items.filter((r) => r.escalation_task_id).length ?? 0

  // Filter activity
  const filteredActivity =
    recentResults?.items.filter((item) => {
      if (filter === 'fixed') return item.fixed_at !== null
      if (filter === 'escalated') return item.escalation_task_id !== null
      return true
    }) ?? []

  // Calculate fix pipeline stats (last 7 days)
  const sevenDaysAgo = new Date()
  sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7)
  const last7Days =
    recentResults?.items.filter(
      (r) => new Date(r.created_at) >= sevenDaysAgo,
    ) ?? []
  const detected = last7Days.length
  const flashFixed = last7Days.filter(
    (r) => r.fixed_by?.includes('flash') || r.fixed_by?.includes('gemini'),
  ).length
  const sonnetFixed = last7Days.filter(
    (r) => r.fixed_by?.includes('sonnet') || r.fixed_by?.includes('claude'),
  ).length
  const escalatedCount = last7Days.filter((r) => r.escalation_task_id).length
  const autoFixRate =
    detected > 0 ? Math.round(((flashFixed + sonnetFixed) / detected) * 100) : 0

  // Format relative time
  const formatRelativeTime = (dateStr: string) => {
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const diffHours = Math.floor(diffMs / 3600000)
    const diffDays = Math.floor(diffMs / 86400000)

    if (diffMins < 1) return 'Just now'
    if (diffMins < 60) return `${diffMins} min ago`
    if (diffHours < 24) return `${diffHours}h ago`
    return `${diffDays}d ago`
  }

  // Format file path for display
  const formatFilePath = (path: string | null) => {
    if (!path) return 'Unknown file'
    // Show last 2 parts of path
    const parts = path.split('/')
    return parts.slice(-2).join('/')
  }

  if (healthLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-2 border-purple-500/30 border-t-purple-500 rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Health Summary Bar */}
      <div className="card rounded-xl p-5">
        <div className="flex items-center gap-8 flex-wrap">
          {/* Status Indicator */}
          <div className="flex items-center gap-3 pr-8 border-r border-slate-700">
            <div
              className={`w-4 h-4 rounded-full ${health?.overall_pass ? 'bg-emerald-500 shadow-[0_0_20px_rgba(16,185,129,0.3)]' : 'bg-rose-500 shadow-[0_0_20px_rgba(244,63,94,0.3)]'} animate-pulse`}
            />
            <div>
              <div
                className={`font-semibold text-lg ${health?.overall_pass ? 'text-emerald-400' : 'text-rose-400'}`}
              >
                {health?.overall_pass ? 'HEALTHY' : 'FAILING'}
              </div>
              <div className="text-slate-500 text-xs">
                {health?.overall_pass
                  ? 'All checks passing'
                  : `${health?.total_unfixed ?? 0} unfixed errors`}
              </div>
            </div>
          </div>

          {/* Metrics */}
          <div className="flex gap-6 flex-1">
            <div className="text-center">
              <div className="text-2xl font-bold text-emerald-400 tabular-nums">
                {fixedToday}
              </div>
              <div className="text-xs text-slate-500">Fixed Today</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-amber-400 tabular-nums">
                {inProgress}
              </div>
              <div className="text-xs text-slate-500">In Progress</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-rose-400 tabular-nums">
                {escalated}
              </div>
              <div className="text-xs text-slate-500">Escalated</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-purple-400 tabular-nums">
                -
              </div>
              <div className="text-xs text-slate-500">Patterns</div>
            </div>
          </div>

          {/* Success Rate */}
          <div className="text-center px-6 border-l border-slate-700">
            <div className="text-2xl font-bold text-cyan-400 tabular-nums">
              {autoFixRate}%
            </div>
            <div className="text-xs text-slate-500">Auto-Fix Rate</div>
          </div>

          {/* Agent Hub Link */}
          <a
            href="http://localhost:8003"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-4 py-2 bg-purple-600/20 text-purple-400 rounded-lg border border-purple-500/30 hover:bg-purple-600/30 transition"
          >
            <Zap className="w-4 h-4" />
            <span className="text-sm font-medium">Memory</span>
            <ExternalLink className="w-3 h-3" />
          </a>
        </div>
      </div>

      {/* Two Column Layout */}
      <div className="grid grid-cols-3 gap-6">
        {/* Activity Feed (2 cols) */}
        <div className="col-span-2 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-200">
              Recent Activity
            </h2>
            <div className="flex gap-2">
              {(['all', 'fixed', 'escalated'] as ActivityFilter[]).map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`px-3 py-1 text-xs rounded-full transition-colors ${
                    filter === f
                      ? 'bg-slate-800 text-slate-400'
                      : 'text-slate-500 hover:bg-slate-800'
                  }`}
                >
                  {f.charAt(0).toUpperCase() + f.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {/* Activity Items */}
          <div className="space-y-3">
            {filteredActivity.length === 0 ? (
              <div className="card rounded-lg p-8 text-center">
                <div className="text-slate-500">No activity found</div>
              </div>
            ) : (
              filteredActivity.slice(0, 20).map((item) => (
                <div
                  key={item.id}
                  className={`card rounded-lg overflow-hidden ${item.escalation_task_id ? 'border-l-2 border-rose-500' : ''}`}
                >
                  <div
                    className="p-4 flex items-center gap-4 cursor-pointer hover:bg-slate-800/30 transition-colors"
                    onClick={() =>
                      setExpandedId(expandedId === item.id ? null : item.id)
                    }
                  >
                    {/* Status Icon */}
                    <div
                      className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                        item.fixed_at
                          ? 'bg-emerald-500/20'
                          : item.escalation_task_id
                            ? 'bg-rose-500/20'
                            : 'bg-amber-500/20'
                      }`}
                    >
                      {item.fixed_at ? (
                        <Check className="w-4 h-4 text-emerald-400" />
                      ) : item.escalation_task_id ? (
                        <AlertTriangle className="w-4 h-4 text-rose-400" />
                      ) : (
                        <div className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                      )}
                    </div>

                    {/* Content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm text-slate-200 truncate">
                          {formatFilePath(item.file_path)}
                        </span>
                        <span
                          className={`px-2 py-0.5 text-xs rounded ${
                            CHECK_TYPE_COLORS[item.check_type]?.bg ??
                            'bg-slate-500/20'
                          } ${CHECK_TYPE_COLORS[item.check_type]?.text ?? 'text-slate-400'}`}
                        >
                          {item.check_type} {item.check_name ?? ''}
                        </span>
                      </div>
                      <div className="text-xs text-slate-500 mt-1">
                        {item.error_message
                          ? item.error_message.slice(0, 60) +
                            (item.error_message.length > 60 ? '...' : '')
                          : 'No error message'}
                        {item.fixed_by && ` • Fixed by ${item.fixed_by}`}
                        {item.fix_attempts > 0 &&
                          !item.fixed_at &&
                          ` • ${item.fix_attempts} attempt${item.fix_attempts > 1 ? 's' : ''}`}
                      </div>
                    </div>

                    {/* Time */}
                    <div className="text-xs text-slate-500">
                      {formatRelativeTime(item.fixed_at ?? item.updated_at)}
                    </div>

                    {/* Expand Icon */}
                    {item.error_message ? (
                      expandedId === item.id ? (
                        <ChevronDown className="w-4 h-4 text-slate-500" />
                      ) : (
                        <ChevronRight className="w-4 h-4 text-slate-500" />
                      )
                    ) : (
                      <div className="w-4" />
                    )}
                  </div>

                  {/* Expanded Details */}
                  {expandedId === item.id && item.error_message && (
                    <div className="bg-slate-950 border-t border-slate-800 p-4">
                      <div className="font-mono text-xs space-y-1">
                        <div className="text-slate-500">
                          {item.file_path}:{item.line_number ?? 0}:
                          {item.column_number ?? 0}
                        </div>
                        <div className="text-rose-400 bg-rose-500/10 px-2 py-1 rounded whitespace-pre-wrap">
                          {item.error_message}
                        </div>
                      </div>
                      {item.escalation_task_id && (
                        <div className="flex items-center gap-3 mt-3 pt-3 border-t border-slate-800">
                          <Link
                            href={`/projects/${projectId}?tab=tasks&task=${item.escalation_task_id}`}
                            className="text-xs text-rose-400 hover:text-rose-300"
                          >
                            View Escalation Task →
                          </Link>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        {/* Right Sidebar */}
        <div className="space-y-4">
          {/* Needs Attention */}
          {unfixedResults && unfixedResults.items.length > 0 && (
            <div className="card rounded-xl p-4">
              <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
                <span className="w-2 h-2 bg-amber-500 rounded-full animate-pulse" />
                Needs Attention
              </h3>
              <div className="space-y-2">
                {unfixedResults.items.slice(0, 5).map((item) => (
                  <div
                    key={item.id}
                    className="flex items-center justify-between py-2 border-b border-slate-800 last:border-0"
                  >
                    <div>
                      <div className="font-mono text-xs text-slate-300 truncate max-w-[140px]">
                        {formatFilePath(item.file_path)}
                      </div>
                      <div className="text-xs text-slate-500">
                        {item.check_type} error
                      </div>
                    </div>
                    <span className="text-xs text-purple-400">
                      {item.fix_attempts > 0
                        ? `${item.fix_attempts} tries`
                        : 'Pending'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Fix Pipeline */}
          <div className="card rounded-xl p-4">
            <h3 className="text-sm font-semibold text-slate-300 mb-3">
              Fix Pipeline (Last 7 Days)
            </h3>
            <div className="space-y-2">
              <div className="flex items-center gap-3">
                <div className="w-24 text-xs text-slate-500">Detected</div>
                <div className="flex-1 bg-slate-800 rounded-full h-2">
                  <div
                    className="bg-slate-400 rounded-full h-2"
                    style={{ width: '100%' }}
                  />
                </div>
                <div className="text-xs text-slate-400 w-8 text-right tabular-nums">
                  {detected}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-24 text-xs text-slate-500">Flash Fixed</div>
                <div className="flex-1 bg-slate-800 rounded-full h-2">
                  <div
                    className="bg-emerald-500 rounded-full h-2"
                    style={{
                      width:
                        detected > 0
                          ? `${(flashFixed / detected) * 100}%`
                          : '0%',
                    }}
                  />
                </div>
                <div className="text-xs text-emerald-400 w-8 text-right tabular-nums">
                  {flashFixed}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-24 text-xs text-slate-500">Sonnet Fixed</div>
                <div className="flex-1 bg-slate-800 rounded-full h-2">
                  <div
                    className="bg-cyan-500 rounded-full h-2"
                    style={{
                      width:
                        detected > 0
                          ? `${(sonnetFixed / detected) * 100}%`
                          : '0%',
                    }}
                  />
                </div>
                <div className="text-xs text-cyan-400 w-8 text-right tabular-nums">
                  {sonnetFixed}
                </div>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-24 text-xs text-slate-500">Escalated</div>
                <div className="flex-1 bg-slate-800 rounded-full h-2">
                  <div
                    className="bg-rose-500 rounded-full h-2"
                    style={{
                      width:
                        detected > 0
                          ? `${(escalatedCount / detected) * 100}%`
                          : '0%',
                    }}
                  />
                </div>
                <div className="text-xs text-rose-400 w-8 text-right tabular-nums">
                  {escalatedCount}
                </div>
              </div>
            </div>
            <div className="mt-3 pt-3 border-t border-slate-800 text-center">
              <span className="text-xs text-slate-500">
                {autoFixRate}% resolved without human intervention
              </span>
            </div>
          </div>

          {/* Quick Links */}
          <div className="card rounded-xl p-4">
            <h3 className="text-sm font-semibold text-slate-300 mb-3">
              Quick Links
            </h3>
            <div className="space-y-2">
              <a
                href="http://localhost:8003"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 text-sm text-slate-400 hover:text-purple-400 transition"
              >
                <Zap className="w-4 h-4" />
                Agent Hub Memory
              </a>
              <Link
                href={`/projects/${projectId}?tab=tasks&status=blocked&taskType=bug`}
                className="flex items-center gap-2 text-sm text-slate-400 hover:text-purple-400 transition"
              >
                <AlertTriangle className="w-4 h-4" />
                All Escalated Tasks
              </Link>
              <Link
                href={`/projects/${projectId}/settings`}
                className="flex items-center gap-2 text-sm text-slate-400 hover:text-purple-400 transition"
              >
                <Settings className="w-4 h-4" />
                Configure Auto-Fix
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
