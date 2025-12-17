"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Activity, CheckCircle2, AlertCircle, Clock, Globe } from "lucide-react";
import Link from "next/link";
import { fetchProject, fetchProjectHealth } from "@/lib/api";
import { SitemapTab } from "@/components/sitemap/SitemapTab";

export default function ProjectDetailPage() {
  const params = useParams();
  const projectId = params.id as string;

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

      {/* Sitemap Section */}
      <section className="animate-fade-in" style={{ animationDelay: "0.1s" }}>
        <div className="flex items-center gap-2 mb-4">
          <Activity className="w-5 h-5 text-phosphor-500" />
          <h2 className="display font-semibold text-lg text-white">Sitemap</h2>
        </div>
        <SitemapTab projectId={projectId} />
      </section>
    </div>
  );
}
