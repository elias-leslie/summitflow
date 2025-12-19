"use client";

import { ReactNode } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";
import { useTerminalState } from "@/lib/hooks/use-terminal-state";
import { useIsMobile } from "@/lib/hooks/use-media-query";
import { TerminalTabs } from "@/components/terminal/TerminalTabs";

interface AppShellProps {
  children: ReactNode;
  /** Currently active project ID (from URL) */
  activeProjectId?: string;
}

/**
 * Application shell with resizable terminal panel.
 *
 * Desktop: Side-by-side panels with drag handle
 * Mobile: Full-screen overlay (handled in Phase 5)
 */
export function AppShell({ children, activeProjectId }: AppShellProps) {
  const { isOpen, width, setWidth, isInitialized } = useTerminalState();
  const isMobile = useIsMobile();

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

  // Mobile: overlay mode (Phase 5 will add full implementation)
  if (isMobile) {
    return (
      <div className="flex-1 overflow-auto">
        {children}
        {/* Mobile overlay will be added in Phase 5 */}
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
