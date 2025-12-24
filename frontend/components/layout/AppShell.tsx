"use client";

import { ReactNode, useMemo } from "react";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Group, Panel, Separator } from "react-resizable-panels";
import { Terminal } from "lucide-react";
import { useTerminalState } from "@/lib/hooks/use-terminal-state";
import { useIsMobile } from "@/lib/hooks/use-media-query";
import { TerminalTabs } from "@/components/terminal/TerminalTabs";
import { fetchProject } from "@/lib/api";

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
 * Application shell with resizable terminal panel at bottom.
 *
 * Desktop: Vertical panels with drag handle
 * Mobile: Full-screen overlay
 */
export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname();
  const { isOpen, height, setHeight, toggle, isInitialized } = useTerminalState();
  const isMobile = useIsMobile();

  // Extract project ID from URL for context-aware working directory
  const activeProjectId = useMemo(() => extractProjectId(pathname), [pathname]);

  // Fetch project to get root_path for terminal working directory
  const { data: project } = useQuery({
    queryKey: ["project", activeProjectId],
    queryFn: () => fetchProject(activeProjectId!),
    enabled: !!activeProjectId,
    staleTime: 5 * 60 * 1000, // Cache for 5 minutes
  });

  // Use project root_path, fallback to home directory
  const projectPath = project?.root_path ?? "/home/kasadis";

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
              projectPath={projectPath}
              className="flex-1"
            />
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

  // Desktop: terminal closed - full content area
  if (!isOpen) {
    return (
      <div className="flex-1 overflow-auto">
        {children}
      </div>
    );
  }

  // Desktop: vertical panels with terminal at bottom
  return (
    <Group
      orientation="vertical"
      className="flex-1"
    >
      {/* Main content panel */}
      <Panel
        id="main"
        defaultSize={100 - height}
        minSize="30%"
        className="overflow-auto"
      >
        <div className="h-full w-full overflow-auto">
          {children}
        </div>
      </Panel>

      {/* Resize handle */}
      <Separator className="h-1.5 bg-slate-800 hover:bg-phosphor-500/50 active:bg-phosphor-500 cursor-ns-resize transition-colors flex items-center justify-center group">
        <div className="w-12 h-1 rounded-full bg-slate-600 group-hover:bg-phosphor-400 transition-colors" />
      </Separator>

      {/* Terminal panel */}
      <Panel
        id="terminal"
        defaultSize={height}
        minSize="15%"
        maxSize="70%"
        className="bg-slate-900 flex flex-col overflow-hidden"
        onResize={(size) => {
          if (typeof size === 'number') {
            setHeight(size);
          }
        }}
      >
        <TerminalTabs
          projectId={activeProjectId}
          projectPath={projectPath}
          className="flex-1 min-h-0"
        />
      </Panel>
    </Group>
  );
}
