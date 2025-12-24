"use client";

import { useCallback, useState, useRef, useEffect } from "react";
import { clsx } from "clsx";
import { Group, Panel, Separator } from "react-resizable-panels";
import { TerminalComponent, TerminalHandle, ConnectionStatus } from "./Terminal";
import { Plus, X, Terminal as TerminalIcon, Loader2, Square, Rows2, Columns2, Minus, Settings2, RefreshCw } from "lucide-react";
import { useTerminalSessions } from "@/lib/hooks/use-terminal-sessions";
import { useTerminalState, LayoutMode } from "@/lib/hooks/use-terminal-state";
import { useTerminalSettings, TERMINAL_FONTS, TERMINAL_FONT_SIZES, TerminalFontId, TerminalFontSize } from "@/lib/hooks/use-terminal-settings";
import { useMediaQuery } from "@/lib/hooks/use-media-query";
import { MobileKeyboard, useMobileKeyboardMode } from "./keyboard/MobileKeyboard";
import { KeyboardMode } from "./keyboard/types";

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

  const { layoutMode, setLayoutMode, setOpen } = useTerminalState();
  const { fontId, fontSize, fontFamily, setFontId, setFontSize } = useTerminalSettings();
  const isMobile = useMediaQuery("(max-width: 767px)");
  const [showSettings, setShowSettings] = useState(false);
  const [keyboardMode, setKeyboardMode] = useState<KeyboardMode>("native");

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
      // If closing the last session, close the terminal panel
      if (sessions.length <= 1) {
        setOpen(false);
      }
    },
    [sessions.length, remove, setOpen]
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
      {/* Tab bar */}
      <div className="flex-shrink-0 flex items-center gap-1 px-2 py-1 bg-slate-800 border-b border-slate-700 overflow-x-auto overflow-y-visible">
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

        {/* Reconnect button - visible when disconnected */}
        {showReconnect && (
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
            <button
              onClick={() => handleLayoutModeChange("single")}
              title="Single pane"
              className={clsx(
                "p-1.5 rounded transition-colors",
                layoutMode === "single"
                  ? "bg-slate-700 text-phosphor-400"
                  : "text-slate-500 hover:text-slate-300 hover:bg-slate-700/50"
              )}
            >
              <Square className="w-4 h-4" />
            </button>
            <button
              onClick={() => handleLayoutModeChange("horizontal")}
              title="Horizontal split"
              className={clsx(
                "p-1.5 rounded transition-colors",
                layoutMode === "horizontal"
                  ? "bg-slate-700 text-phosphor-400"
                  : "text-slate-500 hover:text-slate-300 hover:bg-slate-700/50"
              )}
            >
              <Rows2 className="w-4 h-4" />
            </button>
            <button
              onClick={() => handleLayoutModeChange("vertical")}
              title="Vertical split"
              className={clsx(
                "p-1.5 rounded transition-colors",
                layoutMode === "vertical"
                  ? "bg-slate-700 text-phosphor-400"
                  : "text-slate-500 hover:text-slate-300 hover:bg-slate-700/50"
              )}
            >
              <Columns2 className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Settings button */}
        <SettingsDropdown
          fontId={fontId}
          fontSize={fontSize}
          setFontId={setFontId}
          setFontSize={setFontSize}
          showSettings={showSettings}
          setShowSettings={setShowSettings}
        />

        {/* Close terminal button */}
        <button
          onClick={() => setOpen(false)}
          title="Close terminal"
          className="ml-2 p-1.5 text-slate-400 hover:text-white hover:bg-slate-700/50 rounded transition-colors"
        >
          <Minus className="w-4 h-4" />
        </button>
      </div>

      {/* Terminal panels - use min-h-0 to allow flex-1 to shrink below content size */}
      <div className="flex-1 min-h-0 relative overflow-hidden">
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
                suppressNativeKeyboard={isMobile && keyboardMode === "custom"}
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
                suppressNativeKeyboard={isMobile && keyboardMode === "custom"}
              />
            ))}
          </Group>
        )}
      </div>

      {/* Mobile keyboard - only on mobile */}
      {isMobile && sessions.length > 0 && (
        <MobileKeyboard onSend={handleKeyboardInput} onModeChange={setKeyboardMode} />
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
  suppressNativeKeyboard?: boolean;
}

function SplitPane({ session, projectPath, layoutMode, isLast, paneCount, fontFamily, fontSize, onTerminalRef, onStatusChange, suppressNativeKeyboard }: SplitPaneProps) {
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
            suppressNativeKeyboard={suppressNativeKeyboard}
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

// Settings dropdown component with fixed positioning to escape overflow containers
interface SettingsDropdownProps {
  fontId: TerminalFontId;
  fontSize: TerminalFontSize;
  setFontId: (id: TerminalFontId) => void;
  setFontSize: (size: TerminalFontSize) => void;
  showSettings: boolean;
  setShowSettings: (show: boolean) => void;
}

function SettingsDropdown({
  fontId,
  fontSize,
  setFontId,
  setFontSize,
  showSettings,
  setShowSettings,
}: SettingsDropdownProps) {
  const buttonRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!showSettings) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (
        buttonRef.current &&
        !buttonRef.current.contains(e.target as Node) &&
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setShowSettings(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showSettings, setShowSettings]);

  // Calculate dropdown position
  const getDropdownStyle = (): React.CSSProperties => {
    if (!buttonRef.current) return {};
    const rect = buttonRef.current.getBoundingClientRect();
    return {
      position: "fixed",
      right: window.innerWidth - rect.right,
      bottom: window.innerHeight - rect.top + 4,
      zIndex: 9999,
    };
  };

  return (
    <div className="relative ml-2">
      <button
        ref={buttonRef}
        onClick={() => setShowSettings(!showSettings)}
        title="Terminal settings"
        className={clsx(
          "p-1.5 rounded transition-colors",
          showSettings
            ? "bg-slate-700 text-phosphor-400"
            : "text-slate-400 hover:text-white hover:bg-slate-700/50"
        )}
      >
        <Settings2 className="w-4 h-4" />
      </button>

      {/* Settings dropdown - fixed position to escape overflow */}
      {showSettings && (
        <div
          ref={dropdownRef}
          style={getDropdownStyle()}
          className="bg-slate-800 border border-slate-700 rounded-lg shadow-xl p-3 min-w-[200px]"
        >
          {/* Font family */}
          <div className="mb-3">
            <label className="block text-xs text-slate-400 mb-1">Font</label>
            <select
              value={fontId}
              onChange={(e) => setFontId(e.target.value as TerminalFontId)}
              className="w-full px-2 py-1.5 text-sm bg-slate-900 border border-slate-700 rounded text-slate-200 focus:outline-none focus:border-phosphor-500"
            >
              {TERMINAL_FONTS.map((font) => (
                <option key={font.id} value={font.id}>
                  {font.name}
                </option>
              ))}
            </select>
          </div>

          {/* Font size */}
          <div>
            <label className="block text-xs text-slate-400 mb-1">Size</label>
            <select
              value={fontSize}
              onChange={(e) => setFontSize(Number(e.target.value) as TerminalFontSize)}
              className="w-full px-2 py-1.5 text-sm bg-slate-900 border border-slate-700 rounded text-slate-200 focus:outline-none focus:border-phosphor-500"
            >
              {TERMINAL_FONT_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}px
                </option>
              ))}
            </select>
          </div>
        </div>
      )}
    </div>
  );
}
