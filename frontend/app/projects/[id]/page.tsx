"use client";

import { useState, useEffect } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, AlertCircle, Clock, Globe, ListChecks, Target, Camera, CircleDot, Compass } from "lucide-react";
import Link from "next/link";
import { fetchProject, fetchProjectHealth } from "@/lib/api";
import { FeaturesTab } from "@/components/features/FeaturesTab";
import { VisionGoalsTab } from "@/components/vision/VisionGoalsTab";
import { BeadsTab } from "@/components/beads/BeadsTab";
import { EvidenceTab } from "@/components/evidence/EvidenceTab";
import { ExplorerTab } from "@/components/explorer/ExplorerTab";

type TabId = "explorer" | "features" | "vision" | "evidence" | "beads";

export default function ProjectDetailPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const projectId = params.id as string;

  // Get initial tab from URL query param
  const urlTab = searchParams.get("tab") as TabId | null;
  const [activeTab, setActiveTab] = useState<TabId>(urlTab || "explorer");

  // Sync with URL changes
  useEffect(() => {
    if (urlTab && ["explorer", "features", "vision", "evidence", "beads"].includes(urlTab)) {
      setActiveTab(urlTab);
    }
  }, [urlTab]);

  const { data: project, isLoading, error } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => fetchProject(projectId),
  });

  const { data: health } = useQuery({
    queryKey: ["project-health", projectId],
    queryFn: () => fetchProjectHealth(projectId),
    refetchInterval: 30000,
  });

  if (isLoading) {
    return (
      <div className="p-6">
        <div className="flex items-center justify-center py-12">
          <div className="w-6 h-6 border-2 border-phosphor-500/30 border-t-phosphor-500 rounded-full animate-spin" />
        </div>
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="p-6">
        <div className="card p-8 text-center">
          <AlertCircle className="w-8 h-8 text-red-500 mx-auto mb-2" />
          <p className="text-slate-400">Failed to load project</p>
          <Link href="/" className="btn-secondary mt-4 inline-flex items-center gap-2">
            <ArrowLeft className="w-4 h-4" />
            Back to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <header className="animate-in">
        <Link
          href="/"
          className="text-xs text-slate-500 hover:text-phosphor-400 flex items-center gap-1 mb-3 transition-colors"
        >
          <ArrowLeft className="w-3 h-3" />
          Back to Dashboard
        </Link>

        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-xl bg-slate-800 flex items-center justify-center">
              <span className="display text-2xl font-bold text-phosphor-400">
                {project.name.charAt(0)}
              </span>
            </div>
            <div>
              <h1 className="display text-2xl font-semibold text-white">{project.name}</h1>
              <p className="mono text-sm text-slate-500">{project.id}</p>
            </div>
          </div>

          {/* Health status */}
          <div className="flex items-center gap-3">
            {health ? (
              <>
                <div
                  className={`status-dot ${health.healthy ? "healthy" : "error"}`}
                />
                <span className="text-sm text-slate-400">
                  {health.healthy ? "Healthy" : "Unhealthy"}
                </span>
                {health.response_time_ms && (
                  <span className="mono text-xs text-slate-500 tabular-nums">
                    {Math.round(health.response_time_ms)}ms
                  </span>
                )}
              </>
            ) : (
              <div className="status-dot unknown" />
            )}
          </div>
        </div>

        {/* Project info */}
        <div className="mt-4 flex items-center gap-6 text-sm text-slate-400">
          <span className="flex items-center gap-2">
            <Globe className="w-4 h-4" />
            <span className="mono">{project.base_url}</span>
          </span>
          <span className="flex items-center gap-2">
            <Clock className="w-4 h-4" />
            Created {new Date(project.created_at).toLocaleDateString()}
          </span>
        </div>
      </header>

      {/* Tab Navigation */}
      <nav className="border-b border-slate-700">
        <div className="flex gap-1">
          <button
            onClick={() => setActiveTab("explorer")}
            className={`px-4 py-2.5 text-sm font-medium transition-colors relative ${
              activeTab === "explorer"
                ? "text-phosphor-400"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            <div className="flex items-center gap-2">
              <Compass className="w-4 h-4" />
              Explorer
            </div>
            {activeTab === "explorer" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-phosphor-500" />
            )}
          </button>
          <button
            onClick={() => setActiveTab("features")}
            className={`px-4 py-2.5 text-sm font-medium transition-colors relative ${
              activeTab === "features"
                ? "text-phosphor-400"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            <div className="flex items-center gap-2">
              <ListChecks className="w-4 h-4" />
              Features
            </div>
            {activeTab === "features" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-phosphor-500" />
            )}
          </button>
          <button
            onClick={() => setActiveTab("vision")}
            className={`px-4 py-2.5 text-sm font-medium transition-colors relative ${
              activeTab === "vision"
                ? "text-phosphor-400"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            <div className="flex items-center gap-2">
              <Target className="w-4 h-4" />
              Vision
            </div>
            {activeTab === "vision" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-phosphor-500" />
            )}
          </button>
          <button
            onClick={() => setActiveTab("evidence")}
            className={`px-4 py-2.5 text-sm font-medium transition-colors relative ${
              activeTab === "evidence"
                ? "text-phosphor-400"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            <div className="flex items-center gap-2">
              <Camera className="w-4 h-4" />
              Evidence
            </div>
            {activeTab === "evidence" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-phosphor-500" />
            )}
          </button>
          <button
            onClick={() => setActiveTab("beads")}
            className={`px-4 py-2.5 text-sm font-medium transition-colors relative ${
              activeTab === "beads"
                ? "text-phosphor-400"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            <div className="flex items-center gap-2">
              <CircleDot className="w-4 h-4" />
              Beads
            </div>
            {activeTab === "beads" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-phosphor-500" />
            )}
          </button>
        </div>
      </nav>

      {/* Tab Content */}
      <section className="animate-fade-in">
        {activeTab === "explorer" && <ExplorerTab projectId={projectId} />}
        {activeTab === "features" && <FeaturesTab projectId={projectId} />}
        {activeTab === "vision" && <VisionGoalsTab projectId={projectId} />}
        {activeTab === "evidence" && <EvidenceTab projectId={projectId} />}
        {activeTab === "beads" && <BeadsTab projectId={projectId} />}
      </section>
    </div>
  );
}
