"use client";

import { useCallback, useState, useRef, useEffect } from "react";
import { clsx } from "clsx";
import { TerminalComponent } from "./Terminal";
import { Plus, X, Terminal as TerminalIcon, Loader2 } from "lucide-react";
import { useTerminalSessions } from "@/lib/hooks/use-terminal-sessions";

interface TerminalTabsProps {
  projectId?: string;
  projectPath?: string;
  className?: string;
}

export function TerminalTabs({ projectId, projectPath, className }: TerminalTabsProps) {
  const {
    sessions,
    activeId,
    setActiveId,
    create,
    update,
    remove,
    isLoading,
    isCreating,
  } = useTerminalSessions(projectId);

  // Editing state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const editInputRef = useRef<HTMLInputElement>(null);

  // Focus input when entering edit mode
  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingId]);

  // Create new terminal session
  const handleAddTab = useCallback(async () => {
    const name = `Terminal ${sessions.length + 1}`;
    await create(name, projectPath);
  }, [sessions.length, create, projectPath]);

  // Close terminal session
  const handleCloseTab = useCallback(
    async (sessionId: string, e: React.MouseEvent) => {
      e.stopPropagation();
      // Don't close the last session
      if (sessions.length <= 1) return;
      await remove(sessionId);
    },
    [sessions.length, remove]
  );

  // Start editing tab name
  const handleStartEdit = useCallback((sessionId: string, currentName: string) => {
    setEditingId(sessionId);
    setEditValue(currentName);
  }, []);

  // Save edited name
  const handleSaveEdit = useCallback(async () => {
    if (!editingId || !editValue.trim()) {
      setEditingId(null);
      return;
    }

    await update(editingId, { name: editValue.trim() });
    setEditingId(null);
  }, [editingId, editValue, update]);

  // Cancel editing
  const handleCancelEdit = useCallback(() => {
    setEditingId(null);
    setEditValue("");
  }, []);

  // Handle keyboard events in edit mode
  const handleEditKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") {
        e.preventDefault();
        handleSaveEdit();
      } else if (e.key === "Escape") {
        handleCancelEdit();
      }
    },
    [handleSaveEdit, handleCancelEdit]
  );

  // Loading state
  if (isLoading) {
    return (
      <div className={clsx("flex flex-col h-full items-center justify-center", className)}>
        <Loader2 className="w-6 h-6 text-slate-400 animate-spin" />
        <span className="mt-2 text-sm text-slate-500">Loading terminals...</span>
      </div>
    );
  }

  // No sessions - show create button
  if (sessions.length === 0) {
    return (
      <div className={clsx("flex flex-col h-full items-center justify-center", className)}>
        <TerminalIcon className="w-12 h-12 text-slate-600 mb-4" />
        <p className="text-slate-400 mb-4">No terminal sessions</p>
        <button
          onClick={handleAddTab}
          disabled={isCreating}
          className="flex items-center gap-2 px-4 py-2 bg-phosphor-500 hover:bg-phosphor-400 text-slate-900 rounded-lg transition-colors disabled:opacity-50"
        >
          {isCreating ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Plus className="w-4 h-4" />
          )}
          <span>New Terminal</span>
        </button>
      </div>
    );
  }

  return (
    <div className={clsx("flex flex-col h-full", className)}>
      {/* Tab bar */}
      <div className="flex items-center gap-1 px-2 py-1 bg-slate-800 border-b border-slate-700 overflow-x-auto">
        {sessions.map((session) => (
          <button
            key={session.id}
            onClick={() => setActiveId(session.id)}
            className={clsx(
              "flex items-center gap-2 px-3 py-1.5 text-sm rounded-t-md transition-colors",
              "group min-w-0 flex-shrink-0",
              session.id === activeId
                ? "bg-slate-900 text-white border-t border-l border-r border-slate-700"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-700/50"
            )}
          >
            <TerminalIcon className="w-3.5 h-3.5 flex-shrink-0" />
            {editingId === session.id ? (
              <input
                ref={editInputRef}
                type="text"
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                onBlur={handleSaveEdit}
                onKeyDown={handleEditKeyDown}
                className="bg-slate-800 border border-slate-600 rounded px-1 py-0 text-sm w-24 focus:outline-none focus:ring-1 focus:ring-phosphor-500"
                onClick={(e) => e.stopPropagation()}
              />
            ) : (
              <span
                className="truncate max-w-[120px]"
                onDoubleClick={(e) => {
                  e.stopPropagation();
                  handleStartEdit(session.id, session.name);
                }}
              >
                {session.name}
                {!session.is_alive && " (dead)"}
              </span>
            )}
            {sessions.length > 1 && (
              <button
                onClick={(e) => handleCloseTab(session.id, e)}
                className={clsx(
                  "p-0.5 rounded hover:bg-slate-600 opacity-0 group-hover:opacity-100 transition-opacity",
                  session.id === activeId && "opacity-100"
                )}
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </button>
        ))}

        {/* Add new terminal button */}
        <button
          onClick={handleAddTab}
          disabled={isCreating}
          className="flex items-center gap-1 px-2 py-1.5 text-sm text-slate-400 hover:text-white hover:bg-slate-700/50 rounded transition-colors disabled:opacity-50"
        >
          {isCreating ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Plus className="w-4 h-4" />
          )}
        </button>
      </div>

      {/* Terminal panels */}
      <div className="flex-1 relative">
        {sessions.map((session) => (
          <div
            key={session.id}
            className={clsx(
              "absolute inset-0",
              session.id === activeId ? "z-10 visible" : "z-0 invisible"
            )}
          >
            <TerminalComponent
              sessionId={session.id}
              workingDir={session.working_dir || projectPath}
              className="h-full"
            />
          </div>
        ))}
      </div>
    </div>
  );
}
