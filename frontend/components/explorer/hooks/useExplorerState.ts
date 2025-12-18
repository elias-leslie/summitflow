/**
 * useExplorerState - UI state hook for explorer
 *
 * Responsibilities:
 * - Expansion state (which rows are expanded)
 * - Selection state (which row is selected/focused)
 *
 * Does NOT handle: Data fetching, filters/sorting
 */

import { useState, useCallback, useMemo } from "react";

interface UseExplorerStateOptions {
  /** Initial expanded IDs */
  initialExpanded?: string[];
  /** Initial selected ID */
  initialSelected?: string | null;
}

interface UseExplorerStateReturn {
  // Expansion
  expandedIds: Set<string>;
  isExpanded: (id: string) => boolean;
  toggleExpand: (id: string) => void;
  expand: (id: string) => void;
  collapse: (id: string) => void;
  expandAll: (ids: string[]) => void;
  collapseAll: () => void;
  setExpanded: (ids: string[]) => void;

  // Selection
  selectedId: string | null;
  isSelected: (id: string) => boolean;
  select: (id: string | null) => void;
  clearSelection: () => void;
}

/**
 * Hook for managing explorer UI state (expansion, selection).
 */
export function useExplorerState({
  initialExpanded = [],
  initialSelected = null,
}: UseExplorerStateOptions = {}): UseExplorerStateReturn {
  // Expansion state
  const [expandedIds, setExpandedIds] = useState<Set<string>>(
    () => new Set(initialExpanded)
  );

  // Selection state
  const [selectedId, setSelectedId] = useState<string | null>(initialSelected);

  // Expansion handlers
  const isExpanded = useCallback((id: string) => expandedIds.has(id), [expandedIds]);

  const toggleExpand = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const expand = useCallback((id: string) => {
    setExpandedIds((prev) => {
      if (prev.has(id)) return prev;
      const next = new Set(prev);
      next.add(id);
      return next;
    });
  }, []);

  const collapse = useCallback((id: string) => {
    setExpandedIds((prev) => {
      if (!prev.has(id)) return prev;
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }, []);

  const expandAll = useCallback((ids: string[]) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.add(id));
      return next;
    });
  }, []);

  const collapseAll = useCallback(() => {
    setExpandedIds(new Set());
  }, []);

  const setExpanded = useCallback((ids: string[]) => {
    setExpandedIds(new Set(ids));
  }, []);

  // Selection handlers
  const isSelected = useCallback((id: string) => selectedId === id, [selectedId]);

  const select = useCallback((id: string | null) => {
    setSelectedId(id);
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedId(null);
  }, []);

  return {
    // Expansion
    expandedIds,
    isExpanded,
    toggleExpand,
    expand,
    collapse,
    expandAll,
    collapseAll,
    setExpanded,

    // Selection
    selectedId,
    isSelected,
    select,
    clearSelection,
  };
}
