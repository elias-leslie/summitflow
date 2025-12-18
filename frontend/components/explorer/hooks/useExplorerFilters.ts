/**
 * useExplorerFilters - Filter and sort state hook for explorer
 *
 * Responsibilities:
 * - Filter values (type, health, path)
 * - Sort field and direction
 * - Pagination state
 *
 * Does NOT handle: Data fetching, UI state (expanded/selected)
 */

import { useState, useCallback, useMemo } from "react";
import type {
  ExplorerEntryType,
  ExplorerHealthStatus,
  ExplorerFilters,
} from "@/lib/api/explorer";

type SortField = "path" | "name" | "health_status" | "last_scanned_at";
type SortDir = "asc" | "desc";

interface UseExplorerFiltersOptions {
  /** Initial entry type filter */
  initialType?: ExplorerEntryType;
  /** Initial health status filter */
  initialHealth?: ExplorerHealthStatus | "all";
  /** Initial path prefix filter */
  initialPath?: string;
  /** Initial sort field */
  initialSort?: SortField;
  /** Initial sort direction */
  initialSortDir?: SortDir;
  /** Page size */
  pageSize?: number;
}

interface UseExplorerFiltersReturn {
  // Filter values
  type: ExplorerEntryType | undefined;
  health: ExplorerHealthStatus | undefined;
  path: string | undefined;
  sortField: SortField;
  sortDir: SortDir;
  limit: number;
  offset: number;

  // Computed filters object for API
  filters: ExplorerFilters;

  // Setters
  setType: (type: ExplorerEntryType | undefined) => void;
  setHealth: (health: ExplorerHealthStatus | "all") => void;
  setPath: (path: string | undefined) => void;
  setSort: (field: SortField, dir?: SortDir) => void;
  toggleSort: (field: SortField) => void;
  setPage: (page: number) => void;
  nextPage: () => void;
  prevPage: () => void;

  // Reset
  reset: () => void;
  resetFilters: () => void;
  resetSort: () => void;
  resetPagination: () => void;

  // Helpers
  currentPage: number;
  hasFilters: boolean;
}

/**
 * Hook for managing explorer filter and sort state.
 */
export function useExplorerFilters({
  initialType,
  initialHealth = "all",
  initialPath,
  initialSort = "path",
  initialSortDir = "asc",
  pageSize = 1000,
}: UseExplorerFiltersOptions = {}): UseExplorerFiltersReturn {
  // Filter state
  const [type, setType] = useState<ExplorerEntryType | undefined>(initialType);
  const [health, setHealthState] = useState<ExplorerHealthStatus | undefined>(
    initialHealth === "all" ? undefined : initialHealth
  );
  const [path, setPath] = useState<string | undefined>(initialPath);

  // Sort state
  const [sortField, setSortField] = useState<SortField>(initialSort);
  const [sortDir, setSortDir] = useState<SortDir>(initialSortDir);

  // Pagination state
  const [offset, setOffset] = useState(0);
  const limit = pageSize;

  // Health setter that handles "all"
  const setHealth = useCallback((value: ExplorerHealthStatus | "all") => {
    setHealthState(value === "all" ? undefined : value);
    setOffset(0); // Reset pagination on filter change
  }, []);

  // Type setter that resets pagination
  const handleSetType = useCallback((value: ExplorerEntryType | undefined) => {
    setType(value);
    setOffset(0);
  }, []);

  // Path setter that resets pagination
  const handleSetPath = useCallback((value: string | undefined) => {
    setPath(value);
    setOffset(0);
  }, []);

  // Sort setters
  const setSort = useCallback((field: SortField, dir?: SortDir) => {
    setSortField(field);
    if (dir) setSortDir(dir);
  }, []);

  const toggleSort = useCallback(
    (field: SortField) => {
      if (sortField === field) {
        setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      } else {
        setSortField(field);
        setSortDir("asc");
      }
    },
    [sortField]
  );

  // Pagination helpers
  const currentPage = Math.floor(offset / limit) + 1;

  const setPage = useCallback(
    (page: number) => {
      setOffset((page - 1) * limit);
    },
    [limit]
  );

  const nextPage = useCallback(() => {
    setOffset((o) => o + limit);
  }, [limit]);

  const prevPage = useCallback(() => {
    setOffset((o) => Math.max(0, o - limit));
  }, [limit]);

  // Reset functions
  const resetFilters = useCallback(() => {
    setType(initialType);
    setHealthState(initialHealth === "all" ? undefined : initialHealth);
    setPath(initialPath);
    setOffset(0);
  }, [initialType, initialHealth, initialPath]);

  const resetSort = useCallback(() => {
    setSortField(initialSort);
    setSortDir(initialSortDir);
  }, [initialSort, initialSortDir]);

  const resetPagination = useCallback(() => {
    setOffset(0);
  }, []);

  const reset = useCallback(() => {
    resetFilters();
    resetSort();
    resetPagination();
  }, [resetFilters, resetSort, resetPagination]);

  // Computed filters object for API
  const filters = useMemo<ExplorerFilters>(
    () => ({
      type,
      health,
      path,
      sort: sortField,
      dir: sortDir,
      limit,
      offset,
    }),
    [type, health, path, sortField, sortDir, limit, offset]
  );

  // Check if any non-default filters are applied
  const hasFilters = useMemo(
    () =>
      type !== initialType ||
      health !== (initialHealth === "all" ? undefined : initialHealth) ||
      path !== initialPath,
    [type, health, path, initialType, initialHealth, initialPath]
  );

  return {
    // Values
    type,
    health,
    path,
    sortField,
    sortDir,
    limit,
    offset,
    filters,

    // Setters
    setType: handleSetType,
    setHealth,
    setPath: handleSetPath,
    setSort,
    toggleSort,
    setPage,
    nextPage,
    prevPage,

    // Reset
    reset,
    resetFilters,
    resetSort,
    resetPagination,

    // Helpers
    currentPage,
    hasFilters,
  };
}
