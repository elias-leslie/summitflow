"use client";

import Link from "next/link";
import { usePathname, useSearchParams, useRouter } from "next/navigation";
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
  ChevronDown,
  LayoutGrid,
  Check,
  FolderKanban,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { fetchProject, fetchProjects } from "@/lib/api";
import clsx from "clsx";
import { useState, useEffect, useRef, Suspense } from "react";

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

const projectNavItems: NavItemConfig[] = [
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

function SidebarContent() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Check if we're on a project page
  const projectMatch = pathname.match(/^\/projects\/([^/]+)/);
  const currentProjectId = projectMatch ? projectMatch[1] : null;

  const { data: project } = useQuery({
    queryKey: ["project", currentProjectId],
    queryFn: () => fetchProject(currentProjectId!),
    enabled: !!currentProjectId,
    staleTime: 60000,
  });

  const { data: projects } = useQuery({
    queryKey: ["projects"],
    queryFn: fetchProjects,
  });

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored !== null) {
      setIsCollapsed(stored === "true");
    }
    setMounted(true);
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const toggleCollapsed = () => {
    const newValue = !isCollapsed;
    setIsCollapsed(newValue);
    localStorage.setItem(STORAGE_KEY, String(newValue));
    if (newValue) setDropdownOpen(false);
  };

  const handleSelectProject = (newProjectId: string) => {
    setDropdownOpen(false);
    const currentTab = searchParams.get("tab");
    let targetUrl = `/projects/${newProjectId}`;
    if (currentTab && currentProjectId) {
      targetUrl += `?tab=${currentTab}`;
    }
    router.push(targetUrl);
  };

  const handleGoToDashboard = () => {
    setDropdownOpen(false);
    router.push("/");
  };

  const getActiveTab = (): NavItemId | null => {
    if (!currentProjectId) return null;
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
        )}
      />
    );
  }

  const headerName = currentProjectId
    ? project?.name || currentProjectId
    : "Projects";
  const headerSubtitle = currentProjectId
    ? "Project"
    : `${projects?.length || 0} registered`;

  return (
    <nav
      className={clsx(
        "h-full bg-slate-900/50 border-r border-slate-700/50 flex-col transition-all duration-300",
        isCollapsed ? "w-16" : "w-56",
        "hidden md:flex",
      )}
    >
      {/* Header with Project/Projects Dropdown */}
      <div className="relative" ref={dropdownRef}>
        <button
          onClick={() => !isCollapsed && setDropdownOpen(!dropdownOpen)}
          disabled={isCollapsed}
          className={clsx(
            "w-full p-3 border-b border-slate-700/50 transition-all duration-200",
            !isCollapsed && "hover:bg-slate-800/50 cursor-pointer group",
            isCollapsed && "cursor-default",
          )}
          title={isCollapsed ? headerName : undefined}
        >
          <div
            className={clsx(
              "flex items-center gap-2.5",
              isCollapsed && "justify-center",
            )}
          >
            {/* Icon with Health/Status Glow */}
            <div className="relative flex-shrink-0">
              <div
                className={clsx(
                  "flex items-center justify-center rounded-lg transition-all duration-300",
                  currentProjectId
                    ? "bg-gradient-to-br from-outrun-500/20 to-pink-500/10 border-outrun-500/30"
                    : "bg-gradient-to-br from-phosphor-500/20 to-teal-500/10 border-phosphor-500/30",
                  "border",
                  isCollapsed ? "w-10 h-10" : "w-9 h-9",
                  !isCollapsed &&
                    (currentProjectId
                      ? "group-hover:border-outrun-500/50 group-hover:shadow-[0_0_12px_rgba(255,0,102,0.2)]"
                      : "group-hover:border-phosphor-500/50 group-hover:shadow-[0_0_12px_rgba(0,255,136,0.2)]"),
                )}
              >
                {currentProjectId ? (
                  <span
                    className={clsx(
                      "font-bold text-outrun-400 transition-all duration-300",
                      isCollapsed ? "text-base" : "text-sm",
                      !isCollapsed && "group-hover:text-outrun-300",
                    )}
                  >
                    {headerName.charAt(0).toUpperCase()}
                  </span>
                ) : (
                  <FolderKanban
                    className={clsx(
                      "text-phosphor-400 transition-all duration-300",
                      isCollapsed ? "w-5 h-5" : "w-4 h-4",
                      !isCollapsed && "group-hover:text-phosphor-300",
                    )}
                  />
                )}
              </div>
              {/* Health Status Indicator (only for project) */}
              {currentProjectId && (
                <div
                  className={clsx(
                    "absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border-2 border-slate-900",
                    project?.health_status === "healthy"
                      ? "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.6)]"
                      : "bg-slate-500",
                  )}
                />
              )}
            </div>

            {/* Name & Chevron */}
            {!isCollapsed && (
              <>
                <div className="flex-1 min-w-0 text-left">
                  <div className="text-sm font-semibold text-slate-200 truncate group-hover:text-white transition-colors">
                    {headerName}
                  </div>
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider">
                    {headerSubtitle}
                  </div>
                </div>
                <ChevronDown
                  className={clsx(
                    "w-4 h-4 text-slate-500 transition-all duration-300 flex-shrink-0",
                    "group-hover:text-slate-300",
                    dropdownOpen &&
                      (currentProjectId
                        ? "rotate-180 text-outrun-400"
                        : "rotate-180 text-phosphor-400"),
                  )}
                />
              </>
            )}
          </div>
        </button>

        {/* Dropdown Menu */}
        {dropdownOpen && !isCollapsed && (
          <div
            className={clsx(
              "absolute left-0 right-0 top-full z-50",
              "bg-slate-900/95 backdrop-blur-sm",
              "border-x border-b border-slate-700/50",
              "shadow-2xl shadow-black/50",
              "animate-in fade-in slide-in-from-top-2 duration-200",
              "max-h-[70vh] overflow-y-auto",
            )}
          >
            {/* Dashboard Link */}
            <button
              onClick={handleGoToDashboard}
              className={clsx(
                "w-full flex items-center gap-3 px-4 py-3 text-left transition-colors border-b border-slate-700/30",
                pathname === "/"
                  ? "bg-outrun-500/15"
                  : "hover:bg-outrun-500/10",
              )}
            >
              <div className="w-8 h-8 rounded-lg bg-slate-800 flex items-center justify-center">
                <LayoutGrid className="w-4 h-4 text-outrun-400" />
              </div>
              <div className="flex-1">
                <div className="text-sm font-medium text-outrun-400">
                  Dashboard
                </div>
                <div className="text-[10px] text-slate-500">All projects</div>
              </div>
              {pathname === "/" && (
                <Check className="w-4 h-4 text-outrun-400 flex-shrink-0" />
              )}
            </button>

            {/* Projects List */}
            <div className="py-1">
              {projects?.map((p) => (
                <button
                  key={p.id}
                  onClick={() => handleSelectProject(p.id)}
                  className={clsx(
                    "w-full flex items-center gap-3 px-4 py-2.5 text-left transition-all duration-150",
                    p.id === currentProjectId
                      ? "bg-outrun-500/15"
                      : "hover:bg-slate-800/50",
                  )}
                >
                  {/* Project Icon */}
                  <div className="relative flex-shrink-0">
                    <div
                      className={clsx(
                        "w-8 h-8 rounded-lg flex items-center justify-center",
                        "bg-gradient-to-br from-slate-800 to-slate-800/50",
                        "border",
                        p.id === currentProjectId
                          ? "border-outrun-500/50"
                          : "border-slate-700/50",
                      )}
                    >
                      <span
                        className={clsx(
                          "text-xs font-bold",
                          p.id === currentProjectId
                            ? "text-outrun-400"
                            : "text-slate-400",
                        )}
                      >
                        {p.name.charAt(0).toUpperCase()}
                      </span>
                    </div>
                    {/* Health dot */}
                    <div
                      className={clsx(
                        "absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-slate-900",
                        p.health_status === "healthy"
                          ? "bg-emerald-400"
                          : "bg-slate-500",
                      )}
                    />
                  </div>

                  {/* Project Name */}
                  <div className="flex-1 min-w-0">
                    <div
                      className={clsx(
                        "text-sm font-medium truncate",
                        p.id === currentProjectId
                          ? "text-white"
                          : "text-slate-300",
                      )}
                    >
                      {p.name}
                    </div>
                  </div>

                  {/* Selected Check */}
                  {p.id === currentProjectId && (
                    <Check className="w-4 h-4 text-outrun-400 flex-shrink-0" />
                  )}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Nav Items */}
      <div className="flex-1 overflow-y-auto py-3 px-2">
        <div className="space-y-1">
          {/* Dashboard link (when on global pages) */}
          {!currentProjectId && (
            <Link
              href="/"
              className={clsx(
                "group flex items-center rounded-lg text-sm font-medium transition-all duration-200",
                isCollapsed ? "px-3 py-3 justify-center" : "px-3 py-2.5 gap-3",
                pathname === "/"
                  ? "bg-outrun-500/15 text-outrun-400"
                  : "text-slate-400 hover:bg-outrun-500/10 hover:text-outrun-400",
              )}
              title={isCollapsed ? "Dashboard" : undefined}
            >
              <LayoutGrid
                className={clsx(
                  "w-5 h-5 flex-shrink-0 transition-colors duration-200",
                  pathname === "/"
                    ? "text-outrun-400"
                    : "text-slate-500 group-hover:text-outrun-400",
                )}
              />
              {!isCollapsed && <span className="truncate">Dashboard</span>}
            </Link>
          )}

          {/* Project nav items (when on project pages) */}
          {currentProjectId &&
            projectNavItems.map((item) => {
              const isActive = activeTab === item.id;
              const Icon = item.icon;

              const href = item.isSettings
                ? `/projects/${currentProjectId}/settings`
                : item.isRoute
                  ? `/projects/${currentProjectId}/${item.id}`
                  : `/projects/${currentProjectId}?tab=${item.id}`;

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
                  {!isCollapsed && (
                    <span className="truncate">{item.label}</span>
                  )}
                </Link>
              );
            })}
        </div>
      </div>

      {/* Collapse Toggle */}
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

export function Sidebar() {
  return (
    <Suspense
      fallback={
        <div className="w-16 h-full bg-slate-900/50 border-r border-slate-700/50 hidden md:block" />
      }
    >
      <SidebarContent />
    </Suspense>
  );
}
