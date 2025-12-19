"use client";

import { useCallback, useState, useRef, useEffect } from "react";
import { clsx } from "clsx";
import { Group, Panel, Separator } from "react-resizable-panels";
import { TerminalComponent } from "./Terminal";
import { Plus, X, Terminal as TerminalIcon, Loader2, Square, Rows2, Columns2, ChevronDown } from "lucide-react";
import { useTerminalSessions } from "@/lib/hooks/use-terminal-sessions";
import { useTerminalState, LayoutMode } from "@/lib/hooks/use-terminal-state";
import { useMediaQuery } from "@/lib/hooks/use-media-query";

interface TerminalTabsProps {
  projectId?: string;
  projectPath?: string;
  className?: string;
}

interface LayoutModeButtonProps {
  mode: LayoutMode;
  currentMode: LayoutMode;
  onClick: (mode: LayoutMode) => void;
  icon: React.ComponentType<{ className?: string }>;
  title: string;
}

function LayoutModeButton({ mode, currentMode, onClick, icon: Icon, title }: LayoutModeButtonProps) {
  const isActive = currentMode === mode;
  return (
    <button
      onClick={() => onClick(mode)}
      title={title}
      className={clsx(
        "p-1.5 rounded transition-colors",
        isActive
          ? "bg-slate-700 text-phosphor-400"
          : "text-slate-500 hover:text-slate-300 hover:bg-slate-700/50"
      )}
    >
      <Icon className="w-4 h-4" />
    </button>
  );
}

interface SessionSelectorProps {
  sessions: Array<{ id: string; name: string; is_alive: boolean }>;
  selectedId: string | undefined;
  onSelect: (id: string) => void;
  paneIndex: number;
}

function SessionSelector({ sessions, selectedId, onSelect, paneIndex }: SessionSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const selectedSession = sessions.find((s) => s.id === selectedId);

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-1 px-2 py-1 text-xs bg-slate-800 border border-slate-700 rounded hover:bg-slate-700 text-slate-300"
      >
        <TerminalIcon className="w-3 h-3" />
        <span className="truncate max-w-[100px]">
          {selectedSession?.name || `Pane ${paneIndex + 1}`}
        </span>
        <ChevronDown className="w-3 h-3" />
      </button>
      {isOpen && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setIsOpen(false)} />
          <div className="absolute top-full left-0 mt-1 bg-slate-800 border border-slate-700 rounded shadow-lg z-20 min-w-[150px]">
            {sessions.map((session) => (
              <button
                key={session.id}
                onClick={() => {
                  onSelect(session.id);
                  setIsOpen(false);
                }}
                className={clsx(
                  "w-full text-left px-3 py-1.5 text-xs hover:bg-slate-700 flex items-center gap-2",
                  session.id === selectedId && "bg-slate-700 text-phosphor-400"
                )}
              >
                <TerminalIcon className="w-3 h-3" />
                <span className="truncate">{session.name}</span>
                {!session.is_alive && <span className="text-red-400">(dead)</span>}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
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

  const { layoutMode, setLayoutMode, paneSizes, setPaneSizes, paneSessions, setPaneSessions } = useTerminalState();
  const isMobile = useMediaQuery("(max-width: 767px)");

  // Get session IDs for each pane (default to first sessions if not set)
  const getPaneSession = useCallback((paneIndex: number): string | undefined => {
    if (paneSessions[paneIndex]) {
      // Verify the session still exists
      const exists = sessions.some((s) => s.id === paneSessions[paneIndex]);
      if (exists) return paneSessions[paneIndex];
    }
    // Fall back to session by index
    return sessions[paneIndex]?.id;
  }, [paneSessions, sessions]);

  // Update a specific pane's session
  const setPaneSession = useCallback((paneIndex: number, sessionId: string) => {
    const newPaneSessions = [...paneSessions];
    newPaneSessions[paneIndex] = sessionId;
    setPaneSessions(newPaneSessions);
  }, [paneSessions, setPaneSessions]);

  // Handle pane resize
  const handlePane0Resize = useCallback((size: { asPercentage: number }) => {
    const newSizes = [size.asPercentage, 100 - size.asPercentage];
    setPaneSizes(newSizes);
  }, [setPaneSizes]);

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

        {/* Layout mode buttons - hidden on mobile */}
        {!isMobile && (
          <div className="ml-auto flex items-center gap-0.5 border-l border-slate-700 pl-2">
            <LayoutModeButton
              mode="single"
              currentMode={layoutMode}
              onClick={setLayoutMode}
              icon={Square}
              title="Single pane"
            />
            <LayoutModeButton
              mode="horizontal"
              currentMode={layoutMode}
              onClick={setLayoutMode}
              icon={Rows2}
              title="Horizontal split"
            />
            <LayoutModeButton
              mode="vertical"
              currentMode={layoutMode}
              onClick={setLayoutMode}
              icon={Columns2}
              title="Vertical split"
            />
          </div>
        )}
      </div>

      {/* Terminal panels */}
      <div className="flex-1 relative">
        {layoutMode === "single" ? (
          // Single pane - show active session
          sessions.map((session) => (
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
          ))
        ) : (
          // Split pane layout
          <Group
            orientation={layoutMode === "horizontal" ? "vertical" : "horizontal"}
            className="h-full"
          >
            {/* First pane */}
            <Panel
              defaultSize={paneSizes[0] ?? 50}
              minSize={20}
              onResize={handlePane0Resize}
              className="flex flex-col"
            >
              <div className="flex items-center px-2 py-1 bg-slate-800/50 border-b border-slate-700">
                <SessionSelector
                  sessions={sessions}
                  selectedId={getPaneSession(0)}
                  onSelect={(id) => setPaneSession(0, id)}
                  paneIndex={0}
                />
              </div>
              <div className="flex-1 relative">
                {sessions.map((session) => {
                  const isActive = session.id === getPaneSession(0);
                  return (
                    <div
                      key={session.id}
                      className={clsx(
                        "absolute inset-0",
                        isActive ? "z-10 visible" : "z-0 invisible"
                      )}
                    >
                      <TerminalComponent
                        sessionId={session.id}
                        workingDir={session.working_dir || projectPath}
                        className="h-full"
                      />
                    </div>
                  );
                })}
              </div>
            </Panel>

            {/* Resize handle */}
            <Separator
              className={clsx(
                layoutMode === "horizontal"
                  ? "h-1 cursor-row-resize"
                  : "w-1 cursor-col-resize",
                "bg-slate-700 hover:bg-slate-600 active:bg-phosphor-500 transition-colors"
              )}
            />

            {/* Second pane */}
            <Panel
              defaultSize={paneSizes[1] ?? 50}
              minSize={20}
              className="flex flex-col"
            >
              <div className="flex items-center px-2 py-1 bg-slate-800/50 border-b border-slate-700">
                <SessionSelector
                  sessions={sessions}
                  selectedId={getPaneSession(1)}
                  onSelect={(id) => setPaneSession(1, id)}
                  paneIndex={1}
                />
              </div>
              <div className="flex-1 relative">
                {sessions.map((session) => {
                  const isActive = session.id === getPaneSession(1);
                  return (
                    <div
                      key={session.id}
                      className={clsx(
                        "absolute inset-0",
                        isActive ? "z-10 visible" : "z-0 invisible"
                      )}
                    >
                      <TerminalComponent
                        sessionId={session.id}
                        workingDir={session.working_dir || projectPath}
                        className="h-full"
                      />
                    </div>
                  );
                })}
              </div>
            </Panel>
          </Group>
        )}
      </div>
    </div>
  );
}
