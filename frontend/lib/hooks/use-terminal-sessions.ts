"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

// ============================================================================
// Types
// ============================================================================

export interface TerminalSession {
  id: string;
  name: string;
  user_id: string | null;
  project_id: string | null;
  working_dir: string | null;
  display_order: number;
  is_alive: boolean;
  created_at: string | null;
  last_accessed_at: string | null;
}

interface SessionListResponse {
  items: TerminalSession[];
  total: number;
}

interface CreateSessionRequest {
  name: string;
  project_id?: string;
  working_dir?: string;
}

interface UpdateSessionRequest {
  name?: string;
  display_order?: number;
}

// ============================================================================
// API Functions
// ============================================================================

async function fetchSessions(): Promise<TerminalSession[]> {
  const res = await fetch("/api/terminal/sessions");
  if (!res.ok) throw new Error("Failed to fetch terminal sessions");
  const data: SessionListResponse = await res.json();
  return data.items;
}

async function createSession(request: CreateSessionRequest): Promise<TerminalSession> {
  const res = await fetch("/api/terminal/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Failed to create session" }));
    throw new Error(error.detail || "Failed to create session");
  }
  return res.json();
}

async function updateSession(
  sessionId: string,
  request: UpdateSessionRequest
): Promise<TerminalSession> {
  const res = await fetch(`/api/terminal/sessions/${sessionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Failed to update session" }));
    throw new Error(error.detail || "Failed to update session");
  }
  return res.json();
}

async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`/api/terminal/sessions/${sessionId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete session");
}

// ============================================================================
// Hook
// ============================================================================

/**
 * Hook for managing terminal sessions with backend sync.
 *
 * Provides:
 * - sessions: List of terminal sessions from backend
 * - activeId: Currently active session ID
 * - setActiveId: Set active session
 * - create: Create new session (server generates ID)
 * - update: Update session metadata
 * - remove: Delete session (also kills tmux)
 * - isLoading, isError, error: Query state
 *
 * @param projectId - Optional project ID for new sessions
 *
 * @example
 * ```tsx
 * const { sessions, activeId, create, remove } = useTerminalSessions();
 *
 * return (
 *   <div>
 *     {sessions.map(s => (
 *       <button key={s.id} onClick={() => setActiveId(s.id)}>
 *         {s.name}
 *       </button>
 *     ))}
 *     <button onClick={() => create("Terminal")}>New</button>
 *   </div>
 * );
 * ```
 */
export function useTerminalSessions(projectId?: string) {
  const queryClient = useQueryClient();
  const [activeId, setActiveId] = useState<string | null>(null);

  // Query: fetch sessions
  const {
    data: sessions = [],
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["terminal-sessions"],
    queryFn: fetchSessions,
    refetchInterval: 30000, // Refresh every 30s to catch dead sessions
  });

  // Set initial active session when sessions load
  // (if no active ID set and we have sessions)
  if (!activeId && sessions.length > 0) {
    setActiveId(sessions[0].id);
  }

  // Mutation: create session
  const createMutation = useMutation({
    mutationFn: createSession,
    onSuccess: (newSession) => {
      queryClient.invalidateQueries({ queryKey: ["terminal-sessions"] });
      // Switch to new session
      setActiveId(newSession.id);
    },
  });

  // Mutation: update session
  const updateMutation = useMutation({
    mutationFn: ({ sessionId, ...request }: UpdateSessionRequest & { sessionId: string }) =>
      updateSession(sessionId, request),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["terminal-sessions"] });
    },
  });

  // Mutation: delete session
  const deleteMutation = useMutation({
    mutationFn: deleteSession,
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ["terminal-sessions"] });
      // If deleted active session, switch to another
      if (activeId === deletedId) {
        const remaining = sessions.filter((s) => s.id !== deletedId);
        setActiveId(remaining[0]?.id ?? null);
      }
    },
  });

  // Create new session
  const create = useCallback(
    async (name: string, workingDir?: string) => {
      return createMutation.mutateAsync({
        name,
        project_id: projectId,
        working_dir: workingDir,
      });
    },
    [createMutation, projectId]
  );

  // Update session
  const update = useCallback(
    async (sessionId: string, updates: UpdateSessionRequest) => {
      return updateMutation.mutateAsync({ sessionId, ...updates });
    },
    [updateMutation]
  );

  // Remove session
  const remove = useCallback(
    async (sessionId: string) => {
      return deleteMutation.mutateAsync(sessionId);
    },
    [deleteMutation]
  );

  return {
    sessions,
    activeId,
    setActiveId,
    create,
    update,
    remove,
    isLoading,
    isError,
    error,
    isCreating: createMutation.isPending,
    isDeleting: deleteMutation.isPending,
  };
}
