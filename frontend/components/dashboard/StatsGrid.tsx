"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  FolderKanban,
  Target,
  ListTodo,
  AlertCircle,
} from "lucide-react";
import { fetchProjects, fetchProjectHealth } from "@/lib/api";

interface StatCardProps {
  label: string;
  value: number | string;
  subtext?: string;
  icon: React.ElementType;
  gradientFrom: string;
  gradientTo: string;
  href: string;
}

function StatCard({ label, value, subtext, icon: Icon, gradientFrom, gradientTo, href }: StatCardProps) {
  return (
    <Link
      href={href}
      className="relative overflow-hidden rounded-xl p-5 transition-all duration-300 hover:translate-y-[-2px] hover:shadow-lg group"
      style={{
        background: `linear-gradient(135deg, ${gradientFrom} 0%, ${gradientTo} 100%)`,
      }}
    >
      {/* Background pattern */}
      <div className="absolute inset-0 opacity-10">
        <div className="absolute -right-4 -top-4 w-24 h-24 rounded-full bg-white/20" />
        <div className="absolute -right-8 -bottom-8 w-32 h-32 rounded-full bg-white/10" />
      </div>

      <div className="relative flex items-start justify-between">
        <div>
          <div className="p-2 rounded-lg bg-white/20 w-fit mb-3">
            <Icon className="w-5 h-5 text-white" />
          </div>
          <p className="display text-3xl font-bold text-white tabular-nums">
            {value}
          </p>
          <p className="text-sm text-white/80 mt-1">{label}</p>
          {subtext && (
            <p className="text-xs text-white/60 mt-0.5">{subtext}</p>
          )}
        </div>
      </div>
    </Link>
  );
}

export function StatsGrid() {
  const { data: projects } = useQuery({
    queryKey: ["projects"],
    queryFn: fetchProjects,
  });

  // Get health stats
  const projectCount = projects?.length ?? 0;
  const healthyCount = projects?.filter(p => p.health_status === "healthy").length ?? 0;

  const stats: StatCardProps[] = [
    {
      label: "Projects",
      value: projectCount,
      subtext: `${healthyCount} healthy`,
      icon: FolderKanban,
      gradientFrom: "rgba(0, 200, 83, 0.9)",
      gradientTo: "rgba(0, 150, 62, 0.9)",
      href: "/projects",
    },
    {
      label: "Features",
      value: 0,
      subtext: "In progress",
      icon: Target,
      gradientFrom: "rgba(59, 130, 246, 0.9)",
      gradientTo: "rgba(37, 99, 235, 0.9)",
      href: "/features",
    },
    {
      label: "Tasks",
      value: 0,
      subtext: "Active",
      icon: ListTodo,
      gradientFrom: "rgba(139, 92, 246, 0.9)",
      gradientTo: "rgba(109, 40, 217, 0.9)",
      href: "/projects",
    },
    {
      label: "Blocked",
      value: 0,
      subtext: "Needs attention",
      icon: AlertCircle,
      gradientFrom: "rgba(251, 146, 60, 0.9)",
      gradientTo: "rgba(234, 88, 12, 0.9)",
      href: "/projects",
    },
  ];

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {stats.map((stat) => (
        <StatCard key={stat.label} {...stat} />
      ))}
    </div>
  );
}
