"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  MessageCircle,
  Kanban,
  ListTodo,
  Camera,
  Compass,
  Settings2,
  FlaskConical,
  FileCode,
  GitBranch,
  Archive,
} from "lucide-react";
import clsx from "clsx";

type TabId =
  | "roundtable"
  | "kanban"
  | "tasks"
  | "tests"
  | "prompts"
  | "evidence"
  | "explorer"
  | "git"
  | "backups"
  | "settings";

interface TabConfig {
  id: TabId;
  label: string;
  icon: React.ElementType;
  activeClasses: string;
  inactiveClasses: string;
  iconActiveClasses: string;
  iconInactiveClasses: string;
  isSettings?: boolean;
  isRoute?: boolean;
}

const tabs: TabConfig[] = [
  {
    id: "roundtable",
    label: "Roundtable",
    icon: MessageCircle,
    activeClasses: "bg-emerald-500/15 text-emerald-400",
    inactiveClasses:
      "text-slate-500 hover:bg-emerald-500/10 hover:text-emerald-400",
    iconActiveClasses: "text-emerald-400",
    iconInactiveClasses: "text-slate-500 group-hover:text-emerald-400",
  },
  {
    id: "kanban",
    label: "Kanban",
    icon: Kanban,
    activeClasses: "bg-cyan-500/15 text-cyan-400",
    inactiveClasses: "text-slate-500 hover:bg-cyan-500/10 hover:text-cyan-400",
    iconActiveClasses: "text-cyan-400",
    iconInactiveClasses: "text-slate-500 group-hover:text-cyan-400",
  },
  {
    id: "tasks",
    label: "Tasks",
    icon: ListTodo,
    activeClasses: "bg-orange-500/15 text-orange-400",
    inactiveClasses:
      "text-slate-500 hover:bg-orange-500/10 hover:text-orange-400",
    iconActiveClasses: "text-orange-400",
    iconInactiveClasses: "text-slate-500 group-hover:text-orange-400",
  },
  {
    id: "tests",
    label: "Tests",
    icon: FlaskConical,
    activeClasses: "bg-phosphor-500/15 text-phosphor-400",
    inactiveClasses:
      "text-slate-500 hover:bg-phosphor-500/10 hover:text-phosphor-400",
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
      "text-slate-500 hover:bg-amber-500/10 hover:text-amber-400",
    iconActiveClasses: "text-amber-400",
    iconInactiveClasses: "text-slate-500 group-hover:text-amber-400",
    isRoute: true,
  },
  {
    id: "evidence",
    label: "Evidence",
    icon: Camera,
    activeClasses: "bg-pink-500/15 text-pink-400",
    inactiveClasses: "text-slate-500 hover:bg-pink-500/10 hover:text-pink-400",
    iconActiveClasses: "text-pink-400",
    iconInactiveClasses: "text-slate-500 group-hover:text-pink-400",
  },
  {
    id: "explorer",
    label: "Explorer",
    icon: Compass,
    activeClasses: "bg-teal-500/15 text-teal-400",
    inactiveClasses: "text-slate-500 hover:bg-teal-500/10 hover:text-teal-400",
    iconActiveClasses: "text-teal-400",
    iconInactiveClasses: "text-slate-500 group-hover:text-teal-400",
  },
  {
    id: "git",
    label: "Git",
    icon: GitBranch,
    activeClasses: "bg-violet-500/15 text-violet-400",
    inactiveClasses:
      "text-slate-500 hover:bg-violet-500/10 hover:text-violet-400",
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
      "text-slate-500 hover:bg-indigo-500/10 hover:text-indigo-400",
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
      "text-slate-500 hover:bg-slate-500/10 hover:text-slate-300",
    iconActiveClasses: "text-slate-300",
    iconInactiveClasses: "text-slate-500 group-hover:text-slate-300",
    isSettings: true,
  },
];

interface NavPillsProps {
  projectId: string;
  currentTab?: TabId;
  className?: string;
}

export function NavPills({ projectId, currentTab, className }: NavPillsProps) {
  const searchParams = useSearchParams();

  // Get current tab from URL if not provided
  const activeTab =
    currentTab || (searchParams.get("tab") as TabId) || "roundtable";

  return (
    <nav
      className={clsx(
        "flex items-center gap-1 overflow-x-auto scrollbar-hide",
        "max-w-[calc(100vw-500px)] lg:max-w-none",
        className,
      )}
    >
      {tabs.map((tab) => {
        const isActive = activeTab === tab.id;
        const Icon = tab.icon;

        // Settings and some tabs link to different pages
        const href = tab.isSettings
          ? `/projects/${projectId}/settings`
          : tab.isRoute
            ? `/projects/${projectId}/${tab.id}`
            : `/projects/${projectId}?tab=${tab.id}`;

        return (
          <Link
            key={tab.id}
            href={href}
            className={clsx(
              "group flex items-center px-3 py-2 rounded-lg text-sm font-medium transition-all duration-300 ease-out flex-shrink-0",
              isActive ? tab.activeClasses : tab.inactiveClasses,
            )}
            title={tab.label}
          >
            <Icon
              className={clsx(
                "w-4 h-4 flex-shrink-0 transition-colors duration-200",
                isActive ? tab.iconActiveClasses : tab.iconInactiveClasses,
              )}
            />
            <span
              className={clsx(
                "overflow-hidden transition-all duration-300 ease-out whitespace-nowrap",
                isActive
                  ? "max-w-24 ml-2 opacity-100"
                  : "max-w-0 ml-0 opacity-0 group-hover:max-w-24 group-hover:ml-2 group-hover:opacity-100",
              )}
            >
              {tab.label}
            </span>
          </Link>
        );
      })}
    </nav>
  );
}

export type { TabId };
