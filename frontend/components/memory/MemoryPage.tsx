'use client';

import { useState, useEffect } from 'react';
import {
  Brain,
  ChevronDown,
  ChevronRight,
  Activity,
  Zap,
  Clock,
  Check,
  X,
  FileText,
  Lightbulb,
  BookOpen
} from 'lucide-react';
import { clsx } from 'clsx';
import { motion, AnimatePresence } from 'motion/react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { fetchProjects, type Project } from '@/lib/api';
import { BulkActionsBar } from './BulkActionsBar';

// Types
interface MemoryStats {
  queue_depth: number;
  queue_pending: number;
  observations_today: number;
  observation_success_rate: number;
  token_spend_24h: number;
  health: 'healthy' | 'degraded' | 'unhealthy';
  health_details: Record<string, string> | null;
}

interface Observation {
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

interface Pattern {
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

interface DiaryEntry {
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

// Metrics Card Component
function MetricCard({
  label,
  value,
  subtitle,
  accent,
  isHealth,
  healthStatus,
}: {
  label: string;
  value: string | number;
  subtitle?: string;
  accent: 'amber' | 'green' | 'blue' | 'health';
  isHealth?: boolean;
  healthStatus?: 'healthy' | 'degraded' | 'unhealthy';
}) {
  const accentColors = {
    amber: 'text-amber-400',
    green: 'text-emerald-400',
    blue: 'text-blue-400',
    health: healthStatus === 'healthy' ? 'text-emerald-400' : healthStatus === 'degraded' ? 'text-amber-400' : 'text-rose-400',
  };

  const borderColors = {
    amber: 'before:bg-amber-400',
    green: 'before:bg-emerald-400',
    blue: 'before:bg-blue-400',
    health: healthStatus === 'healthy' ? 'before:bg-emerald-400' : healthStatus === 'degraded' ? 'before:bg-amber-400' : 'before:bg-rose-400',
  };

  return (
    <div
      className={clsx(
        'relative bg-slate-800/50 border border-slate-700/50 rounded-xl p-5 overflow-hidden',
        'before:absolute before:top-0 before:left-0 before:right-0 before:h-[3px]',
        borderColors[accent]
      )}
    >
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">
        {label}
      </div>
      {isHealth ? (
        <div className="flex items-center gap-3 mt-2">
          <span
            className={clsx(
              'w-2.5 h-2.5 rounded-full',
              healthStatus === 'healthy'
                ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)] animate-pulse'
                : healthStatus === 'degraded'
                ? 'bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.6)]'
                : 'bg-rose-400 shadow-[0_0_8px_rgba(251,113,133,0.6)]'
            )}
          />
          <span className={clsx('text-sm font-medium', accentColors[accent])}>
            {healthStatus === 'healthy' ? 'All Systems OK' : healthStatus === 'degraded' ? 'Degraded' : 'Unhealthy'}
          </span>
        </div>
      ) : (
        <div className={clsx('text-3xl font-bold tracking-tight', accentColors[accent])}>
          {value}
        </div>
      )}
      {subtitle && (
        <div className="text-[13px] text-slate-500 mt-1">
          {subtitle}
        </div>
      )}
    </div>
  );
}

// Observation Row Component
function ObservationRow({ observation }: { observation: Observation }) {
  const [expanded, setExpanded] = useState(false);

  const typeColors: Record<string, string> = {
    bugfix: 'bg-rose-500/15 text-rose-400 border-rose-500/30',
    feature: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
    discovery: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/30',
    refactor: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
    decision: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
    change: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
    default: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
  };

  const typeColor = typeColors[observation.observation_type] || typeColors.default;

  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
  };

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

// Pattern Row Component
function PatternRow({
  pattern,
  onApprove,
  onReject
}: {
  pattern: Pattern;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);

  const actionColors: Record<string, string> = {
    add: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
    update: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
    remove: 'bg-rose-500/15 text-rose-400 border-rose-500/30',
    merge: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  };

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
          <span className={clsx('text-[10px] font-bold uppercase px-2.5 py-1 rounded border', actionColors[pattern.action] || actionColors.add)}>
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

// Diary Row Component
function DiaryRow({ entry }: { entry: DiaryEntry }) {
  const [expanded, setExpanded] = useState(false);

  const outcomeConfig = {
    success: { color: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30', label: 'Success', barColor: 'bg-emerald-500' },
    failure: { color: 'bg-rose-500/15 text-rose-400 border-rose-500/30', label: 'Failed', barColor: 'bg-rose-500' },
    partial: { color: 'bg-amber-500/15 text-amber-400 border-amber-500/30', label: 'Partial', barColor: 'bg-amber-500' },
    neutral: { color: 'bg-slate-500/15 text-slate-400 border-slate-500/30', label: 'Neutral', barColor: 'bg-slate-500' },
  };

  const config = outcomeConfig[entry.outcome] || outcomeConfig.neutral;

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return null;
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
  };

  const formatTokens = (tokens: number | null) => {
    if (!tokens) return null;
    if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}k`;
    return tokens.toString();
  };

  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
  };

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
        {/* Outcome indicator bar */}
        <div className={clsx('w-1 h-10 rounded-full', config.barColor)} />

        {/* Outcome badge */}
        <span className={clsx('text-[11px] font-semibold uppercase px-2.5 py-1 rounded border', config.color)}>
          {config.label}
        </span>

        {/* Agent badge */}
        <span className="text-[11px] font-medium px-2 py-1 rounded bg-slate-700/50 text-slate-400">
          {entry.agent_type}
        </span>

        {/* Summary */}
        <span className="flex-1 text-sm font-medium text-slate-200 truncate">
          {entry.concepts.length > 0 ? entry.concepts.slice(0, 2).join(', ') : 'Session entry'}
        </span>

        {/* Meta info */}
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
              {/* What worked */}
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

              {/* What failed */}
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

              {/* User corrections */}
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

              {/* Session ID */}
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

// Main Memory Page Component
export default function MemoryPage() {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [observations, setObservations] = useState<Observation[]>([]);
  const [patterns, setPatterns] = useState<Pattern[]>([]);
  const [diaryEntries, setDiaryEntries] = useState<DiaryEntry[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState('observations');
  const [loading, setLoading] = useState(true);
  const [projectDropdownOpen, setProjectDropdownOpen] = useState(false);

  // Fetch data
  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);

        // Fetch stats
        const statsRes = await fetch('/api/memory/stats');
        if (statsRes.ok) {
          const statsData = await statsRes.json();
          setStats(statsData);
        }

        // Fetch observations (global or filtered)
        const obsUrl = selectedProject
          ? `/api/observations?project_id=${selectedProject}`
          : '/api/observations';
        const obsRes = await fetch(obsUrl);
        if (obsRes.ok) {
          const obsData = await obsRes.json();
          setObservations(obsData);
        }

        // Fetch patterns (global or filtered)
        const patUrl = selectedProject
          ? `/api/patterns?project_id=${selectedProject}`
          : '/api/patterns';
        const patRes = await fetch(patUrl);
        if (patRes.ok) {
          const patData = await patRes.json();
          setPatterns(patData);
        }

        // Fetch diary entries (global or filtered)
        const diaryUrl = selectedProject
          ? `/api/diary?project_id=${selectedProject}`
          : '/api/diary';
        const diaryRes = await fetch(diaryUrl);
        if (diaryRes.ok) {
          const diaryData = await diaryRes.json();
          setDiaryEntries(diaryData);
        }

        // Fetch projects for filter
        const projectsData = await fetchProjects();
        setProjects(projectsData);
      } catch (error) {
        console.error('Failed to fetch memory data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [selectedProject]);

  const handleApprovePattern = async (patternId: string) => {
    try {
      const res = await fetch('/api/patterns/bulk-approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pattern_ids: [patternId], reason: 'user-approved' }),
      });
      if (res.ok) {
        setPatterns(patterns.map(p => p.id === patternId ? { ...p, status: 'approved' } : p));
      }
    } catch (error) {
      console.error('Failed to approve pattern:', error);
    }
  };

  const handleRejectPattern = async (patternId: string) => {
    try {
      const res = await fetch('/api/patterns/bulk-reject', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pattern_ids: [patternId], reason: 'user-rejected' }),
      });
      if (res.ok) {
        setPatterns(patterns.map(p => p.id === patternId ? { ...p, status: 'rejected' } : p));
      }
    } catch (error) {
      console.error('Failed to reject pattern:', error);
    }
  };

  const formatTokens = (tokens: number) => {
    if (tokens >= 1000) {
      return `${(tokens / 1000).toFixed(1)}k`;
    }
    return tokens.toString();
  };

  const pendingPatterns = patterns.filter(p => p.status === 'pending');

  return (
    <div className="min-h-screen bg-slate-950 p-8">
      <div className="max-w-[1400px] mx-auto">
        {/* Header */}
        <header className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-4">
            <Brain className="w-7 h-7 text-outrun-500" />
            <h1 className="text-[28px] font-semibold text-slate-100 tracking-tight">Memory</h1>
          </div>

          {/* Project Filter Dropdown */}
          <div className="relative">
            <button
              onClick={() => setProjectDropdownOpen(!projectDropdownOpen)}
              className="flex items-center gap-2 px-4 py-2 bg-slate-800/50 border border-slate-700/50 rounded-lg hover:border-slate-600 transition-colors"
            >
              <span className="text-sm text-slate-400">Project:</span>
              <span className="text-sm font-medium text-slate-200">
                {selectedProject ? projects.find(p => p.id === selectedProject)?.name || selectedProject : 'All Projects'}
              </span>
              <ChevronDown className="w-4 h-4 text-slate-500" />
            </button>

            <AnimatePresence>
              {projectDropdownOpen && (
                <motion.div
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -4 }}
                  className="absolute right-0 top-full mt-2 w-56 bg-slate-800 border border-slate-700 rounded-lg shadow-xl z-50 overflow-hidden"
                >
                  <button
                    onClick={() => { setSelectedProject(null); setProjectDropdownOpen(false); }}
                    className={clsx(
                      'w-full px-4 py-2.5 text-left text-sm hover:bg-slate-700/50 transition-colors',
                      !selectedProject ? 'text-outrun-400 bg-outrun-500/10' : 'text-slate-300'
                    )}
                  >
                    All Projects
                  </button>
                  {projects.map((project) => (
                    <button
                      key={project.id}
                      onClick={() => { setSelectedProject(project.id); setProjectDropdownOpen(false); }}
                      className={clsx(
                        'w-full px-4 py-2.5 text-left text-sm hover:bg-slate-700/50 transition-colors',
                        selectedProject === project.id ? 'text-outrun-400 bg-outrun-500/10' : 'text-slate-300'
                      )}
                    >
                      {project.name}
                    </button>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </header>

        {/* Metrics Grid */}
        <div className="grid grid-cols-4 gap-4 mb-8">
          <MetricCard
            label="Queue Depth"
            value={stats?.queue_depth ?? '-'}
            subtitle={stats ? `${stats.queue_pending} pending extraction` : undefined}
            accent="amber"
          />
          <MetricCard
            label="Observations"
            value={stats?.observations_today ?? '-'}
            subtitle={stats ? `${stats.observation_success_rate}% extraction success` : undefined}
            accent="green"
          />
          <MetricCard
            label="Token Spend"
            value={stats ? formatTokens(stats.token_spend_24h) : '-'}
            subtitle="24h total"
            accent="blue"
          />
          <MetricCard
            label="System Health"
            value=""
            subtitle="Hook connected"
            accent="health"
            isHealth
            healthStatus={stats?.health ?? 'healthy'}
          />
        </div>

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="border-slate-700/50 mb-6">
            <TabsTrigger value="observations" className="gap-2">
              <FileText className="w-4 h-4" />
              Observations
              <span className={clsx(
                'text-[11px] font-semibold px-2 py-0.5 rounded-full',
                activeTab === 'observations' ? 'bg-outrun-500/15 text-outrun-400' : 'bg-slate-700/50 text-slate-500'
              )}>
                {observations.length}
              </span>
            </TabsTrigger>
            <TabsTrigger value="patterns" className="gap-2">
              <Lightbulb className="w-4 h-4" />
              Patterns
              <span className={clsx(
                'text-[11px] font-semibold px-2 py-0.5 rounded-full',
                activeTab === 'patterns' ? 'bg-outrun-500/15 text-outrun-400' : 'bg-slate-700/50 text-slate-500'
              )}>
                {pendingPatterns.length}
              </span>
            </TabsTrigger>
            <TabsTrigger value="diary" className="gap-2">
              <BookOpen className="w-4 h-4" />
              Diary
            </TabsTrigger>
          </TabsList>

          {/* Observations Tab */}
          <TabsContent value="observations">
            {loading ? (
              <div className="flex items-center justify-center py-16 text-slate-500">
                <Activity className="w-5 h-5 animate-spin mr-2" />
                Loading observations...
              </div>
            ) : observations.length === 0 ? (
              <div className="text-center py-16 text-slate-500">
                <FileText className="w-10 h-10 mx-auto mb-4 opacity-30" />
                <h3 className="text-lg font-medium text-slate-400 mb-2">No observations yet</h3>
                <p className="text-sm">Observations will appear here as agents work</p>
              </div>
            ) : (
              <div className="space-y-2">
                {observations.map((obs) => (
                  <ObservationRow key={obs.id} observation={obs} />
                ))}
              </div>
            )}
          </TabsContent>

          {/* Patterns Tab */}
          <TabsContent value="patterns">
            {loading ? (
              <div className="flex items-center justify-center py-16 text-slate-500">
                <Activity className="w-5 h-5 animate-spin mr-2" />
                Loading patterns...
              </div>
            ) : pendingPatterns.length === 0 ? (
              <div className="text-center py-16 text-slate-500">
                <Lightbulb className="w-10 h-10 mx-auto mb-4 opacity-30" />
                <h3 className="text-lg font-medium text-slate-400 mb-2">No pending patterns</h3>
                <p className="text-sm">Patterns will appear here for review after reflection</p>
              </div>
            ) : (
              <div className="space-y-4">
                <BulkActionsBar
                  patterns={pendingPatterns}
                  onBulkApprove={async (patternIds) => {
                    try {
                      const res = await fetch('/api/patterns/bulk-approve', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ pattern_ids: patternIds, reason: 'bulk-approved' }),
                      });
                      if (res.ok) {
                        setPatterns(patterns.map(p =>
                          patternIds.includes(p.id) ? { ...p, status: 'approved' } : p
                        ));
                      }
                    } catch (error) {
                      console.error('Failed to bulk approve patterns:', error);
                    }
                  }}
                />
                <div className="space-y-2">
                  {pendingPatterns.map((pattern) => (
                    <PatternRow
                      key={pattern.id}
                      pattern={pattern}
                      onApprove={handleApprovePattern}
                      onReject={handleRejectPattern}
                    />
                  ))}
                </div>
              </div>
            )}
          </TabsContent>

          {/* Diary Tab */}
          <TabsContent value="diary">
            {loading ? (
              <div className="flex items-center justify-center py-16 text-slate-500">
                <Activity className="w-5 h-5 animate-spin mr-2" />
                Loading diary entries...
              </div>
            ) : diaryEntries.length === 0 ? (
              <div className="text-center py-16 text-slate-500">
                <BookOpen className="w-10 h-10 mx-auto mb-4 opacity-30" />
                <h3 className="text-lg font-medium text-slate-400 mb-2">No diary entries yet</h3>
                <p className="text-sm">Session summaries will appear here</p>
              </div>
            ) : (
              <div className="space-y-2">
                {diaryEntries.map((entry) => (
                  <DiaryRow key={entry.id} entry={entry} />
                ))}
              </div>
            )}
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
