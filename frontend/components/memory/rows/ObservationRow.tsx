'use client';

import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { clsx } from 'clsx';
import { AnimatePresence, motion } from 'motion/react';
import { formatTime } from '@/lib/formatters/memory-formatters';

export interface Observation {
  id: string;
  project_id: string;
  session_id: string;
  agent_type: string;
  observation_type: string;
  title: string;
  concepts: string[];
  subtitle?: string;
  narrative?: string;
  facts?: Record<string, unknown>;
  files_read?: string[];
  files_modified?: string[];
  tool_name?: string;
  discovery_tokens: number;
  extracted_by?: string;
  created_at: string;
}

const TYPE_COLORS: Record<string, string> = {
  bugfix: 'bg-rose-500/15 text-rose-400 border-rose-500/30',
  feature: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  discovery: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
  refactor: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  decision: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  change: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
  default: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
};

export function ObservationRow({ observation }: { observation: Observation }) {
  const [expanded, setExpanded] = useState(false);

  const typeColor = TYPE_COLORS[observation.observation_type] || TYPE_COLORS.default;

  return (
    <div
      className={clsx(
        'bg-slate-800/50 border rounded-xl overflow-hidden transition-all duration-200',
        expanded ? 'border-outrun-500/50 shadow-outrun-sm' : 'border-slate-700/50 hover:border-slate-600'
      )}
    >
      <div
        className="flex items-center gap-3 px-5 py-4 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <span className={clsx('text-[11px] font-semibold uppercase px-2.5 py-1 rounded border', typeColor)}>
          {observation.observation_type}
        </span>
        <span className="text-[11px] font-medium px-2 py-1 rounded bg-slate-700/50 text-slate-400">
          {observation.agent_type}
        </span>
        <span className="flex-1 text-sm font-medium text-slate-200 truncate">
          {observation.title}
        </span>
        <div className="flex items-center gap-4 text-slate-500 text-[12px]">
          {observation.concepts.slice(0, 2).map((concept) => (
            <span key={concept} className="px-2 py-0.5 rounded-full bg-slate-700/50 text-slate-400">
              {concept}
            </span>
          ))}
          <span className="font-mono">~{observation.discovery_tokens} tok</span>
          {observation.files_modified && (
            <span>{observation.files_modified.length} files</span>
          )}
          <span>{formatTime(observation.created_at)}</span>
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
              {observation.narrative && (
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">
                    Narrative
                  </div>
                  <p className="text-sm text-slate-300 leading-relaxed">{observation.narrative}</p>
                </div>
              )}
              {observation.facts && Object.keys(observation.facts).length > 0 && (
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">
                    Facts Extracted
                  </div>
                  <ul className="space-y-1">
                    {Object.entries(observation.facts).map(([key, value]) => (
                      <li key={key} className="text-sm text-slate-300 pl-4 relative before:absolute before:left-0 before:content-['•'] before:text-outrun-500">
                        {String(value)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {observation.files_modified && observation.files_modified.length > 0 && (
                <div>
                  <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">
                    Files Modified
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {observation.files_modified.map((file) => (
                      <span key={file} className="text-[12px] font-mono px-2.5 py-1 rounded bg-slate-700/50 text-slate-300">
                        {file}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
