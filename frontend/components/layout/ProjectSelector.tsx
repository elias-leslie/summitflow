"use client";

import { usePathname, useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  FolderKanban,
  ChevronDown,
  Check,
} from "lucide-react";
import clsx from "clsx";
import { useState, useEffect, useRef } from "react";
import { fetchProjects, type Project } from "@/lib/api";

interface ProjectSelectorProps {
  onProjectChange?: (projectId: string | null) => void;
}

export function ProjectSelector({ onProjectChange }: ProjectSelectorProps) {
  const pathname = usePathname();
  const params = useParams();
  const router = useRouter();
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Fetch projects
  const { data: projects } = useQuery({
    queryKey: ["projects"],
    queryFn: fetchProjects,
  });

  // Detect project from URL
  useEffect(() => {
    const urlProjectId = params.id as string | undefined;
    if (urlProjectId) {
      setSelectedProjectId(urlProjectId);
      localStorage.setItem("summitflow_selected_project", urlProjectId);
    } else {
      // Try to restore from localStorage
      const stored = localStorage.getItem("summitflow_selected_project");
      if (stored && projects?.some(p => p.id === stored)) {
        setSelectedProjectId(stored);
      }
    }
  }, [params.id, projects]);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const selectedProject = projects?.find(p => p.id === selectedProjectId);

  const handleSelectProject = (projectId: string | null) => {
    setSelectedProjectId(projectId);
    if (projectId) {
      localStorage.setItem("summitflow_selected_project", projectId);
      // Navigate to project page if not already there
      if (!pathname.startsWith(`/projects/${projectId}`)) {
        router.push(`/projects/${projectId}`);
      }
    } else {
      localStorage.removeItem("summitflow_selected_project");
    }
    setIsDropdownOpen(false);
    onProjectChange?.(projectId);
  };

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsDropdownOpen(!isDropdownOpen)}
        className={clsx(
          "flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-all",
          "bg-slate-800 border border-slate-700 hover:border-slate-600",
          selectedProject ? "text-white" : "text-slate-400"
        )}
      >
        {/* Health dot */}
        <div
          className={clsx(
            "w-2 h-2 rounded-full flex-shrink-0",
            selectedProject?.health_status === "healthy"
              ? "bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]"
              : selectedProject
                ? "bg-slate-500"
                : "bg-slate-600"
          )}
        />
        <span className="truncate max-w-[140px]">
          {selectedProject ? selectedProject.name : "Select project..."}
        </span>
        <ChevronDown
          className={clsx(
            "w-4 h-4 flex-shrink-0 text-slate-500 transition-transform",
            isDropdownOpen && "rotate-180"
          )}
        />
      </button>

      {/* Dropdown */}
      {isDropdownOpen && (
        <div className="absolute top-full left-0 mt-1 w-64 bg-slate-800 border border-slate-700 rounded-lg shadow-xl z-50 max-h-64 overflow-y-auto">
          {/* Clear selection */}
          <button
            onClick={() => handleSelectProject(null)}
            className={clsx(
              "w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-slate-700/50 transition-colors",
              !selectedProjectId && "bg-slate-700/30"
            )}
          >
            <span className="text-slate-400">No project selected</span>
          </button>

          {/* Divider */}
          <div className="border-t border-slate-700 my-1" />

          {/* Projects */}
          {projects?.length === 0 ? (
            <div className="px-3 py-2 text-sm text-slate-500">
              No projects yet
            </div>
          ) : (
            projects?.map((project) => (
              <button
                key={project.id}
                onClick={() => handleSelectProject(project.id)}
                className={clsx(
                  "w-full flex items-center justify-between px-3 py-2 text-sm text-left hover:bg-slate-700/50 transition-colors",
                  selectedProjectId === project.id && "bg-phosphor-500/10"
                )}
              >
                <div className="flex items-center gap-2 truncate">
                  <div
                    className={clsx(
                      "w-2 h-2 rounded-full flex-shrink-0",
                      project.health_status === "healthy"
                        ? "bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]"
                        : "bg-slate-500"
                    )}
                  />
                  <span className="truncate text-slate-200">{project.name}</span>
                </div>
                {selectedProjectId === project.id && (
                  <Check className="w-4 h-4 text-phosphor-400 flex-shrink-0" />
                )}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

// Export hook for getting current project ID
export function useSelectedProject() {
  const params = useParams();
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);

  useEffect(() => {
    const urlProjectId = params.id as string | undefined;
    if (urlProjectId) {
      setSelectedProjectId(urlProjectId);
    } else {
      const stored = localStorage.getItem("summitflow_selected_project");
      setSelectedProjectId(stored);
    }
  }, [params.id]);

  return selectedProjectId;
}
