"use client";

import { usePathname, useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  FolderKanban,
  ChevronDown,
  Check,
  LayoutGrid,
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

  // Detect project from URL - clear selection when not on a project page
  useEffect(() => {
    const urlProjectId = params.id as string | undefined;
    if (urlProjectId) {
      setSelectedProjectId(urlProjectId);
      localStorage.setItem("summitflow_selected_project", urlProjectId);
    } else if (pathname === "/projects" || pathname === "/") {
      // On projects list or dashboard - clear selection
      setSelectedProjectId(null);
      localStorage.removeItem("summitflow_selected_project");
    }
  }, [params.id, pathname]);

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

  const handleViewAllProjects = () => {
    setIsDropdownOpen(false);
    router.push("/projects");
  };

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsDropdownOpen(!isDropdownOpen)}
        className={clsx(
          "flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-all cursor-pointer",
          "bg-slate-800 border border-slate-700 hover:border-slate-500 hover:bg-slate-750",
          selectedProject ? "text-white" : "text-slate-400"
        )}
      >
        {/* Health dot */}
        <div
          className={clsx(
            "w-2 h-2 rounded-full flex-shrink-0",
            selectedProject?.health_status === "healthy"
              ? "bg-outrun-500 shadow-[0_0_6px_rgba(255,0,102,0.5)]"
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
            "w-4 h-4 flex-shrink-0 text-slate-500 transition-transform duration-200",
            isDropdownOpen && "rotate-180"
          )}
        />
      </button>

      {/* Dropdown */}
      {isDropdownOpen && (
        <div className="absolute top-full left-0 mt-1 w-64 bg-slate-900 border border-slate-700 rounded-lg shadow-2xl z-[100] max-h-80 overflow-y-auto">
          {/* All Projects link */}
          <button
            onClick={handleViewAllProjects}
            className="w-full flex items-center gap-2 px-3 py-2.5 text-sm text-left text-outrun-400 hover:bg-slate-800 transition-colors border-b border-slate-700"
          >
            <LayoutGrid className="w-4 h-4" />
            <span className="font-medium">All Projects</span>
          </button>

          {/* Projects list */}
          <div className="py-1">
            {projects?.length === 0 ? (
              <div className="px-3 py-3 text-sm text-slate-500 text-center">
                No projects yet
              </div>
            ) : (
              projects?.map((project) => (
                <button
                  key={project.id}
                  onClick={() => handleSelectProject(project.id)}
                  className={clsx(
                    "w-full flex items-center justify-between px-3 py-2.5 text-sm text-left transition-colors cursor-pointer",
                    selectedProjectId === project.id
                      ? "bg-outrun-500/15 text-white"
                      : "text-slate-300 hover:bg-slate-800 hover:text-white"
                  )}
                >
                  <div className="flex items-center gap-2 truncate">
                    <div
                      className={clsx(
                        "w-2 h-2 rounded-full flex-shrink-0",
                        project.health_status === "healthy"
                          ? "bg-outrun-500 shadow-[0_0_6px_rgba(255,0,102,0.5)]"
                          : "bg-slate-500"
                      )}
                    />
                    <span className="truncate">{project.name}</span>
                  </div>
                  {selectedProjectId === project.id && (
                    <Check className="w-4 h-4 text-outrun-400 flex-shrink-0" />
                  )}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// Export hook for getting current project ID
export function useSelectedProject() {
  const params = useParams();
  const pathname = usePathname();
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);

  useEffect(() => {
    const urlProjectId = params.id as string | undefined;
    if (urlProjectId) {
      setSelectedProjectId(urlProjectId);
    } else if (pathname === "/projects" || pathname === "/") {
      // On projects list or dashboard - no project selected
      setSelectedProjectId(null);
    }
  }, [params.id, pathname]);

  return selectedProjectId;
}
