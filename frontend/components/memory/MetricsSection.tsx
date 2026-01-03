'use client';

import { clsx } from 'clsx';
import { formatTokens } from '@/lib/formatters/memory-formatters';

interface LifecycleStats {
  failed_queue_count: number;
  stuck_queue_count: number;
  oldest_pending_age_minutes: number | null;
  unreflected_diary_count: number;
  stale_patterns_count: number;
  pattern_status_breakdown: Record<string, number>;
}

interface MemoryStats {
  queue_depth: number;
  queue_pending: number;
  observations_today: number;
  observation_success_rate: number;
  token_spend_24h: number;
  health: 'healthy' | 'degraded' | 'unhealthy';
  health_details: Record<string, string> | null;
  lifecycle: LifecycleStats | null;
  last_access_time: string | null;
}

interface MetricCardProps {
  label: string;
  value: string | number;
  subtitle?: string;
  accent: 'amber' | 'green' | 'blue' | 'health';
  isHealth?: boolean;
  healthStatus?: 'healthy' | 'degraded' | 'unhealthy';
}

function MetricCard({ label, value, subtitle, accent, isHealth, healthStatus }: MetricCardProps) {
  const accentColors = {
    amber: 'text-amber-400',
    green: 'text-emerald-400',
    blue: 'text-blue-400',
    health:
      healthStatus === 'healthy'
        ? 'text-emerald-400'
        : healthStatus === 'degraded'
          ? 'text-amber-400'
          : 'text-rose-400',
  };

  const borderColors = {
    amber: 'before:bg-amber-400',
    green: 'before:bg-emerald-400',
    blue: 'before:bg-blue-400',
    health:
      healthStatus === 'healthy'
        ? 'before:bg-emerald-400'
        : healthStatus === 'degraded'
          ? 'before:bg-amber-400'
          : 'before:bg-rose-400',
  };

  return (
    <div
      className={clsx(
        'relative bg-slate-800/50 border border-slate-700/50 rounded-xl p-5 overflow-hidden',
        'before:absolute before:top-0 before:left-0 before:right-0 before:h-[3px]',
        borderColors[accent]
      )}
    >
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-2">{label}</div>
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
        <div className={clsx('text-3xl font-bold tracking-tight', accentColors[accent])}>{value}</div>
      )}
      {subtitle && <div className="text-[13px] text-slate-500 mt-1">{subtitle}</div>}
    </div>
  );
}

interface MetricsSectionProps {
  stats: MemoryStats | null;
  loading: boolean;
}

export function MetricsSection({ stats, loading }: MetricsSectionProps) {
  if (loading || !stats) {
    return (
      <div className="grid grid-cols-4 gap-4 mb-8">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="bg-slate-800/50 rounded-xl p-5 animate-pulse h-28" />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-4 gap-4 mb-8">
      <MetricCard label="Queue Depth" value={stats.queue_depth} subtitle={`${stats.queue_pending} pending`} accent="amber" />
      <MetricCard
        label="Observations (24h)"
        value={stats.observations_today}
        subtitle={`${Math.round(stats.observation_success_rate * 100)}% success`}
        accent="green"
      />
      <MetricCard label="Token Spend (24h)" value={formatTokens(stats.token_spend_24h) ?? '-'} subtitle="extraction cost" accent="blue" />
      <MetricCard label="System Health" value="" accent="health" isHealth healthStatus={stats.health} />
    </div>
  );
}

export { MetricCard };
export type { MemoryStats, LifecycleStats };
