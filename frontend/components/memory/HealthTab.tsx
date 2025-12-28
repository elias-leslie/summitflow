'use client';

import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  Shield,
  TrendingDown,
  XCircle,
} from 'lucide-react';
import { clsx } from 'clsx';
import { Badge } from '@/components/ui/badge';
import {
  useMemoryHealth,
  useRunHealthCheck,
  type HealthReport,
} from '@/lib/hooks/useMemoryHealth';

// Status indicator component
function StatusIndicator({ status }: { status: HealthReport['status'] }) {
  const config = {
    healthy: {
      icon: CheckCircle2,
      color: 'text-emerald-400',
      bg: 'bg-emerald-400/10',
      border: 'border-emerald-500/30',
      glow: 'shadow-[0_0_12px_rgba(52,211,153,0.3)]',
      label: 'Healthy',
    },
    corrected: {
      icon: RefreshCw,
      color: 'text-blue-400',
      bg: 'bg-blue-400/10',
      border: 'border-blue-500/30',
      glow: 'shadow-[0_0_12px_rgba(59,130,246,0.3)]',
      label: 'Auto-Corrected',
    },
    degraded: {
      icon: AlertTriangle,
      color: 'text-amber-400',
      bg: 'bg-amber-400/10',
      border: 'border-amber-500/30',
      glow: 'shadow-[0_0_12px_rgba(251,191,36,0.3)]',
      label: 'Degraded',
    },
    unhealthy: {
      icon: XCircle,
      color: 'text-rose-400',
      bg: 'bg-rose-400/10',
      border: 'border-rose-500/30',
      glow: 'shadow-[0_0_12px_rgba(251,113,133,0.3)]',
      label: 'Unhealthy',
    },
  };

  const { icon: Icon, color, bg, border, glow, label } = config[status];

  return (
    <div className={clsx('flex items-center gap-3 px-4 py-3 rounded-xl border', bg, border, glow)}>
      <Icon className={clsx('w-6 h-6', color)} />
      <div>
        <div className={clsx('text-lg font-semibold', color)}>{label}</div>
        <div className="text-xs text-slate-500">Memory System Status</div>
      </div>
    </div>
  );
}

// Metric card for stats
function StatCard({
  label,
  value,
  subtitle,
  trend,
}: {
  label: string;
  value: string | number;
  subtitle?: string;
  trend?: 'up' | 'down' | 'neutral';
}) {
  return (
    <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-4">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 mb-1">
        {label}
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-bold text-slate-200">{value}</span>
        {trend === 'down' && <TrendingDown className="w-4 h-4 text-rose-400" />}
      </div>
      {subtitle && <div className="text-xs text-slate-500 mt-1">{subtitle}</div>}
    </div>
  );
}

// Main HealthTab component
export function HealthTab({ projectId }: { projectId: string }) {
  // Use hooks for data fetching
  const { health: fetchedHealth, isLoading: loading, error: fetchError, refresh } = useMemoryHealth(projectId);
  const { run: runCheck, isRunning: running, error: runError, result: checkResult } = useRunHealthCheck(projectId);

  // Use check result if available, otherwise use fetched health
  const health = checkResult || fetchedHealth;
  const error = runError || fetchError;

  // Run health check and update state
  const runHealthCheck = async () => {
    await runCheck();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16 text-slate-500">
        <Activity className="w-5 h-5 animate-spin mr-2" />
        Loading health data...
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-16">
        <XCircle className="w-10 h-10 mx-auto mb-4 text-rose-400 opacity-50" />
        <h3 className="text-lg font-medium text-slate-400 mb-2">Error loading health data</h3>
        <p className="text-sm text-rose-400">{error}</p>
        <button
          onClick={refresh}
          className="mt-4 px-4 py-2 bg-slate-800 text-slate-300 rounded-lg hover:bg-slate-700 transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!health) return null;

  const { metrics, warnings, corrections } = health;
  const filterStats = metrics.filter_stats;
  const obsDistribution = metrics.observation_distribution;
  const patternStatus = metrics.pattern_status;

  return (
    <div className="space-y-6">
      {/* Header with status and action */}
      <div className="flex items-center justify-between">
        <StatusIndicator status={health.status} />
        <button
          onClick={runHealthCheck}
          disabled={running}
          className={clsx(
            'flex items-center gap-2 px-4 py-2.5 rounded-lg font-medium transition-colors',
            running
              ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
              : 'bg-outrun-500/20 text-outrun-400 hover:bg-outrun-500/30 border border-outrun-500/30'
          )}
        >
          <RefreshCw className={clsx('w-4 h-4', running && 'animate-spin')} />
          {running ? 'Running...' : 'Run Health Check'}
        </button>
      </div>

      {/* Capture Stats */}
      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-3">
          Capture Statistics
        </h3>
        <div className="grid grid-cols-4 gap-3">
          <StatCard
            label="Tools Received"
            value={filterStats.tools_received.toLocaleString()}
            subtitle="Total tool executions"
          />
          <StatCard
            label="Tools Queued"
            value={filterStats.tools_queued.toLocaleString()}
            subtitle="Sent for extraction"
          />
          <StatCard
            label="Skip Rate"
            value={`${(filterStats.skip_rate * 100).toFixed(1)}%`}
            subtitle={`${filterStats.tools_skipped.toLocaleString()} skipped`}
            trend={filterStats.skip_rate > 0.5 ? 'down' : 'neutral'}
          />
          <StatCard
            label="Patterns Waiting"
            value={metrics.approved_patterns_waiting}
            subtitle="Ready to apply"
          />
        </div>
      </div>

      {/* Skip Reasons */}
      {Object.keys(filterStats.skip_reasons).length > 0 && (
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-3">
            Skip Reasons
          </h3>
          <div className="flex flex-wrap gap-2">
            {Object.entries(filterStats.skip_reasons)
              .sort(([, a], [, b]) => b - a)
              .map(([reason, count]) => (
                <Badge
                  key={reason}
                  variant="secondary"
                  className="bg-slate-800 text-slate-300 border border-slate-700"
                >
                  {reason.replace('skip_', '').replace('_', ' ')}: {count.toLocaleString()}
                </Badge>
              ))}
          </div>
        </div>
      )}

      {/* Observation Distribution */}
      {Object.keys(obsDistribution).length > 0 && (
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-3">
            Observation Types
          </h3>
          <div className="flex flex-wrap gap-2">
            {Object.entries(obsDistribution)
              .sort(([, a], [, b]) => b - a)
              .map(([type, count]) => (
                <Badge
                  key={type}
                  variant="secondary"
                  className={clsx(
                    'border',
                    type === 'operational'
                      ? 'bg-blue-500/15 text-blue-400 border-blue-500/30'
                      : type === 'error'
                      ? 'bg-rose-500/15 text-rose-400 border-rose-500/30'
                      : type === 'architecture'
                      ? 'bg-purple-500/15 text-purple-400 border-purple-500/30'
                      : 'bg-slate-800 text-slate-300 border-slate-700'
                  )}
                >
                  {type}: {count.toLocaleString()}
                </Badge>
              ))}
          </div>
        </div>
      )}

      {/* Pattern Status */}
      {Object.keys(patternStatus).length > 0 && (
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-3">
            Pattern Status
          </h3>
          <div className="flex flex-wrap gap-2">
            {Object.entries(patternStatus).map(([status, count]) => (
              <Badge
                key={status}
                variant="secondary"
                className={clsx(
                  'border',
                  status === 'pending' && 'bg-amber-500/15 text-amber-400 border-amber-500/30',
                  status === 'approved' && 'bg-blue-500/15 text-blue-400 border-blue-500/30',
                  status === 'applied' && 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
                  status === 'rejected' && 'bg-rose-500/15 text-rose-400 border-rose-500/30'
                )}
              >
                {status}: {count}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Warnings */}
      {warnings.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            Warnings
          </h3>
          <div className="space-y-2">
            {warnings.map((warning, idx) => (
              <div
                key={idx}
                className={clsx(
                  'px-4 py-3 rounded-lg border',
                  warning.severity === 'high'
                    ? 'bg-rose-500/10 border-rose-500/30'
                    : warning.severity === 'medium'
                    ? 'bg-amber-500/10 border-amber-500/30'
                    : 'bg-slate-800/50 border-slate-700/50'
                )}
              >
                <div className="flex items-center gap-2">
                  <Badge
                    variant="secondary"
                    className={clsx(
                      'text-[10px] uppercase',
                      warning.severity === 'high' && 'bg-rose-500/20 text-rose-400',
                      warning.severity === 'medium' && 'bg-amber-500/20 text-amber-400',
                      warning.severity === 'low' && 'bg-slate-700 text-slate-400'
                    )}
                  >
                    {warning.severity}
                  </Badge>
                  <span className="text-xs text-slate-500 font-mono">{warning.type}</span>
                </div>
                <p className="text-sm text-slate-300 mt-1">{warning.message}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Corrections */}
      {corrections.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-2">
            <Shield className="w-4 h-4 text-blue-400" />
            Auto-Corrections Applied
          </h3>
          <div className="space-y-2">
            {corrections.map((correction, idx) => (
              <div
                key={idx}
                className="px-4 py-3 bg-blue-500/10 border border-blue-500/30 rounded-lg"
              >
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-blue-400" />
                  <span className="text-xs text-blue-400 font-mono">{correction.type}</span>
                  <span className="text-xs text-slate-500 ml-auto">
                    {new Date(correction.timestamp).toLocaleTimeString()}
                  </span>
                </div>
                <p className="text-sm text-slate-300 mt-1">{correction.description}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recommendations */}
      {health.recommendations && health.recommendations.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400 mb-3">
            Recommendations
          </h3>
          <div className="space-y-2">
            {health.recommendations.map((rec, idx) => (
              <div
                key={idx}
                className="px-4 py-3 bg-slate-800/50 border border-slate-700/50 rounded-lg"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs text-slate-500 font-mono">{rec.type}</span>
                  <Badge
                    variant="secondary"
                    className={clsx(
                      'text-[10px] uppercase',
                      rec.confidence === 'high' && 'bg-emerald-500/20 text-emerald-400',
                      rec.confidence === 'medium' && 'bg-amber-500/20 text-amber-400',
                      rec.confidence === 'low' && 'bg-slate-700 text-slate-400'
                    )}
                  >
                    {rec.confidence}
                  </Badge>
                </div>
                <p className="text-sm text-slate-300">{rec.reason}</p>
                <div className="flex items-center gap-4 mt-2 text-xs text-slate-500">
                  <span>
                    Current: <span className="text-slate-400">{rec.current}</span>
                  </span>
                  <span>→</span>
                  <span>
                    Recommended: <span className="text-blue-400">{rec.recommended}</span>
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Last updated */}
      <div className="text-xs text-slate-600 text-right">
        Last updated: {new Date(health.timestamp).toLocaleString()}
      </div>
    </div>
  );
}
