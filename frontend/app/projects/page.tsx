"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { FolderKanban, Plus, Clock, Target, ListTodo } from "lucide-react";
import { fetchProjects, type Project } from "@/lib/api";
import clsx from "clsx";

export default function ProjectsPage() {
  const { data: projects, isLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: fetchProjects,
  });

  // Calculate stats
  const totalProjects = projects?.length ?? 0;
  const healthyProjects = projects?.filter(p => p.health_status === "healthy").length ?? 0;

  return (
    <div className="p-6 space-y-8">
      {/* Header */}
      <header>
        <div className="flex items-center gap-3 mb-1">
          <span className="mono text-xs text-phosphor-500 uppercase tracking-widest">Projects</span>
          <div className="h-px flex-1 bg-gradient-to-r from-slate-700 to-transparent" />
        </div>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="display text-2xl font-semibold text-white">Registered Projects</h1>
            <p className="text-slate-400 mt-1">Manage your development projects</p>
          </div>
          <Link
            href="/projects/new"
            className="btn-primary text-sm flex items-center gap-2"
          >
            <Plus className="w-4 h-4" />
            Add Project
          </Link>
        </div>
      </header>

      {/* Hero Stats */}
      <div className="grid grid-cols-3 gap-4">
        <div className="card p-4 border-phosphor-500/20">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-phosphor-500/10">
              <FolderKanban className="w-5 h-5 text-phosphor-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-white tabular-nums">{totalProjects}</p>
              <p className="text-xs text-slate-500">Total Projects</p>
            </div>
          </div>
        </div>
        <div className="card p-4 border-green-500/20">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-green-500/10">
              <Target className="w-5 h-5 text-green-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-white tabular-nums">{healthyProjects}</p>
              <p className="text-xs text-slate-500">Healthy</p>
            </div>
          </div>
        </div>
        <div className="card p-4 border-amber-500/20">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-amber-500/10">
              <ListTodo className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <p className="text-2xl font-bold text-white tabular-nums">0</p>
              <p className="text-xs text-slate-500">Active Tasks</p>
            </div>
          </div>
        </div>
      </div>

      {/* Projects Grid */}
      {isLoading ? (
        <div className="card p-8 text-center">
          <div className="inline-flex items-center gap-2 text-slate-400">
            <div className="w-4 h-4 border-2 border-phosphor-500/30 border-t-phosphor-500 rounded-full animate-spin" />
            Loading projects...
          </div>
        </div>
      ) : !projects?.length ? (
        <div className="card p-8 text-center border-dashed">
          <FolderKanban className="w-12 h-12 mx-auto text-slate-600 mb-4" />
          <p className="text-slate-400 mb-4">No projects registered yet</p>
          <Link
            href="/projects/new"
            className="btn-primary inline-flex items-center gap-2"
          >
            <Plus className="w-4 h-4" />
            Add Your First Project
          </Link>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {projects.map((project: Project) => (
            <ProjectCard key={project.id} project={project} />
          ))}
        </div>
      )}
    </div>
  );
}

function ProjectCard({ project }: { project: Project }) {
  // Generate gradient based on first letter
  const gradients: Record<string, { from: string; to: string }> = {
    S: { from: "#00c853", to: "#009624" },
    P: { from: "#3b82f6", to: "#2563eb" },
    A: { from: "#8b5cf6", to: "#6d28d9" },
    C: { from: "#f59e0b", to: "#d97706" },
    default: { from: "#64748b", to: "#475569" },
  };
  const firstLetter = project.name.charAt(0).toUpperCase();
  const gradient = gradients[firstLetter] ?? gradients.default;

  return (
    <Link
      href={`/projects/${project.id}`}
      className={clsx(
        "card-elevated p-5 group transition-all duration-300",
        "hover:border-phosphor-500/50 hover:translate-y-[-2px]"
      )}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          {/* Project avatar with gradient */}
          <div
            className="w-12 h-12 rounded-xl flex items-center justify-center"
            style={{
              background: `linear-gradient(135deg, ${gradient.from} 0%, ${gradient.to} 100%)`,
            }}
          >
            <span className="display font-bold text-xl text-white">
              {firstLetter}
            </span>
          </div>
          <div>
            <h3 className="font-medium text-white group-hover:text-phosphor-400 transition-colors">
              {project.name}
            </h3>
            <p className="text-xs mono text-slate-500 truncate max-w-[200px]">
              {project.base_url}
            </p>
          </div>
        </div>

        {/* Health status with glow */}
        <div
          className={clsx(
            "w-3 h-3 rounded-full",
            project.health_status === "healthy"
              ? "bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]"
              : "bg-slate-600"
          )}
        />
      </div>

      <div className="mt-4 pt-3 border-t border-slate-800 flex items-center justify-between">
        {/* Placeholder counts */}
        <div className="flex items-center gap-4 text-xs text-slate-500">
          <span>0 features</span>
          <span>0 tasks</span>
        </div>
        <span className="text-xs text-slate-500 flex items-center gap-1">
          <Clock className="w-3 h-3" />
          {new Date(project.created_at).toLocaleDateString()}
        </span>
      </div>
    </Link>
  );
}
