'use client';

import { useState, useEffect, useMemo } from 'react';
import { motion } from 'motion/react';
import { clsx } from 'clsx';
import { formatTime } from '@/lib/formatters/memory-formatters';
import type { Observation } from './rows';

// Type icons matching the SessionStart hook format
const TYPE_ICONS: Record<string, { icon: string; color: string }> = {
  error: { icon: '🔴', color: 'text-rose-400' },
  warning: { icon: '🟠', color: 'text-amber-400' },
  operational: { icon: '🔵', color: 'text-blue-400' },
  pattern: { icon: '🟢', color: 'text-emerald-400' },
  architecture: { icon: '🟣', color: 'text-purple-400' },
  decision: { icon: '🟣', color: 'text-purple-400' },
  refactoring: { icon: '⚪', color: 'text-slate-400' },
  feature: { icon: '🟢', color: 'text-emerald-400' },
  bugfix: { icon: '🔴', color: 'text-rose-400' },
  discovery: { icon: '🔵', color: 'text-cyan-400' },
  change: { icon: '🔵', color: 'text-blue-400' },
  default: { icon: '⚪', color: 'text-slate-400' },
};

export type ViewMode = 'index' | 'full';

interface ViewModeToggleProps {
  mode: ViewMode;
  onChange: (mode: ViewMode) => void;
}

export function ViewModeToggle({ mode, onChange }: ViewModeToggleProps) {
  return (
    <div className="inline-flex items-center bg-slate-800/60 border border-slate-700/50 rounded-lg p-0.5">
      <button
        onClick={() => onChange('index')}
        className={clsx(
          'relative px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200',
          mode === 'index'
            ? 'text-outrun-400'
            : 'text-slate-500 hover:text-slate-300'
        )}
      >
        {mode === 'index' && (
          <motion.div
            layoutId="view-mode-indicator"
            className="absolute inset-0 bg-outrun-500/15 border border-outrun-500/30 rounded-md"
            transition={{ type: 'spring', bounce: 0.2, duration: 0.4 }}
          />
        )}
        <span className="relative z-10">Index</span>
      </button>
      <button
        onClick={() => onChange('full')}
        className={clsx(
          'relative px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200',
          mode === 'full'
            ? 'text-outrun-400'
            : 'text-slate-500 hover:text-slate-300'
        )}
      >
        {mode === 'full' && (
          <motion.div
            layoutId="view-mode-indicator"
            className="absolute inset-0 bg-outrun-500/15 border border-outrun-500/30 rounded-md"
            transition={{ type: 'spring', bounce: 0.2, duration: 0.4 }}
          />
        )}
        <span className="relative z-10">Full</span>
      </button>
    </div>
  );
}

function estimateTokens(obs: Observation): number {
  const title = obs.title || '';
  const subtitle = obs.subtitle || '';
  const narrative = obs.narrative || '';
  const facts = obs.facts || {};

  const textTokens = Math.ceil((title.length + subtitle.length + narrative.length) / 4);
  const factsTokens = Object.keys(facts).length * 20;

  return textTokens + factsTokens;
}

interface ObservationIndexViewProps {
  observations: Observation[];
  onRowClick?: (observation: Observation) => void;
}

export function ObservationIndexView({ observations, onRowClick }: ObservationIndexViewProps) {
  const tokenStats = useMemo(() => {
    const fullTokens = observations.reduce((sum, obs) => sum + estimateTokens(obs), 0);
    // Index tokens: ~15 tokens per row (time + icon + truncated title + tokens display)
    const indexTokens = observations.length * 15;
    const savings = fullTokens > 0 ? Math.round((1 - indexTokens / fullTokens) * 100) : 0;
    return { indexTokens, fullTokens, savings };
  }, [observations]);

  if (observations.length === 0) {
    return null;
  }

  return (
    <div className="space-y-3">
      {/* Type Legend */}
      <div className="flex items-center gap-4 px-1 text-[11px] text-slate-500">
        <span className="font-medium uppercase tracking-wider">Type:</span>
        <span>🔴 error</span>
        <span>🟠 warning</span>
        <span>🔵 operational</span>
        <span>🟢 pattern</span>
        <span>🟣 architecture</span>
        <span>⚪ other</span>
      </div>

      {/* Index Table */}
      <div className="bg-slate-800/30 border border-slate-700/50 rounded-xl overflow-hidden">
        {/* Table Header */}
        <div className="grid grid-cols-[100px_40px_1fr_80px] gap-2 px-4 py-2.5 bg-slate-800/50 border-b border-slate-700/50">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Time</span>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">T</span>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">Title</span>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 text-right">~Tokens</span>
        </div>

        {/* Table Rows */}
        <div className="divide-y divide-slate-700/30">
          {observations.map((obs, index) => {
            const typeInfo = TYPE_ICONS[obs.observation_type] || TYPE_ICONS.default;
            const tokens = estimateTokens(obs);
            const truncatedTitle = obs.title.length > 60
              ? obs.title.slice(0, 57) + '...'
              : obs.title;

            return (
              <motion.div
                key={obs.id}
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.02 }}
                onClick={() => onRowClick?.(obs)}
                className={clsx(
                  'grid grid-cols-[100px_40px_1fr_80px] gap-2 px-4 py-2.5 transition-colors cursor-pointer',
                  index % 2 === 0 ? 'bg-slate-800/20' : 'bg-transparent',
                  'hover:bg-outrun-500/5 hover:border-l-2 hover:border-l-outrun-500/50'
                )}
              >
                <span className="text-xs text-slate-500 font-mono">
                  {formatTime(obs.created_at)}
                </span>
                <span className="text-center" title={obs.observation_type}>
                  {typeInfo.icon}
                </span>
                <span className="text-sm text-slate-300 truncate">
                  {truncatedTitle}
                </span>
                <span className="text-xs text-slate-500 font-mono text-right">
                  ~{tokens}
                </span>
              </motion.div>
            );
          })}
        </div>
      </div>

      {/* Token Savings Visualization */}
      <div className="bg-slate-800/30 border border-slate-700/50 rounded-lg px-4 py-3">
        <div className="flex items-center justify-between gap-6">
          {/* Stats */}
          <div className="flex items-center gap-4 text-[11px] text-slate-500">
            <span>
              Index: <span className="font-mono text-slate-300">~{tokenStats.indexTokens}</span> tokens
            </span>
            <span className="text-slate-600">vs</span>
            <span>
              Full: <span className="font-mono text-slate-300">~{tokenStats.fullTokens}</span> tokens
            </span>
          </div>

          {/* Progress bar + savings */}
          <div className="flex items-center gap-3 flex-1 max-w-xs">
            <div className="flex-1 h-2 bg-slate-700/50 rounded-full overflow-hidden">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${100 - tokenStats.savings}%` }}
                transition={{ duration: 0.5, ease: 'easeOut' }}
                className="h-full bg-gradient-to-r from-outrun-500 to-outrun-400 rounded-full"
              />
            </div>
            <span className={clsx(
              'text-sm font-semibold tabular-nums min-w-[50px] text-right',
              tokenStats.savings > 50 ? 'text-emerald-400' : tokenStats.savings > 25 ? 'text-amber-400' : 'text-slate-400'
            )}>
              -{tokenStats.savings}%
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

// Hook for persisting view mode preference
const STORAGE_KEY = 'memory-view-mode';

export function useViewMode(): [ViewMode, (mode: ViewMode) => void] {
  const [mode, setMode] = useState<ViewMode>('full');

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'index' || stored === 'full') {
      setMode(stored);
    }
  }, []);

  const setModeWithPersist = (newMode: ViewMode) => {
    setMode(newMode);
    localStorage.setItem(STORAGE_KEY, newMode);
  };

  return [mode, setModeWithPersist];
}
