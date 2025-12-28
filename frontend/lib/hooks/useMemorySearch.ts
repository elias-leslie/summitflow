'use client';

import { useState, useCallback } from 'react';

export interface SearchResult {
  entity_type: 'observation' | 'pattern' | 'user_prompt' | 'diary';
  id: string;
  title: string | null;
  summary: string | null;
  score: number;
  created_at: string | null;
  data: Record<string, unknown>;
}

export interface SearchResponse {
  query: string;
  use_semantic: boolean;
  total: number;
  results: SearchResult[];
}

export interface SearchParams {
  q: string;
  project_id: string;
  type?: string;
  concepts?: string[];
  use_semantic?: boolean;
  limit?: number;
}

interface UseMemorySearchReturn {
  results: SearchResult[];
  total: number;
  usedSemantic: boolean;
  isLoading: boolean;
  error: string | null;
  search: (params: SearchParams) => Promise<void>;
  clear: () => void;
}

export function useMemorySearch(): UseMemorySearchReturn {
  const [results, setResults] = useState<SearchResult[]>([]);
  const [total, setTotal] = useState(0);
  const [usedSemantic, setUsedSemantic] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const search = useCallback(async (params: SearchParams) => {
    setIsLoading(true);
    setError(null);

    try {
      const searchParams = new URLSearchParams({
        q: params.q,
        project_id: params.project_id,
        limit: String(params.limit ?? 20),
      });

      if (params.type && params.type !== 'all') {
        searchParams.set('type', params.type);
      }
      if (params.concepts && params.concepts.length > 0) {
        searchParams.set('concepts', params.concepts.join(','));
      }
      if (params.use_semantic) {
        searchParams.set('use_semantic', 'true');
      }

      const response = await fetch(`/api/memory/search?${searchParams.toString()}`);

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Search failed: ${response.status}`);
      }

      const data: SearchResponse = await response.json();

      setResults(data.results);
      setTotal(data.total);
      setUsedSemantic(data.use_semantic);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Search failed';
      setError(message);
      setResults([]);
      setTotal(0);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const clear = useCallback(() => {
    setResults([]);
    setTotal(0);
    setUsedSemantic(false);
    setError(null);
  }, []);

  return {
    results,
    total,
    usedSemantic,
    isLoading,
    error,
    search,
    clear,
  };
}
