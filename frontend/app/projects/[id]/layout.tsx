"use client";

import { Suspense, ReactNode } from "react";
import { useParams } from "next/navigation";
import { SecondaryNav } from "@/components/layout/SecondaryNav";

interface ProjectLayoutProps {
  children: ReactNode;
}

export default function ProjectLayout({ children }: ProjectLayoutProps) {
  const params = useParams();
  const projectId = params.id as string;

  return (
    <div className="flex h-[calc(100vh-6rem)]">
      <Suspense
        fallback={
          <div className="w-16 h-full bg-slate-900/50 border-r border-slate-700/50" />
        }
      >
        <SecondaryNav projectId={projectId} />
      </Suspense>
      <div className="flex-1 overflow-hidden">{children}</div>
    </div>
  );
}
