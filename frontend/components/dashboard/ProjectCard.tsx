"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Clock } from "lucide-react";
import { fetchProjectHealth, type Project } from "@/lib/api";
import { useState } from "react";
import clsx from "clsx";

interface ProjectCardProps {
  project: Project;
}

export function ProjectCard({ project }: ProjectCardProps) {
  const [showHealth, setShowHealth] = useState(false);

  const { data: health, isLoading: healthLoading } = useQuery({
    queryKey: ["project-health", project.id],
    queryFn: () => fetchProjectHealth(project.id),
    enabled: showHealth,
    refetchInterval: showHealth ? 30000 : false,
  });

  // Generate gradient based on first letter
  const gradients: Record<string, { from: string; to: string }> = {
    S: { from: "#00c853", to: "#009624" },
    P: { from: "#3b82f6", to: "#2563eb" },
    A: { from: "#8b5cf6", to: "#6d28d9" },
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
      onMouseEnter={() => setShowHealth(true)}
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
            <p className="text-xs mono text-slate-500 truncate max-w-[180px]">
              {project.base_url}
            </p>
          </div>
        </div>

        {/* Health status with glow */}
        <div className="flex items-center gap-2">
          {healthLoading ? (
            <div className="w-3 h-3 border border-slate-600 border-t-phosphor-500 rounded-full animate-spin" />
          ) : health ? (
            <div
              className={clsx(
                "w-3 h-3 rounded-full",
                health.healthy
                  ? "bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.6)]"
                  : "bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.6)]"
              )}
            />
          ) : (
            <div className="w-3 h-3 rounded-full bg-slate-600" />
          )}
        </div>
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
