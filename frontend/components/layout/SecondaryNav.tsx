"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import {
  Kanban,
  ListTodo,
  Camera,
  Compass,
  Settings2,
  FlaskConical,
  FileCode,
  GitBranch,
  Archive,
  ChevronLeft,
  ChevronRight,
  Folder,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { fetchProject } from "@/lib/api";
import clsx from "clsx";
import { useState, useEffect } from "react";

type NavItemId =
  | "kanban"
  | "tasks"
  | "tests"
  | "prompts"
  | "evidence"
  | "explorer"
  | "git"
  | "backups"
  | "settings";

interface NavItemConfig {
  id: NavItemId;
  label: string;
  icon: React.ElementType;
  activeClasses: string;
  inactiveClasses: string;
  iconActiveClasses: string;
  iconInactiveClasses: string;
  isSettings?: boolean;
  isRoute?: boolean;
}

const navItems: NavItemConfig[] = [
  {
    id: "kanban",
    label: "Kanban",
    icon: Kanban,
    activeClasses: "bg-cyan-500/15 text-cyan-400",
    inactiveClasses: "text-slate-400 hover:bg-cyan-500/10 hover:text-cyan-400",
    iconActiveClasses: "text-cyan-400",
    iconInactiveClasses: "text-slate-500 group-hover:text-cyan-400",
  },
  {
    id: "tasks",
    label: "Tasks",
    icon: ListTodo,
    activeClasses: "bg-orange-500/15 text-orange-400",
    inactiveClasses:
      "text-slate-400 hover:bg-orange-500/10 hover:text-orange-400",
    iconActiveClasses: "text-orange-400",
    iconInactiveClasses: "text-slate-500 group-hover:text-orange-400",
  },
  {
    id: "tests",
    label: "Tests",
    icon: FlaskConical,
    activeClasses: "bg-phosphor-500/15 text-phosphor-400",
    inactiveClasses:
      "text-slate-400 hover:bg-phosphor-500/10 hover:text-phosphor-400",
    iconActiveClasses: "text-phosphor-400",
    iconInactiveClasses: "text-slate-500 group-hover:text-phosphor-400",
    isRoute: true,
  },
  {
    id: "prompts",
    label: "Prompts",
    icon: FileCode,
    activeClasses: "bg-amber-500/15 text-amber-400",
    inactiveClasses:
      "text-slate-400 hover:bg-amber-500/10 hover:text-amber-400",
    iconActiveClasses: "text-amber-400",
    iconInactiveClasses: "text-slate-500 group-hover:text-amber-400",
    isRoute: true,
  },
  {
    id: "evidence",
    label: "Evidence",
    icon: Camera,
    activeClasses: "bg-pink-500/15 text-pink-400",
    inactiveClasses: "text-slate-400 hover:bg-pink-500/10 hover:text-pink-400",
    iconActiveClasses: "text-pink-400",
    iconInactiveClasses: "text-slate-500 group-hover:text-pink-400",
  },
  {
    id: "explorer",
    label: "Explorer",
    icon: Compass,
    activeClasses: "bg-teal-500/15 text-teal-400",
    inactiveClasses: "text-slate-400 hover:bg-teal-500/10 hover:text-teal-400",
    iconActiveClasses: "text-teal-400",
    iconInactiveClasses: "text-slate-500 group-hover:text-teal-400",
  },
  {
    id: "git",
    label: "Git",
    icon: GitBranch,
    activeClasses: "bg-violet-500/15 text-violet-400",
    inactiveClasses:
      "text-slate-400 hover:bg-violet-500/10 hover:text-violet-400",
    iconActiveClasses: "text-violet-400",
    iconInactiveClasses: "text-slate-500 group-hover:text-violet-400",
    isRoute: true,
  },
  {
    id: "backups",
    label: "Backups",
    icon: Archive,
    activeClasses: "bg-indigo-500/15 text-indigo-400",
    inactiveClasses:
      "text-slate-400 hover:bg-indigo-500/10 hover:text-indigo-400",
    iconActiveClasses: "text-indigo-400",
    iconInactiveClasses: "text-slate-500 group-hover:text-indigo-400",
    isRoute: true,
  },
  {
    id: "settings",
    label: "Settings",
    icon: Settings2,
    activeClasses: "bg-slate-500/15 text-slate-300",
    inactiveClasses:
      "text-slate-400 hover:bg-slate-500/10 hover:text-slate-300",
    iconActiveClasses: "text-slate-300",
    iconInactiveClasses: "text-slate-500 group-hover:text-slate-300",
    isSettings: true,
  },
];

const STORAGE_KEY = "summitflow_sidebar_collapsed";

interface SecondaryNavProps {
  projectId: string;
  className?: string;
}

export function SecondaryNav({ projectId, className }: SecondaryNavProps) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [mounted, setMounted] = useState(false);

  const { data: project } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => fetchProject(projectId),
    staleTime: 60000,
  });

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored !== null) {
      setIsCollapsed(stored === "true");
    }
    setMounted(true);
  }, []);

  const toggleCollapsed = () => {
    const newValue = !isCollapsed;
    setIsCollapsed(newValue);
    localStorage.setItem(STORAGE_KEY, String(newValue));
  };

  const getActiveTab = (): NavItemId => {
    if (pathname.includes("/settings")) return "settings";
    if (pathname.includes("/tests")) return "tests";
    if (pathname.includes("/prompts")) return "prompts";
    if (pathname.includes("/git")) return "git";
    if (pathname.includes("/backups")) return "backups";

    const tab = searchParams.get("tab") as NavItemId | null;
    return tab || "kanban";
  };

  const activeTab = getActiveTab();

  if (!mounted) {
    return (
      <nav
        className={clsx(
          "h-full bg-slate-900/50 border-r border-slate-700/50 flex-col",
          "w-16",
          "hidden md:flex",
          className,
        )}
      />
    );
  }

  return (
    <nav
      className={clsx(
        "h-full bg-slate-900/50 border-r border-slate-700/50 flex-col transition-all duration-300",
        isCollapsed ? "w-16" : "w-56",
        "hidden md:flex",
        className,
      )}
    >
      {/* Project Header */}
      <div className="p-3 border-b border-slate-700/50">
        <div
          className={clsx(
            "flex items-center gap-2 text-slate-300",
            isCollapsed && "justify-center",
          )}
          title={isCollapsed ? project?.name || projectId : undefined}
        >
          <div
            className={clsx(
              "flex-shrink-0 flex items-center justify-center rounded-md",
              "bg-outrun-500/20 text-outrun-400",
              isCollapsed ? "w-10 h-10" : "w-8 h-8",
            )}
          >
            <Folder className={clsx(isCollapsed ? "w-5 h-5" : "w-4 h-4")} />
          </div>
          {!isCollapsed && (
            <span className="text-sm font-medium truncate">
              {project?.name || projectId}
            </span>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto py-3 px-2">
        <div className="space-y-1">
          {navItems.map((item) => {
            const isActive = activeTab === item.id;
            const Icon = item.icon;

            const href = item.isSettings
              ? `/projects/${projectId}/settings`
              : item.isRoute
                ? `/projects/${projectId}/${item.id}`
                : `/projects/${projectId}?tab=${item.id}`;

            return (
              <Link
                key={item.id}
                href={href}
                className={clsx(
                  "group flex items-center rounded-lg text-sm font-medium transition-all duration-200",
                  isCollapsed
                    ? "px-3 py-3 justify-center"
                    : "px-3 py-2.5 gap-3",
                  isActive ? item.activeClasses : item.inactiveClasses,
                )}
                title={isCollapsed ? item.label : undefined}
              >
                <Icon
                  className={clsx(
                    "w-5 h-5 flex-shrink-0 transition-colors duration-200",
                    isActive
                      ? item.iconActiveClasses
                      : item.iconInactiveClasses,
                  )}
                />
                {!isCollapsed && <span className="truncate">{item.label}</span>}
              </Link>
            );
          })}
        </div>
      </div>

      <div className="p-2 border-t border-slate-700/50">
        <button
          onClick={toggleCollapsed}
          className="w-full flex items-center justify-center p-2 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-slate-800/50 transition-colors"
          title={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {isCollapsed ? (
            <ChevronRight className="w-5 h-5" />
          ) : (
            <ChevronLeft className="w-5 h-5" />
          )}
        </button>
      </div>
    </nav>
  );
}

export type { NavItemId };
