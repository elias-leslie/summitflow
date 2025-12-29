"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { TerminalTabs } from "@/components/TerminalTabs";

function TerminalPage() {
  const searchParams = useSearchParams();
  const projectId = searchParams.get("project") || undefined;
  const projectPath = searchParams.get("dir") || undefined;

  return (
    <div className="h-screen flex flex-col bg-slate-900">
      <TerminalTabs
        projectId={projectId}
        projectPath={projectPath}
        className="flex-1 min-h-0"
      />
    </div>
  );
}

// Wrap in Suspense for useSearchParams
export default function Home() {
  return (
    <Suspense
      fallback={
        <div className="h-screen flex items-center justify-center bg-slate-900 text-slate-400">
          Loading terminal...
        </div>
      }
    >
      <TerminalPage />
    </Suspense>
  );
}
