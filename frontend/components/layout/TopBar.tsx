"use client";

import Link from "next/link";
import { Search, Terminal, Camera, Settings } from "lucide-react";
import { useState, useEffect } from "react";
import { EvidenceCaptureModal } from "@/components/evidence";
import { NotificationBell } from "@/components/notifications";
import { useTerminalState } from "@/lib/hooks/use-terminal-state";
import { ProjectSelector, useSelectedProject } from "./ProjectSelector";
import { NavPills } from "./NavPills";

// SummitFlow captures evidence for itself (dogfooding)
const SUMMITFLOW_PROJECT_ID = "summitflow";

export function TopBar() {
  const [isSearchFocused, setIsSearchFocused] = useState(false);
  const [captureModalOpen, setCaptureModalOpen] = useState(false);
  const [currentUrl, setCurrentUrl] = useState("");
  const { isOpen, toggle } = useTerminalState();
  const selectedProjectId = useSelectedProject();

  // Get current URL on client side
  useEffect(() => {
    setCurrentUrl(window.location.href);
  }, []);

  return (
    <>
      <header className="h-14 flex-shrink-0 bg-slate-900 border-b border-slate-800 flex items-center px-4 gap-4">
        {/* Logo */}
        <Link href="/" className="flex items-center gap-2 group flex-shrink-0">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-phosphor-500 to-phosphor-600 flex items-center justify-center glow-phosphor-sm">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              className="w-4 h-4 text-white"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
          </div>
          <span className="display font-semibold text-white tracking-tight hidden sm:inline">
            SummitFlow
          </span>
        </Link>

        {/* Vertical divider */}
        <div className="w-px h-6 bg-slate-700 flex-shrink-0" />

        {/* Project Selector */}
        <div className="relative z-20 flex-shrink-0">
          <ProjectSelector />
        </div>

        {/* Nav Pills (only when project selected) */}
        {selectedProjectId && (
          <NavPills projectId={selectedProjectId} className="flex-shrink-0 z-10" />
        )}

        {/* Spacer */}
        <div className="flex-1" />

        {/* Search */}
        <div className="hidden md:block">
          <div
            className={`relative transition-all duration-300 ${
              isSearchFocused ? "scale-[1.02]" : ""
            }`}
          >
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none" />
            <input
              type="text"
              placeholder="Search projects, features..."
              className="input pl-11 pr-4 py-2 text-sm bg-slate-800 border-slate-700 w-64 focus:w-80 transition-all duration-300"
              onFocus={() => setIsSearchFocused(true)}
              onBlur={() => setIsSearchFocused(false)}
            />
          </div>
        </div>

        {/* Right side actions */}
        <div className="flex items-center gap-1 flex-shrink-0">
          {/* Terminal toggle */}
          <button
            onClick={toggle}
            className={`btn-ghost p-2 rounded-lg transition-colors ${
              isOpen
                ? "bg-phosphor-500/20 text-phosphor-400"
                : "hover:bg-phosphor-500/10 hover:text-phosphor-400"
            }`}
            title={isOpen ? "Close Terminal" : "Open Terminal"}
          >
            <Terminal className="w-4 h-4" />
          </button>

          {/* Capture Evidence */}
          <button
            onClick={() => {
              setCurrentUrl(window.location.href);
              setCaptureModalOpen(true);
            }}
            className="btn-ghost p-2 rounded-lg hover:bg-phosphor-500/10 hover:text-phosphor-400 transition-colors"
            title="Capture Evidence (Screenshot)"
          >
            <Camera className="w-4 h-4" />
          </button>

          {/* Settings */}
          <Link
            href="/settings"
            className="btn-ghost p-2 rounded-lg hover:bg-phosphor-500/10 hover:text-phosphor-400 transition-colors"
            title="Settings"
          >
            <Settings className="w-4 h-4" />
          </Link>

          {/* Notifications */}
          <NotificationBell projectId={SUMMITFLOW_PROJECT_ID} />
        </div>
      </header>

      {/* Evidence Capture Modal */}
      <EvidenceCaptureModal
        open={captureModalOpen}
        onClose={() => setCaptureModalOpen(false)}
        projectId={SUMMITFLOW_PROJECT_ID}
        pageUrl={currentUrl}
        onCaptured={() => {
          setCaptureModalOpen(false);
        }}
      />
    </>
  );
}
