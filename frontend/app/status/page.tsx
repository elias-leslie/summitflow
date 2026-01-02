"use client";

/**
 * Status Page - Codebase Health Dashboard
 *
 * Shows scan history, complexity trends, and recent scan activity
 * across all projects or a selected project.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Activity } from "lucide-react";
import Link from "next/link";
import { fetchProjects, type Project } from "@/lib/api";
import { ScanHistoryChart } from "@/components/explorer/ScanHistoryChart";

export default function StatusPage() {
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);

  // Fetch projects for selector
  const { data: projects = [], isLoading: projectsLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: fetchProjects,
  });

  // Default to first project if none selected
  const projectId = selectedProjectId ?? projects[0]?.id ?? null;

  if (projectsLoading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-purple-500/30 border-t-purple-500 rounded-full animate-spin" />
      </div>
    );
  }

  if (!projects.length) {
    return (
      <div className="min-h-screen bg-slate-950 p-8">
        <div className="max-w-4xl mx-auto">
          <Link
            href="/"
            className="inline-flex items-center gap-2 text-slate-400 hover:text-slate-200 mb-8"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Dashboard
          </Link>
          <div className="text-center py-16">
            <Activity className="h-12 w-12 text-slate-600 mx-auto mb-4" />
            <h2 className="text-xl font-medium text-slate-200 mb-2">
              No Projects Found
            </h2>
            <p className="text-slate-500">
              Create a project to start tracking codebase health.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 p-8">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-4">
            <Link
              href="/"
              className="inline-flex items-center gap-2 text-slate-400 hover:text-slate-200"
            >
              <ArrowLeft className="h-4 w-4" />
            </Link>
            <div>
              <h1 className="text-2xl font-semibold text-white">
                Codebase Health
              </h1>
              <p className="text-sm text-slate-400 mt-1">
                Track complexity trends and scan history
              </p>
            </div>
          </div>

          {/* Project selector */}
          <select
            value={projectId ?? ""}
            onChange={(e) => setSelectedProjectId(e.target.value || null)}
            className="bg-slate-800 border border-slate-700 text-slate-200 rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
          >
            {projects.map((project: Project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </div>

        {/* Codebase Health Card */}
        {projectId && (
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
            <div className="flex items-center gap-3 mb-6">
              <div className="p-2 bg-purple-500/10 rounded-lg">
                <Activity className="h-5 w-5 text-purple-400" />
              </div>
              <div>
                <h2 className="text-lg font-medium text-white">
                  Complexity Trend
                </h2>
                <p className="text-sm text-slate-400">
                  Track codebase health over time
                </p>
              </div>
            </div>

            <ScanHistoryChart projectId={projectId} />
          </div>
        )}
      </div>
    </div>
  );
}
