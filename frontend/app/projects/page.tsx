"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { FolderKanban, Plus, ExternalLink, Activity } from "lucide-react";
import { fetchProjects, type Project } from "@/lib/api";

export default function ProjectsPage() {
  const { data: projects, isLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: fetchProjects,
  });

  return (
    <div className="p-6 space-y-6">
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

      {isLoading ? (
        <div className="card p-8 text-center">
          <div className="inline-flex items-center gap-2 text-slate-400">
            <div className="w-4 h-4 border-2 border-phosphor-500/30 border-t-phosphor-500 rounded-full animate-spin" />
            Loading projects...
          </div>
        </div>
      ) : !projects?.length ? (
        <div className="card p-8 text-center">
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
        <div className="grid gap-4">
          {projects.map((project: Project) => (
            <Link
              key={project.id}
              href={`/projects/${project.id}`}
              className="card p-5 hover:border-slate-600 transition-all group"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-4">
                  <div className="p-2.5 rounded-lg bg-phosphor-500/10 text-phosphor-400">
                    <FolderKanban className="w-5 h-5" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-white group-hover:text-phosphor-400 transition-colors">
                      {project.name}
                    </h3>
                    <p className="text-sm text-slate-500 mt-1">{project.base_url}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className={`status-dot ${project.health_status === "healthy" ? "healthy" : "error"}`} />
                  <ExternalLink className="w-4 h-4 text-slate-500 group-hover:text-phosphor-400 transition-colors" />
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
