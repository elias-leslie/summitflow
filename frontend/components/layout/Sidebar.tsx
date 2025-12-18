"use client";

import Link from "next/link";
import { usePathname, useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard,
  FolderKanban,
  Compass,
  Target,
  Camera,
  Settings,
  ChevronRight,
  ChevronDown,
  Check,
} from "lucide-react";
import clsx from "clsx";
import { useState, useEffect, useRef } from "react";
import { fetchProjects, type Project } from "@/lib/api";

export function Sidebar() {
  const pathname = usePathname();
  const params = useParams();
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

  // Build navigation - project-scoped links when project is selected
  const getNavigation = () => {
    const base = [
      { name: "Dashboard", href: "/", icon: LayoutDashboard },
      { name: "Projects", href: "/projects", icon: FolderKanban },
    ];

    if (selectedProjectId) {
      return [
        ...base,
        { name: "Explorer", href: `/projects/${selectedProjectId}?tab=explorer`, icon: Compass },
        { name: "Features", href: `/projects/${selectedProjectId}?tab=features`, icon: Target },
        { name: "Evidence", href: `/projects/${selectedProjectId}?tab=evidence`, icon: Camera },
      ];
    }

    return [
      ...base,
      { name: "Features", href: "/features", icon: Target },
      { name: "Evidence", href: "/evidence", icon: Camera },
    ];
  };

  const navigation = getNavigation();

  const handleSelectProject = (projectId: string | null) => {
    setSelectedProjectId(projectId);
    if (projectId) {
      localStorage.setItem("summitflow_selected_project", projectId);
    } else {
      localStorage.removeItem("summitflow_selected_project");
    }
    setIsDropdownOpen(false);
  };

  return (
    <aside className="w-64 flex-shrink-0 bg-slate-900 border-r border-slate-800 flex flex-col">
      {/* Logo */}
      <div className="h-16 flex items-center px-5 border-b border-slate-800">
        <Link href="/" className="flex items-center gap-3 group">
          <div className="relative">
            <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-phosphor-500 to-phosphor-600 flex items-center justify-center glow-phosphor-sm">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                className="w-5 h-5 text-white"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="M12 2L2 7l10 5 10-5-10-5z" />
                <path d="M2 17l10 5 10-5" />
                <path d="M2 12l10 5 10-5" />
              </svg>
            </div>
          </div>
          <div>
            <span className="display font-semibold text-lg text-white tracking-tight">
              SummitFlow
            </span>
            <span className="block text-[10px] mono text-phosphor-500 uppercase tracking-widest">
              Dev Platform
            </span>
          </div>
        </Link>
      </div>

      {/* Project Selector */}
      <div className="px-3 py-3 border-b border-slate-800" ref={dropdownRef}>
        <div className="relative">
          <button
            onClick={() => setIsDropdownOpen(!isDropdownOpen)}
            className={clsx(
              "w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-all",
              selectedProject
                ? "bg-slate-800 text-white border border-slate-700"
                : "bg-slate-800/50 text-slate-400 border border-slate-700/50 hover:border-slate-600"
            )}
          >
            <div className="flex items-center gap-2 truncate">
              <FolderKanban className="w-4 h-4 flex-shrink-0 text-slate-500" />
              <span className="truncate">
                {selectedProject ? selectedProject.name : "Select project..."}
              </span>
            </div>
            <ChevronDown
              className={clsx(
                "w-4 h-4 flex-shrink-0 text-slate-500 transition-transform",
                isDropdownOpen && "rotate-180"
              )}
            />
          </button>

          {/* Dropdown */}
          {isDropdownOpen && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-slate-800 border border-slate-700 rounded-lg shadow-xl z-50 max-h-64 overflow-y-auto">
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
                          project.health_status === "healthy" ? "bg-green-500" : "bg-slate-500"
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
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        <div className="mb-3 px-2">
          <span className="text-[10px] mono uppercase tracking-widest text-slate-500">
            Navigation
          </span>
        </div>
        {navigation.map((item) => {
          const isActive = pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(item.href.split("?")[0]));
          return (
            <Link
              key={item.name}
              href={item.href}
              className={clsx(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 group",
                isActive
                  ? "bg-phosphor-500/10 text-phosphor-400 border border-phosphor-500/20"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
              )}
            >
              <item.icon
                className={clsx(
                  "w-4 h-4 transition-colors",
                  isActive ? "text-phosphor-400" : "text-slate-500 group-hover:text-slate-400"
                )}
              />
              <span>{item.name}</span>
              {isActive && (
                <ChevronRight className="w-3 h-3 ml-auto text-phosphor-500/60" />
              )}
            </Link>
          );
        })}
      </nav>

      {/* Bottom navigation */}
      <div className="px-3 py-4 border-t border-slate-800">
        <Link
          href="/settings"
          className={clsx(
            "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200",
            pathname === "/settings"
              ? "bg-slate-800 text-slate-200"
              : "text-slate-500 hover:text-slate-300 hover:bg-slate-800/50"
          )}
        >
          <Settings className="w-4 h-4" />
          <span>Settings</span>
        </Link>
      </div>

      {/* Status indicator */}
      <div className="px-4 py-3 border-t border-slate-800 bg-slate-950/50">
        <div className="flex items-center gap-2">
          <div className="status-dot healthy animate-pulse-slow" />
          <span className="text-xs mono text-slate-500">
            System Online
          </span>
        </div>
      </div>
    </aside>
  );
}
