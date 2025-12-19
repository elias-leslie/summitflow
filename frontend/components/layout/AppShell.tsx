"use client";

import { ReactNode, useMemo } from "react";
import { usePathname } from "next/navigation";
import { Group, Panel, Separator } from "react-resizable-panels";
import { Terminal, ChevronDown } from "lucide-react";
import { useTerminalState } from "@/lib/hooks/use-terminal-state";
import { useIsMobile } from "@/lib/hooks/use-media-query";
import { TerminalTabs } from "@/components/terminal/TerminalTabs";

interface AppShellProps {
  children: ReactNode;
}

/**
 * Extract project ID from URL path.
 * Matches /projects/[id] and /projects/[id]/*
 */
function extractProjectId(pathname: string | null): string | undefined {
  if (!pathname) return undefined;
  const match = pathname.match(/^\/projects\/([^/]+)/);
  return match?.[1];
}

/**
 * Application shell with resizable terminal panel.
 *
 * Desktop: Side-by-side panels with drag handle
 * Mobile: Full-screen overlay (handled in Phase 5)
 */
export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname();
  const { isOpen, width, setWidth, toggle, isInitialized } = useTerminalState();
  const isMobile = useIsMobile();

  // Extract project ID from URL for context-aware working directory
  const activeProjectId = useMemo(() => extractProjectId(pathname), [pathname]);

  // Convert width percentage to min size in percentage
  // Minimum 300px, but we need percentage for PanelGroup
  // Assuming typical screen width of 1920px, 300px ≈ 15.6%
  // We'll use a fixed minSize of 15 and maxSize of 70
  const MIN_SIZE = 15;
  const MAX_SIZE = 70;

  // Don't render terminal panel until state is initialized from localStorage
  // This prevents flash of default state
  if (!isInitialized) {
    return (
      <div className="flex-1 overflow-auto">
        {children}
      </div>
    );
  }

  // Mobile: full-screen overlay mode
  if (isMobile) {
    return (
      <div className="flex-1 overflow-auto relative">
        {children}

        {/* Full-screen terminal overlay when open */}
        {isOpen && (
          <div className="fixed inset-0 z-50 bg-slate-900 flex flex-col">
            {/* Terminal content */}
            <TerminalTabs
              projectId={activeProjectId}
              className="flex-1"
            />

            {/* Minimize pill button at bottom */}
            <div className="flex justify-center pb-4 pt-2">
              <button
                onClick={toggle}
                className="flex items-center gap-1 px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded-full text-sm text-slate-300 transition-colors"
              >
                <ChevronDown className="w-4 h-4" />
                <span>Minimize</span>
              </button>
            </div>
          </div>
        )}

        {/* Floating terminal FAB when closed */}
        {!isOpen && (
          <button
            onClick={toggle}
            className="fixed bottom-4 right-4 z-40 p-3 bg-phosphor-500 hover:bg-phosphor-400 rounded-full shadow-lg transition-colors"
            aria-label="Open Terminal"
          >
            <Terminal className="w-5 h-5 text-slate-900" />
          </button>
        )}
      </div>
    );
  }

  // Desktop: side-by-side resizable panels
  if (!isOpen) {
    return (
      <div className="flex-1 overflow-auto">
        {children}
      </div>
    );
  }

  // Handle resize - extract percentage from PanelSize
  const handleResize = (panelSize: { asPercentage: number; inPixels: number }) => {
    setWidth(panelSize.asPercentage);
  };

  return (
    <Group orientation="horizontal" className="flex-1">
      {/* Main content panel */}
      <Panel
        defaultSize={100 - width}
        minSize={100 - MAX_SIZE}
        className="overflow-auto"
      >
        {children}
      </Panel>

      {/* Resize handle */}
      <Separator className="w-1 bg-slate-700 hover:bg-slate-600 active:bg-phosphor-500 cursor-col-resize transition-colors" />

      {/* Terminal panel */}
      <Panel
        defaultSize={width}
        minSize={MIN_SIZE}
        maxSize={MAX_SIZE}
        onResize={handleResize}
        className="bg-slate-900 flex flex-col"
      >
        <TerminalTabs
          projectId={activeProjectId}
          className="flex-1"
        />
      </Panel>
    </Group>
  );
}
