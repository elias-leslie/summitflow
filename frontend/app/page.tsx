"use client";

import { useQuery } from "@tanstack/react-query";
import { FolderKanban, Activity, AlertCircle, Plus } from "lucide-react";
import Link from "next/link";
import { fetchProjects } from "@/lib/api";
import { StatsGrid, ProjectCard, ActivityFeed } from "@/components/dashboard";

export default function DashboardPage() {
  return (
    <div className="p-6 space-y-8">
      {/* Header */}
      <header className="animate-in">
        <div className="flex items-center gap-3 mb-1">
          <span className="mono text-xs text-phosphor-500 uppercase tracking-widest">
            Dashboard
          </span>
          <div className="h-px flex-1 bg-gradient-to-r from-slate-700 to-transparent" />
        </div>
        <h1 className="display text-2xl font-semibold text-white">
          Mission Control
        </h1>
        <p className="text-slate-400 mt-1">
          Monitor your projects and development workflow
        </p>
      </header>

      {/* Stats Grid */}
      <section className="animate-fade-in" style={{ animationDelay: "0.05s" }}>
        <StatsGrid />
      </section>

      {/* Recent Projects Section */}
      <section className="animate-fade-in" style={{ animationDelay: "0.1s" }}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="display font-semibold text-lg text-white flex items-center gap-2">
            <FolderKanban className="w-5 h-5 text-phosphor-500" />
            Recent Projects
          </h2>
          <Link href="/projects/new" className="btn-primary text-sm flex items-center gap-2">
            <Plus className="w-4 h-4" />
            Add Project
          </Link>
        </div>
        <ProjectsGrid />
      </section>

      {/* Recent Activity Section */}
      <section className="animate-fade-in" style={{ animationDelay: "0.2s" }}>
        <h2 className="display font-semibold text-lg text-white flex items-center gap-2 mb-4">
          <Activity className="w-5 h-5 text-phosphor-500" />
          Recent Activity
        </h2>
        <ActivityFeed />
      </section>
    </div>
  );
}

function ProjectsGrid() {
  const { data: projects, isLoading, error } = useQuery({
    queryKey: ["projects"],
    queryFn: fetchProjects,
  });

  if (isLoading) {
    return (
      <div className="card p-8 text-center">
        <div className="inline-flex items-center gap-2 text-slate-400">
          <div className="w-4 h-4 border-2 border-phosphor-500/30 border-t-phosphor-500 rounded-full animate-spin" />
          Loading projects...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card p-8 text-center">
        <AlertCircle className="w-8 h-8 text-rose-500 mx-auto mb-2" />
        <p className="text-slate-400">Failed to load projects</p>
        <p className="text-xs text-rose-400 mono mt-1">{String(error)}</p>
      </div>
    );
  }

  if (!projects?.length) {
    return (
      <div className="card p-8 text-center border-dashed">
        <FolderKanban className="w-10 h-10 text-slate-600 mx-auto mb-3" />
        <p className="text-slate-400 mb-1">No projects registered</p>
        <p className="text-sm text-slate-500 mb-4">
          Add your first project to start tracking
        </p>
        <Link href="/projects/new" className="btn-primary inline-flex items-center gap-2">
          <Plus className="w-4 h-4" />
          Add Project
        </Link>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {projects.slice(0, 4).map((project) => (
        <ProjectCard key={project.id} project={project} />
      ))}
    </div>
  );
}
