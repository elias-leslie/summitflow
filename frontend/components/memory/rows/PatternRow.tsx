'use client';

import { useState } from 'react';
import { ChevronDown, Check, X } from 'lucide-react';
import { clsx } from 'clsx';
import { AnimatePresence, motion } from 'motion/react';

export interface Pattern {
  id: string;
  project_id: string;
  pattern_type: string;
  title: string;
  content: string;
  rationale?: string;
  action: string;
  status: string;
  confidence: number;
  created_at: string;
  reflected_by?: string;
}

const ACTION_COLORS: Record<string, string> = {
  add: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  update: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  remove: 'bg-rose-500/15 text-rose-400 border-rose-500/30',
  merge: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
};

export function PatternRow({
  pattern,
  onApprove,
  onReject
}: {
  pattern: Pattern;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  const confidenceColor = pattern.confidence >= 0.85 ? 'text-emerald-400' : pattern.confidence >= 0.7 ? 'text-amber-400' : 'text-slate-400';

  return (
    <div
      className={clsx(
        'bg-slate-800/50 border rounded-xl overflow-hidden transition-all duration-200',
        expanded ? 'border-purple-500/50 shadow-[0_0_10px_rgba(168,85,247,0.15)]' : 'border-slate-700/50 hover:border-slate-600'
      )}
    >
      <div className="flex items-center gap-3 px-5 py-4">
        <div
          className="flex-1 flex items-center gap-3 cursor-pointer"
          onClick={() => setExpanded(!expanded)}
        >
          <span className={clsx('text-[10px] font-bold uppercase px-2.5 py-1 rounded border', ACTION_COLORS[pattern.action] || ACTION_COLORS.add)}>
            {pattern.action}
          </span>
          <span className={clsx('text-[13px] font-semibold font-mono px-2.5 py-1 rounded bg-slate-700/50', confidenceColor)}>
            {Math.round(pattern.confidence * 100)}%
          </span>
          <div className="flex-1">
            <div className="text-sm font-medium text-slate-200">{pattern.title}</div>
            <div className="text-[13px] text-slate-500 truncate">{pattern.content}</div>
          </div>
        </div>
        {pattern.status === 'pending' && (
          <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
            <button
              onClick={() => onApprove(pattern.id)}
              className="w-8 h-8 flex items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400 hover:bg-emerald-500/25 transition-colors"
            >
              <Check className="w-4 h-4" />
            </button>
            <button
              onClick={() => onReject(pattern.id)}
              className="w-8 h-8 flex items-center justify-center rounded-lg bg-rose-500/15 text-rose-400 hover:bg-rose-500/25 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        )}
        <ChevronDown
          className={clsx(
            'w-5 h-5 text-slate-500 transition-transform duration-200 cursor-pointer',
            expanded && 'rotate-180'
          )}
          onClick={() => setExpanded(!expanded)}
        />
      </div>

      <AnimatePresence>
        {expanded && pattern.rationale && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="border-t border-slate-700/50 bg-slate-900/50"
          >
            <div className="px-5 py-4">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">
                Rationale
              </div>
              <p className="text-sm text-slate-300 leading-relaxed">{pattern.rationale}</p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
