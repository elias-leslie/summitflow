"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  FolderKanban,
  Map,
  FileCode2,
  Target,
  Camera,
  Settings,
  ChevronRight,
} from "lucide-react";
import clsx from "clsx";

const navigation = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "Projects", href: "/projects", icon: FolderKanban },
  { name: "Features", href: "/features", icon: Target },
  { name: "Sitemap", href: "/sitemap", icon: Map },
  { name: "Files", href: "/files", icon: FileCode2 },
  { name: "Evidence", href: "/evidence", icon: Camera },
];

const bottomNav = [
  { name: "Settings", href: "/settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

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

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        <div className="mb-3 px-2">
          <span className="text-[10px] mono uppercase tracking-widest text-slate-500">
            Navigation
          </span>
        </div>
        {navigation.map((item) => {
          const isActive = pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(item.href));
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
        {bottomNav.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.name}
              href={item.href}
              className={clsx(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200",
                isActive
                  ? "bg-slate-800 text-slate-200"
                  : "text-slate-500 hover:text-slate-300 hover:bg-slate-800/50"
              )}
            >
              <item.icon className="w-4 h-4" />
              <span>{item.name}</span>
            </Link>
          );
        })}
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
