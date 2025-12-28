'use client';

import { useState, useCallback, useEffect } from 'react';

// Types matching backend API response
export interface FilterStats {
  tools_received: number;
  tools_queued: number;
  tools_skipped: number;
  skip_reasons: Record<string, number>;
  skip_rate: number;
}

export interface EmbeddingCoverage {
  total: number;
  with_embeddings: number;
  coverage_pct: number;
}

export interface Correction {
  type: string;
  description: string;
  details: Record<string, unknown>;
  timestamp: string;
}

export interface Warning {
  type: string;
  message: string;
  severity: 'low' | 'medium' | 'high';
  details: Record<string, unknown>;
}

export interface Recommendation {
  type: string;
  current: string | number;
  recommended: string | number;
  confidence: 'low' | 'medium' | 'high';
  reason: string;
  impact: Record<string, unknown>;
}

export interface RuleAdherenceStats {
  followed: number;
  violated: number;
  rate: number;
}

export interface RuleAdherence {
  by_rule: Record<string, RuleAdherenceStats>;
  overall_rate: number;
  total_observations: number;
}

export interface HealthMetrics {
  filter_stats: FilterStats;
  observation_distribution: Record<string, number>;
  pattern_status: Record<string, number>;
  embedding_coverage: EmbeddingCoverage;
  approved_patterns_waiting: number;
  rule_adherence?: RuleAdherence;
}

export interface HealthReport {
  status: 'healthy' | 'corrected' | 'degraded' | 'unhealthy';
  corrections: Correction[];
  warnings: Warning[];
  metrics: HealthMetrics;
  recommendations: Recommendation[] | null;
  timestamp: string;
}

interface UseMemoryHealthReturn {
  health: HealthReport | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * Hook to fetch memory health status
 * Auto-refreshes on mount
 */
export function useMemoryHealth(projectId: string): UseMemoryHealthReturn {
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(`/api/memory/health?project_id=${projectId}`);

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Failed to fetch health: ${response.status}`);
      }

      const data: HealthReport = await response.json();
      setHealth(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch health';
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return {
    health,
    isLoading,
    error,
    refresh,
  };
}

interface UseRunHealthCheckReturn {
  result: HealthReport | null;
  isRunning: boolean;
  error: string | null;
  run: () => Promise<HealthReport | null>;
}

/**
 * Hook to run a health check (mutation)
 * Returns updated health report after check
 */
export function useRunHealthCheck(projectId: string): UseRunHealthCheckReturn {
  const [result, setResult] = useState<HealthReport | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (): Promise<HealthReport | null> => {
    setIsRunning(true);
    setError(null);

    try {
      const response = await fetch(`/api/memory/health/check?project_id=${projectId}`, {
        method: 'POST',
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Health check failed: ${response.status}`);
      }

      const data: HealthReport = await response.json();
      setResult(data);
      return data;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Health check failed';
      setError(message);
      return null;
    } finally {
      setIsRunning(false);
    }
  }, [projectId]);

  return {
    result,
    isRunning,
    error,
    run,
  };
}
