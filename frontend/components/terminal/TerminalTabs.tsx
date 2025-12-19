"use client";

import { useState, useCallback } from "react";
import { clsx } from "clsx";
import { TerminalComponent } from "./Terminal";
import { Plus, X, Terminal as TerminalIcon } from "lucide-react";

interface TerminalTab {
  id: string;
  label: string;
}

interface TerminalTabsProps {
  projectId?: string;
  projectPath?: string;
  className?: string;
}

function generateSessionId(): string {
  return `session-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

export function TerminalTabs({ projectId, projectPath, className }: TerminalTabsProps) {
  const [tabs, setTabs] = useState<TerminalTab[]>(() => {
    const initialId = generateSessionId();
    return [{ id: initialId, label: "Terminal 1" }];
  });
  const [activeTabId, setActiveTabId] = useState<string>(tabs[0].id);

  const addTab = useCallback(() => {
    const newId = generateSessionId();
    const newLabel = `Terminal ${tabs.length + 1}`;
    setTabs((prev) => [...prev, { id: newId, label: newLabel }]);
    setActiveTabId(newId);
  }, [tabs.length]);

  const closeTab = useCallback(
    (tabId: string, e: React.MouseEvent) => {
      e.stopPropagation();

      // Don't close the last tab
      if (tabs.length <= 1) return;

      const tabIndex = tabs.findIndex((t) => t.id === tabId);
      const newTabs = tabs.filter((t) => t.id !== tabId);
      setTabs(newTabs);

      // If closing the active tab, switch to an adjacent one
      if (tabId === activeTabId) {
        const newActiveIndex = Math.min(tabIndex, newTabs.length - 1);
        setActiveTabId(newTabs[newActiveIndex].id);
      }
    },
    [tabs, activeTabId]
  );

  const handleTabDisconnect = useCallback((tabId: string) => {
    // Update tab label to show disconnected state
    setTabs((prev) =>
      prev.map((t) =>
        t.id === tabId
          ? { ...t, label: t.label.replace(/( \(disconnected\))?$/, " (disconnected)") }
          : t
      )
    );
  }, []);

  return (
    <div className={clsx("flex flex-col h-full", className)}>
      {/* Tab bar */}
      <div className="flex items-center gap-1 px-2 py-1 bg-slate-800 border-b border-slate-700 overflow-x-auto">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTabId(tab.id)}
            className={clsx(
              "flex items-center gap-2 px-3 py-1.5 text-sm rounded-t-md transition-colors",
              "group min-w-0 flex-shrink-0",
              tab.id === activeTabId
                ? "bg-slate-900 text-white border-t border-l border-r border-slate-700"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-700/50"
            )}
          >
            <TerminalIcon className="w-3.5 h-3.5 flex-shrink-0" />
            <span className="truncate max-w-[120px]">{tab.label}</span>
            {tabs.length > 1 && (
              <button
                onClick={(e) => closeTab(tab.id, e)}
                className={clsx(
                  "p-0.5 rounded hover:bg-slate-600 opacity-0 group-hover:opacity-100 transition-opacity",
                  tab.id === activeTabId && "opacity-100"
                )}
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </button>
        ))}

        {/* Add new terminal button */}
        <button
          onClick={addTab}
          className="flex items-center gap-1 px-2 py-1.5 text-sm text-slate-400 hover:text-white hover:bg-slate-700/50 rounded transition-colors"
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>

      {/* Terminal panels */}
      <div className="flex-1 relative">
        {tabs.map((tab) => (
          <div
            key={tab.id}
            className={clsx(
              "absolute inset-0",
              tab.id === activeTabId ? "z-10 visible" : "z-0 invisible"
            )}
          >
            <TerminalComponent
              sessionId={projectId ? `${projectId}-${tab.id}` : tab.id}
              workingDir={projectPath}
              className="h-full"
              onDisconnect={() => handleTabDisconnect(tab.id)}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
