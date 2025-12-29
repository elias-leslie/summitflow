"use client";

import { ReactNode } from "react";

interface AppShellProps {
  children: ReactNode;
}

/**
 * Application shell - simple wrapper for main content.
 * Terminal is now a standalone app at terminal.summitflow.dev
 */
export function AppShell({ children }: AppShellProps) {
  return (
    <div className="flex-1 overflow-auto">
      {children}
    </div>
  );
}
