"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  MessageCircle,
  Target,
  Flag,
  ListChecks,
  Kanban,
  ListTodo,
  Camera,
  Compass,
} from "lucide-react";
import clsx from "clsx";

type TabId = "roundtable" | "vision" | "goals" | "features" | "kanban" | "tasks" | "evidence" | "explorer";

interface TabConfig {
  id: TabId;
  label: string;
  icon: React.ElementType;
}

const tabs: TabConfig[] = [
  { id: "roundtable", label: "Roundtable", icon: MessageCircle },
  { id: "vision", label: "Vision", icon: Target },
  { id: "goals", label: "Goals", icon: Flag },
  { id: "features", label: "Features", icon: ListChecks },
  { id: "kanban", label: "Kanban", icon: Kanban },
  { id: "tasks", label: "Tasks", icon: ListTodo },
  { id: "evidence", label: "Evidence", icon: Camera },
  { id: "explorer", label: "Explorer", icon: Compass },
];

interface NavPillsProps {
  projectId: string;
  currentTab?: TabId;
  className?: string;
}

export function NavPills({ projectId, currentTab, className }: NavPillsProps) {
  const searchParams = useSearchParams();

  // Get current tab from URL if not provided
  const activeTab = currentTab || (searchParams.get("tab") as TabId) || "roundtable";

  return (
    <nav className={clsx("flex items-center gap-1", className)}>
      {tabs.map((tab) => {
        const isActive = activeTab === tab.id;
        const Icon = tab.icon;

        return (
          <Link
            key={tab.id}
            href={`/projects/${projectId}?tab=${tab.id}`}
            className={clsx(
              "flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-all duration-200",
              isActive
                ? "bg-phosphor-500/12 text-phosphor-400"
                : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
            )}
          >
            <Icon className="w-4 h-4" />
            <span className="hidden lg:inline">{tab.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}

export type { TabId };
