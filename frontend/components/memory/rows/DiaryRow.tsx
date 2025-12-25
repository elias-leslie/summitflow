'use client';

import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { clsx } from 'clsx';
import { AnimatePresence, motion } from 'motion/react';
import { formatTime, formatDuration, formatTokens } from '@/lib/formatters/memory-formatters';

export interface DiaryEntry {
  id: string;
  project_id: string;
  session_id: string;
  task_id: string | null;
  agent_type: string;
  duration_seconds: number | null;
  tokens_used: number | null;
  discovery_tokens: number | null;
  outcome: 'success' | 'failure' | 'partial' | 'neutral';
  observation_type: string | null;
  concepts: string[];
  what_worked: string[] | null;
  what_failed: string[] | null;
  user_corrections: string[] | null;
  created_at: string;
}

const OUTCOME_CONFIG = {
  success: { color: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30', label: 'Success', barColor: 'bg-emerald-500' },
  failure: { color: 'bg-rose-500/15 text-rose-400 border-rose-500/30', label: 'Failed', barColor: 'bg-rose-500' },
  partial: { color: 'bg-amber-500/15 text-amber-400 border-amber-500/30', label: 'Partial', barColor: 'bg-amber-500' },
  neutral: { color: 'bg-slate-500/15 text-slate-400 border-slate-500/30', label: 'Neutral', barColor: 'bg-slate-500' },
};

export function DiaryRow({ entry }: { entry: DiaryEntry }) {
  const [expanded, setExpanded] = useState(false);

  const config = OUTCOME_CONFIG[entry.outcome] || OUTCOME_CONFIG.neutral;

  return (
    <div
      className={clsx(
        'bg-slate-800/50 border rounded-xl overflow-hidden transition-all duration-200',
        expanded ? 'border-slate-600' : 'border-slate-700/50 hover:border-slate-600'
      )}
    >
      <div
        className="flex items-center gap-3 px-5 py-4 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className={clsx('w-1 h-10 rounded-full', config.barColor)} />
        <span className={clsx('text-[11px] font-semibold uppercase px-2.5 py-1 rounded border', config.color)}>
          {config.label}
        </span>
        <span className="text-[11px] font-medium px-2 py-1 rounded bg-slate-700/50 text-slate-400">
          {entry.agent_type}
        </span>
        <span className="flex-1 text-sm font-medium text-slate-200 truncate">
          {entry.concepts.length > 0 ? entry.concepts.slice(0, 2).join(', ') : 'Session entry'}
        </span>
        <div className="flex items-center gap-4 text-slate-500 text-[12px]">
          {entry.tokens_used && (
            <span className="font-mono">{formatTokens(entry.tokens_used)} tok</span>
          )}
          {entry.duration_seconds && (
            <span>{formatDuration(entry.duration_seconds)}</span>
          )}
          <span>{formatTime(entry.created_at)}</span>
        </div>
        <ChevronDown
          className={clsx(
            'w-5 h-5 text-slate-500 transition-transform duration-200',
            expanded && 'rotate-180'
          )}
        />
      </div>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="border-t border-slate-700/50 bg-slate-900/50"
          >
            <div className="px-5 py-4 space-y-4">
              {entry.what_worked && entry.what_worked.length > 0 && (
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-emerald-500 mb-2">
                    What Worked
                  </div>
                  <ul className="space-y-1">
                    {entry.what_worked.map((item, i) => (
                      <li key={i} className="text-sm text-slate-300 pl-4 relative before:absolute before:left-0 before:content-['•'] before:text-emerald-500">
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {entry.what_failed && entry.what_failed.length > 0 && (
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-rose-500 mb-2">
                    What Failed
                  </div>
                  <ul className="space-y-1">
                    {entry.what_failed.map((item, i) => (
                      <li key={i} className="text-sm text-slate-300 pl-4 relative before:absolute before:left-0 before:content-['•'] before:text-rose-500">
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {entry.user_corrections && entry.user_corrections.length > 0 && (
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-amber-500 mb-2">
                    User Corrections
                  </div>
                  <ul className="space-y-1">
                    {entry.user_corrections.map((item, i) => (
                      <li key={i} className="text-sm text-slate-300 pl-4 relative before:absolute before:left-0 before:content-['•'] before:text-amber-500">
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="text-[12px] text-slate-500">
                Session: {entry.session_id.slice(0, 8)}...
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
