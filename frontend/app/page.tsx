"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FolderKanban, Activity, AlertCircle, Plus, ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { fetchProjectsWithStats, type ProjectWithStats } from "@/lib/api";
import { ProjectCard, ActivityFeed } from "@/components/dashboard";

const PROJECTS_PER_PAGE = 9;

export default function DashboardPage() {
  const [page, setPage] = useState(0);

  const { data, isLoading, error } = useQuery({
    queryKey: ["projects-with-stats"],
    queryFn: fetchProjectsWithStats,
  });

  const projects = data?.projects ?? [];
  const totalProjects = projects.length;
  const totalPages = Math.ceil(totalProjects / PROJECTS_PER_PAGE);
  const startIndex = page * PROJECTS_PER_PAGE;
  const endIndex = startIndex + PROJECTS_PER_PAGE;
  const visibleProjects = projects.slice(startIndex, endIndex);

  const handlePrevPage = () => setPage((p) => Math.max(0, p - 1));
  const handleNextPage = () => setPage((p) => Math.min(totalPages - 1, p + 1));

  return (
    <div className="p-6 space-y-8">
      {/* All Projects Section */}
      <section className="animate-in">
        <div className="flex items-center justify-between mb-4">
          <h2 className="display font-semibold text-lg text-white flex items-center gap-2">
            <FolderKanban className="w-5 h-5 text-phosphor-500" />
            All Projects
          </h2>
          <div className="flex items-center gap-3">
            {/* Pagination controls */}
            {totalPages > 1 && (
              <div className="flex items-center gap-2 text-sm">
                <button
                  onClick={handlePrevPage}
                  disabled={page === 0}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <span className="text-slate-400 tabular-nums min-w-[60px] text-center">
                  {page + 1} / {totalPages}
                </span>
                <button
                  onClick={handleNextPage}
                  disabled={page === totalPages - 1}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            )}
            <Link href="/projects/new" className="btn-primary text-sm flex items-center gap-2">
              <Plus className="w-4 h-4" />
              Add Project
            </Link>
          </div>
        </div>
        <ProjectsGrid
          projects={visibleProjects}
          isLoading={isLoading}
          error={error}
        />
      </section>

      {/* Recent Activity Section */}
      <section className="animate-fade-in" style={{ animationDelay: "0.1s" }}>
        <h2 className="display font-semibold text-lg text-white flex items-center gap-2 mb-4">
          <Activity className="w-5 h-5 text-phosphor-500" />
          Recent Activity
        </h2>
        <ActivityFeed />
      </section>
    </div>
  );
}

interface ProjectsGridProps {
  projects: ProjectWithStats[];
  isLoading: boolean;
  error: Error | null;
}

function ProjectsGrid({ projects, isLoading, error }: ProjectsGridProps) {
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

  if (!projects.length) {
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
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {projects.map((project) => (
        <ProjectCard key={project.id} project={project} />
      ))}
    </div>
  );
}
