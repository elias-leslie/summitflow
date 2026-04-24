'use client'

import clsx from 'clsx'
import { AlertTriangle, GitBranch, Scissors, Unplug } from 'lucide-react'
import type { RepoStatus } from '@/lib/api'
import {
  getStateColor,
  getStateHexColor,
  getStateIcon,
  getStateLabel,
} from './GitRepoStateUtils'

interface GitRepoCardProps {
  repo: RepoStatus
}

function WorkspacePill({
  icon: Icon,
  label,
  tone,
}: {
  icon: typeof GitBranch
  label: string
  tone: 'cyan' | 'amber' | 'rose'
}) {
  const tones = {
    cyan: 'bg-cyan-500/10 text-cyan-300 border-cyan-500/20',
    amber: 'bg-amber-500/10 text-amber-300 border-amber-500/20',
    rose: 'bg-rose-500/10 text-rose-300 border-rose-500/20',
  }

  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-mono uppercase tracking-wide',
        tones[tone],
      )}
    >
      <Icon className="h-3 w-3" />
      {label}
    </span>
  )
}

export function GitRepoCard({ repo }: GitRepoCardProps) {
  const stateColor = getStateColor(repo.state)
  const hexColor = getStateHexColor(stateColor)
  const workspaceSummary = repo.workspace_summary
  const orphanDetailLabels =
    workspaceSummary?.orphan_details?.map((item) => {
      const status = item.task_status ?? 'missing'
      return `${item.task_id}:${item.resolution}:${status}:a${item.commits_ahead}:b${item.commits_behind ?? 0}:f${item.files_changed}`
    }) ?? []
  const previewSections = [
    {
      label: 'Checkpoints',
      values: workspaceSummary?.checkpoint_task_ids ?? [],
      tone: 'text-cyan-300 border-cyan-500/20 bg-cyan-500/10',
    },
    {
      label: 'Orphans',
      values: workspaceSummary?.orphan_branch_names ?? [],
      tone: 'text-amber-300 border-amber-500/20 bg-amber-500/10',
    },
    {
      label: 'Prunable',
      values: workspaceSummary?.prunable_branch_names ?? [],
      tone: 'text-rose-300 border-rose-500/20 bg-rose-500/10',
    },
    {
      label: 'Salvage',
      values: workspaceSummary?.salvage_task_ids ?? [],
      tone: 'text-rose-300 border-rose-500/20 bg-rose-500/10',
    },
    {
      label: 'Review',
      values:
        orphanDetailLabels.length > 0
          ? orphanDetailLabels
          : (workspaceSummary?.review_orphan_task_ids ?? []),
      tone: 'text-amber-300 border-amber-500/20 bg-amber-500/10',
    },
  ].filter((section) => section.values.length > 0)

  return (
    <div
      className="relative group card p-5 transition-all duration-300 border-l-2 hover:shadow-[0_0_25px_var(--glow-color)]"
      style={
        {
          borderLeftColor: hexColor,
          '--glow-color': `${hexColor}26`,
        } as React.CSSProperties
      }
    >
      {/* Glow orb */}
      <div
        className="absolute top-4 right-4 w-8 h-8 rounded-full opacity-20 blur-lg transition-opacity group-hover:opacity-40"
        style={{ backgroundColor: hexColor }}
      />

      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="display font-semibold text-lg text-slate-100">
            {repo.name}
          </h3>
          <p className="mono text-xs text-slate-500 truncate max-w-[200px]">
            {repo.path}
          </p>
        </div>
        <div
          className={clsx(
            'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium',
            stateColor === 'phosphor' && 'bg-phosphor-500/10 text-phosphor-400',
            stateColor === 'outrun' && 'bg-outrun-500/10 text-outrun-400',
            stateColor === 'amber' && 'bg-amber-500/10 text-amber-400',
            stateColor === 'sunset' && 'bg-sunset-orange/10 text-sunset-orange',
            !['phosphor', 'outrun', 'amber', 'sunset'].includes(stateColor) &&
              'bg-slate-500/10 text-slate-400',
          )}
        >
          {getStateIcon(repo.state)}
          {getStateLabel(repo.state)}
        </div>
      </div>

      {/* Branch */}
      <div className="flex items-center gap-2 mb-4">
        <GitBranch className="w-4 h-4 text-slate-500" />
        <span className="mono text-sm text-slate-300">{repo.branch}</span>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-3 gap-3">
        <div className="text-center p-2 rounded bg-slate-800/50">
          <div
            className={clsx(
              'text-lg font-bold',
              repo.uncommitted > 0 ? 'text-outrun-400' : 'text-slate-500',
            )}
          >
            {repo.uncommitted}
          </div>
          <div className="text-2xs text-slate-500 uppercase tracking-wide">
            Modified
          </div>
        </div>
        <div className="text-center p-2 rounded bg-slate-800/50">
          <div
            className={clsx(
              'text-lg font-bold',
              repo.ahead > 0 ? 'text-sunset-orange' : 'text-slate-500',
            )}
          >
            {repo.ahead}
          </div>
          <div className="text-2xs text-slate-500 uppercase tracking-wide">
            Ahead
          </div>
        </div>
        <div className="text-center p-2 rounded bg-slate-800/50">
          <div
            className={clsx(
              'text-lg font-bold',
              repo.behind > 0 ? 'text-amber-400' : 'text-slate-500',
            )}
          >
            {repo.behind}
          </div>
          <div className="text-2xs text-slate-500 uppercase tracking-wide">
            Behind
          </div>
        </div>
      </div>

      {workspaceSummary && (
        <div className="mt-4 space-y-3 border-t border-slate-800/60 pt-4">
          <div className="flex flex-wrap gap-2">
            <WorkspacePill
              icon={GitBranch}
              label={`${workspaceSummary.active_checkpoints} checkpoint${workspaceSummary.active_checkpoints === 1 ? '' : 's'}`}
              tone="cyan"
            />
            {workspaceSummary.dirty_checkpoints > 0 && (
              <WorkspacePill
                icon={AlertTriangle}
                label={`${workspaceSummary.dirty_checkpoints} dirty`}
                tone="rose"
              />
            )}
            {workspaceSummary.orphan_branches > 0 && (
              <WorkspacePill
                icon={Unplug}
                label={`${workspaceSummary.orphan_branches} orphan`}
                tone="amber"
              />
            )}
            {workspaceSummary.prunable_branches > 0 && (
              <WorkspacePill
                icon={Scissors}
                label={`${workspaceSummary.prunable_branches} prune`}
                tone="rose"
              />
            )}
          </div>

          {previewSections.length > 0 && (
            <div className="space-y-2">
              {previewSections.map((section) => (
                <div key={section.label}>
                  <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
                    {section.label}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {section.values.map((value) => (
                      <span
                        key={`${section.label}-${value}`}
                        className={clsx(
                          'rounded-full border px-2 py-0.5 font-mono text-[10px]',
                          section.tone,
                        )}
                      >
                        {value}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
