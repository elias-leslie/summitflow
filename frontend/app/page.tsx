"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  FolderKanban,
  Target,
  Compass,
  ArrowUpRight,
  Clock,
  CheckCircle2,
  AlertCircle,
  Plus,
} from "lucide-react";
import Link from "next/link";
import { fetchProjects, fetchProjectHealth, type Project } from "@/lib/api";
import { useState } from "react";

export default function DashboardPage() {
  return (
    <div className="p-6 space-y-6">
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
      <StatsGrid />

      {/* Projects Section */}
      <section className="animate-fade-in" style={{ animationDelay: "0.1s" }}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="display font-semibold text-lg text-white flex items-center gap-2">
            <FolderKanban className="w-5 h-5 text-phosphor-500" />
            Registered Projects
          </h2>
          <Link href="/projects/new" className="btn-primary text-sm flex items-center gap-2">
            <Plus className="w-4 h-4" />
            Add Project
          </Link>
        </div>
        <ProjectsGrid />
      </section>

      {/* Recent Activity */}
      <section className="animate-fade-in" style={{ animationDelay: "0.2s" }}>
        <h2 className="display font-semibold text-lg text-white flex items-center gap-2 mb-4">
          <Activity className="w-5 h-5 text-phosphor-500" />
          Recent Activity
        </h2>
        <RecentActivity />
      </section>
    </div>
  );
}

function StatsGrid() {
  const { data: projects } = useQuery({
    queryKey: ["projects"],
    queryFn: fetchProjects,
  });

  const stats = [
    {
      label: "Projects",
      value: projects?.length ?? 0,
      icon: FolderKanban,
      color: "phosphor",
      href: "/projects",
    },
    {
      label: "Features",
      value: 0,
      icon: Target,
      color: "amber",
      href: "/features",
    },
    {
      label: "Explorer",
      value: 0,
      icon: Compass,
      color: "rose",
      href: "/projects",
    },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 animate-fade-in" style={{ animationDelay: "0.05s" }}>
      {stats.map((stat) => (
        <Link
          key={stat.label}
          href={stat.href}
          className="card-elevated p-5 group hover:border-slate-600 transition-all duration-300"
        >
          <div className="flex items-start justify-between">
            <div>
              <p className="text-sm text-slate-400 mb-1">{stat.label}</p>
              <p className="display text-3xl font-bold text-white tabular-nums">
                {stat.value}
              </p>
            </div>
            <div
              className={`p-2.5 rounded-lg ${
                stat.color === "phosphor"
                  ? "bg-phosphor-500/10 text-phosphor-400"
                  : stat.color === "amber"
                  ? "bg-amber-500/10 text-amber-400"
                  : "bg-rose-500/10 text-rose-400"
              }`}
            >
              <stat.icon className="w-5 h-5" />
            </div>
          </div>
          <div className="mt-3 flex items-center text-xs text-slate-500 group-hover:text-phosphor-400 transition-colors">
            View details
            <ArrowUpRight className="w-3 h-3 ml-1" />
          </div>
        </Link>
      ))}
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
      {projects.map((project) => (
        <ProjectCard key={project.id} project={project} />
      ))}
    </div>
  );
}

function ProjectCard({ project }: { project: Project }) {
  const [showHealth, setShowHealth] = useState(false);

  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ["project-health", project.id],
    queryFn: () => fetchProjectHealth(project.id),
    enabled: showHealth,
    refetchInterval: showHealth ? 30000 : false,
  });

  return (
    <Link
      href={`/projects/${project.id}`}
      className="card-elevated p-5 group hover:border-phosphor-500/30 transition-all duration-300"
      onMouseEnter={() => setShowHealth(true)}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-slate-800 flex items-center justify-center">
            <span className="display font-bold text-phosphor-400">
              {project.name.charAt(0)}
            </span>
          </div>
          <div>
            <h3 className="font-medium text-white group-hover:text-phosphor-400 transition-colors">
              {project.name}
            </h3>
            <p className="text-xs mono text-slate-500">{project.id}</p>
          </div>
        </div>

        {/* Health status */}
        <div className="flex items-center gap-2">
          {healthLoading ? (
            <div className="w-3 h-3 border border-slate-600 border-t-phosphor-500 rounded-full animate-spin" />
          ) : health ? (
            <>
              <div
                className={`status-dot ${health.healthy ? "healthy" : "error"}`}
              />
              {health.response_time_ms && (
                <span className="text-[10px] mono text-slate-500 tabular-nums">
                  {Math.round(health.response_time_ms)}ms
                </span>
              )}
            </>
          ) : (
            <div className="status-dot unknown" />
          )}
        </div>
      </div>

      <div className="mt-4 pt-3 border-t border-slate-800 flex items-center justify-between">
        <span className="text-xs text-slate-500 mono truncate max-w-[200px]">
          {project.base_url}
        </span>
        <span className="text-xs text-slate-500 flex items-center gap-1">
          <Clock className="w-3 h-3" />
          {new Date(project.created_at).toLocaleDateString()}
        </span>
      </div>
    </Link>
  );
}

function RecentActivity() {
  // Placeholder for recent activity - will be populated as features are added
  const activities = [
    {
      id: 1,
      type: "system",
      message: "SummitFlow initialized",
      time: "Just now",
      icon: CheckCircle2,
    },
  ];

  return (
    <div className="card divide-y divide-slate-800">
      {activities.map((activity) => (
        <div
          key={activity.id}
          className="p-4 flex items-center gap-4 hover:bg-slate-800/30 transition-colors"
        >
          <div className="p-2 rounded-lg bg-phosphor-500/10">
            <activity.icon className="w-4 h-4 text-phosphor-400" />
          </div>
          <div className="flex-1">
            <p className="text-sm text-slate-300">{activity.message}</p>
          </div>
          <span className="text-xs text-slate-500 mono">{activity.time}</span>
        </div>
      ))}

      {activities.length === 1 && (
        <div className="p-6 text-center">
          <p className="text-sm text-slate-500">
            Activity feed will populate as you use SummitFlow
          </p>
        </div>
      )}
    </div>
  );
}
