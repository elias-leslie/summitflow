'use client'

import { GitBranch } from 'lucide-react'
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

export function GitRepoCard({ repo }: GitRepoCardProps) {
  const stateColor = getStateColor(repo.state)
  const hexColor = getStateHexColor(stateColor)

  return (
    <div
      className="relative group card p-5 transition-all duration-300 border-l-2"
      style={{ borderLeftColor: hexColor }}
      onMouseEnter={(e) => { e.currentTarget.style.boxShadow = `0 0 25px ${hexColor}26` }}
      onMouseLeave={(e) => { e.currentTarget.style.boxShadow = 'none' }}
    >
      {/* Glow orb */}
      <div
        className="absolute top-4 right-4 w-8 h-8 rounded-full opacity-20 blur-lg transition-opacity group-hover:opacity-40"
        style={{ backgroundColor: hexColor }}
      />

      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="display font-semibold text-lg text-white">
            {repo.name}
          </h3>
          <p className="mono text-xs text-slate-500 truncate max-w-[200px]">
            {repo.path}
          </p>
        </div>
        <div
          className={`
            flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium
            ${
              stateColor === 'phosphor'
                ? 'bg-phosphor-500/10 text-phosphor-400'
                : stateColor === 'outrun'
                  ? 'bg-outrun-500/10 text-outrun-400'
                  : stateColor === 'amber'
                    ? 'bg-amber-500/10 text-amber-400'
                    : 'bg-sunset-orange/10 text-sunset-orange'
            }
          `}
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
            className={`text-lg font-bold ${repo.uncommitted > 0 ? 'text-outrun-400' : 'text-slate-500'}`}
          >
            {repo.uncommitted}
          </div>
          <div className="text-2xs text-slate-500 uppercase tracking-wide">
            Modified
          </div>
        </div>
        <div className="text-center p-2 rounded bg-slate-800/50">
          <div
            className={`text-lg font-bold ${repo.ahead > 0 ? 'text-sunset-orange' : 'text-slate-500'}`}
          >
            {repo.ahead}
          </div>
          <div className="text-2xs text-slate-500 uppercase tracking-wide">
            Ahead
          </div>
        </div>
        <div className="text-center p-2 rounded bg-slate-800/50">
          <div
            className={`text-lg font-bold ${repo.behind > 0 ? 'text-amber-400' : 'text-slate-500'}`}
          >
            {repo.behind}
          </div>
          <div className="text-2xs text-slate-500 uppercase tracking-wide">
            Behind
          </div>
        </div>
      </div>
    </div>
  )
}
