"use client";

import { useCallback, useState, useRef, useEffect } from "react";
import { clsx } from "clsx";
import { Group, Panel, Separator } from "react-resizable-panels";
import { TerminalComponent, TerminalHandle, ConnectionStatus } from "./Terminal";
import { Plus, X, Terminal as TerminalIcon, Loader2, RefreshCw } from "lucide-react";
import { LayoutModeButtons, LayoutMode } from "./LayoutModeButton";
import { useTerminalSessions } from "@/lib/hooks/use-terminal-sessions";
import { useTerminalSettings } from "@/lib/hooks/use-terminal-settings";
import { useMediaQuery } from "@/lib/hooks/use-media-query";
import { MobileKeyboard } from "./keyboard/MobileKeyboard";
import { SettingsDropdown, KeyboardSizePreset } from "./SettingsDropdown";

// Maximum number of split panes
const MAX_SPLIT_PANES = 4;

// Helper to get next terminal name (Terminal 1, Terminal 2, etc.)
function getNextTerminalName(sessions: Array<{ name: string }>): string {
  // Find the highest "Terminal N" number
  let maxNum = 0;
  for (const session of sessions) {
    const match = session.name.match(/^Terminal\s+(\d+)$/i);
    if (match) {
      maxNum = Math.max(maxNum, parseInt(match[1], 10));
    }
  }
  return `Terminal ${maxNum + 1}`;
}

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

  // Standalone app uses local state for layout (no embedded panel)
  const [layoutMode, setLayoutMode] = useState<LayoutMode>("single");
  const { fontId, fontSize, fontFamily, setFontId, setFontSize } = useTerminalSettings();
  const isMobile = useMediaQuery("(max-width: 767px)");
  const [showSettings, setShowSettings] = useState(false);
  const [keyboardSize, setKeyboardSize] = useState<KeyboardSizePreset>("medium");

  // Load keyboard size from localStorage
  useEffect(() => {
    const stored = localStorage.getItem("terminal-keyboard-size");
    if (stored === "small" || stored === "medium" || stored === "large") {
      setKeyboardSize(stored);
    }
  }, []);

  // Save keyboard size to localStorage
  const handleKeyboardSizeChange = useCallback((size: KeyboardSizePreset) => {
    setKeyboardSize(size);
    localStorage.setItem("terminal-keyboard-size", size);
  }, []);

  // Terminal refs and connection status tracking
  const terminalRefs = useRef<Map<string, TerminalHandle>>(new Map());
  const [terminalStatuses, setTerminalStatuses] = useState<Map<string, ConnectionStatus>>(new Map());

  // Get active terminal status for showing reconnect button
  const activeStatus = activeId ? terminalStatuses.get(activeId) : undefined;
  const showReconnect = activeStatus && ["disconnected", "error", "timeout"].includes(activeStatus);

  // Handle reconnect for active terminal
  const handleReconnect = useCallback(() => {
    if (activeId) {
      const terminalRef = terminalRefs.current.get(activeId);
      terminalRef?.reconnect();
    }
  }, [activeId]);

  // Handle status change from terminal
  const handleStatusChange = useCallback((sessionId: string, status: ConnectionStatus) => {
    setTerminalStatuses((prev) => {
      const next = new Map(prev);
      next.set(sessionId, status);
      return next;
    });
  }, []);

  // Handle input from keyboard bar
  const handleKeyboardInput = useCallback((data: string) => {
    if (activeId) {
      const terminalRef = terminalRefs.current.get(activeId);
      terminalRef?.sendInput(data);
    }
  }, [activeId]);

  // Number of panes to show in split mode (1:1 with sessions, capped)
  const splitPaneCount = Math.min(sessions.length, MAX_SPLIT_PANES);

  // Handle layout mode change - create session if needed for split
  const handleLayoutModeChange = useCallback(async (mode: LayoutMode) => {
    if (mode !== "single" && sessions.length === 1) {
      // Create a second terminal before switching to split
      const name = getNextTerminalName(sessions);
      await create(name, projectPath);
    }
    setLayoutMode(mode);
  }, [sessions, create, projectPath, setLayoutMode]);

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
    const name = getNextTerminalName(sessions);
    await create(name, projectPath);
  }, [sessions, create, projectPath]);

  // Close terminal session
  const handleCloseTab = useCallback(
    async (sessionId: string, e: React.MouseEvent) => {
      e.stopPropagation();
      await remove(sessionId);
      // Standalone app: no panel to close, session removal is enough
    },
    [remove]
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

  return (
    <div className={clsx("flex flex-col h-full min-h-0 overflow-visible", className)}>
      {/* Tab bar - order-2 on mobile (below terminal), order-1 on desktop (above terminal) */}
      <div className={clsx(
        "flex-shrink-0 flex items-center gap-1 px-2 py-1 bg-slate-800 overflow-x-auto overflow-y-visible",
        isMobile ? "order-2 border-t border-slate-700" : "order-1 border-b border-slate-700"
      )}>
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
            <button
              onClick={(e) => handleCloseTab(session.id, e)}
              className={clsx(
                "p-0.5 rounded hover:bg-slate-600 opacity-0 group-hover:opacity-100 transition-opacity",
                session.id === activeId && "opacity-100"
              )}
              title="Close terminal"
            >
              <X className="w-3 h-3" />
            </button>
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

        {/* Reconnect button - visible when disconnected, hidden on mobile (in control bar) */}
        {showReconnect && !isMobile && (
          <button
            onClick={handleReconnect}
            className="flex items-center gap-1 px-2 py-1.5 text-sm text-amber-400 hover:text-amber-300 hover:bg-slate-700/50 rounded transition-colors"
            title="Reconnect terminal"
          >
            <RefreshCw className="w-4 h-4" />
            <span className="hidden sm:inline">Reconnect</span>
          </button>
        )}


        {/* Layout mode buttons - hidden on mobile */}
        {!isMobile && (
          <div className="ml-auto flex items-center gap-0.5 border-l border-slate-700 pl-2">
            <LayoutModeButtons layoutMode={layoutMode} onLayoutChange={handleLayoutModeChange} />
          </div>
        )}

        {/* Settings button - always visible, pushed to right on mobile */}
        <div className={clsx("flex items-center gap-1", isMobile && "ml-auto")}>
          {/* Connection status / reconnect - show on mobile */}
          {isMobile && (
            <button
              onClick={handleReconnect}
              disabled={!showReconnect}
              className={clsx(
                "p-1.5 rounded transition-colors",
                showReconnect
                  ? "text-amber-400 hover:text-amber-300 hover:bg-slate-700/50"
                  : activeStatus === "connected"
                    ? "text-green-400 cursor-default"
                    : activeStatus === "connecting"
                      ? "text-yellow-400 animate-pulse cursor-default"
                      : "text-slate-500 cursor-default"
              )}
              title={showReconnect ? "Reconnect" : `Status: ${activeStatus || "unknown"}`}
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          )}
          <SettingsDropdown
            fontId={fontId}
            fontSize={fontSize}
            setFontId={setFontId}
            setFontSize={setFontSize}
            showSettings={showSettings}
            setShowSettings={setShowSettings}
            keyboardSize={keyboardSize}
            setKeyboardSize={handleKeyboardSizeChange}
            isMobile={isMobile}
          />

          {/* Standalone app: no minimize button (full-page terminal) */}
        </div>
      </div>

      {/* Terminal panels - use min-h-0 to allow flex-1 to shrink below content size */}
      {/* order-1 on mobile (above tabs), order-2 on desktop (below tabs) */}
      <div className={clsx(
        "flex-1 min-h-0 relative overflow-hidden",
        isMobile ? "order-1" : "order-2"
      )}>
        {sessions.length === 0 ? (
          // Empty state - just show hint text
          <div className="flex items-center justify-center h-full text-slate-500 text-sm">
            Click <Plus className="w-4 h-4 mx-1 inline" /> to start a terminal
          </div>
        ) : layoutMode === "single" ? (
          // Single pane - show active session
          sessions.map((session) => (
            <div
              key={session.id}
              className={clsx(
                "absolute inset-0 overflow-hidden",
                session.id === activeId ? "z-10 visible" : "z-0 invisible"
              )}
            >
              <TerminalComponent
                ref={(handle) => {
                  if (handle) {
                    terminalRefs.current.set(session.id, handle);
                  } else {
                    terminalRefs.current.delete(session.id);
                  }
                }}
                sessionId={session.id}
                workingDir={session.working_dir || projectPath}
                className="h-full"
                fontFamily={fontFamily}
                fontSize={fontSize}
                onStatusChange={(status) => handleStatusChange(session.id, status)}
              />
            </div>
          ))
        ) : (
          // Split pane layout - 1:1 mapping with sessions
          <Group
            orientation={layoutMode === "horizontal" ? "vertical" : "horizontal"}
            className="h-full"
          >
            {sessions.slice(0, splitPaneCount).map((session, index) => (
              <SplitPane
                key={session.id}
                session={session}
                projectPath={projectPath}
                layoutMode={layoutMode}
                isLast={index === splitPaneCount - 1}
                paneCount={splitPaneCount}
                fontFamily={fontFamily}
                fontSize={fontSize}
                onTerminalRef={(handle) => {
                  if (handle) {
                    terminalRefs.current.set(session.id, handle);
                  } else {
                    terminalRefs.current.delete(session.id);
                  }
                }}
                onStatusChange={(status) => handleStatusChange(session.id, status)}
              />
            ))}
          </Group>
        )}
      </div>

      {/* Mobile keyboard - only on mobile, order-3 (at bottom) */}
      {isMobile && sessions.length > 0 && (
        <div className="order-3">
          <MobileKeyboard
            onSend={handleKeyboardInput}
            connectionStatus={activeStatus}
            onReconnect={handleReconnect}
            keyboardSize={keyboardSize}
          />
        </div>
      )}
    </div>
  );
}

// Split pane component for cleaner rendering
interface SplitPaneProps {
  session: { id: string; name: string; working_dir: string | null; is_alive: boolean };
  projectPath?: string;
  layoutMode: LayoutMode;
  isLast: boolean;
  paneCount: number;
  fontFamily: string;
  fontSize: number;
  onTerminalRef?: (handle: TerminalHandle | null) => void;
  onStatusChange?: (status: ConnectionStatus) => void;
}

function SplitPane({ session, projectPath, layoutMode, isLast, paneCount, fontFamily, fontSize, onTerminalRef, onStatusChange }: SplitPaneProps) {
  const defaultSize = 100 / paneCount;
  const minSize = `${Math.max(10, 100 / (paneCount * 2))}%`; // String percentage for proper sizing

  return (
    <>
      <Panel
        id={session.id}
        defaultSize={defaultSize}
        minSize={minSize}
        className="flex flex-col h-full min-h-0 overflow-hidden"
      >
        {/* Small header showing terminal name */}
        <div className="flex-shrink-0 flex items-center px-2 py-0.5 bg-slate-800/50 border-b border-slate-700">
          <TerminalIcon className="w-3 h-3 text-slate-500 mr-1.5" />
          <span className="text-xs text-slate-400 truncate">{session.name}</span>
          {!session.is_alive && <span className="text-xs text-red-400 ml-1">(dead)</span>}
        </div>
        <div className="flex-1 min-h-0 overflow-hidden">
          <TerminalComponent
            ref={onTerminalRef}
            sessionId={session.id}
            workingDir={session.working_dir || projectPath}
            className="h-full"
            fontFamily={fontFamily}
            fontSize={fontSize}
            onStatusChange={onStatusChange}
          />
        </div>
      </Panel>
      {!isLast && (
        <Separator
          className={clsx(
            layoutMode === "horizontal"
              ? "h-1 cursor-row-resize"
              : "w-1 cursor-col-resize",
            "bg-slate-700 hover:bg-slate-600 active:bg-phosphor-500 transition-colors"
          )}
        />
      )}
    </>
  );
}
