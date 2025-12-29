"use client";

import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { Search, Terminal, Camera, Settings, Info, Brain, ExternalLink } from "lucide-react";
import { useState, useEffect, useRef, Suspense } from "react";
import { EvidenceCaptureModal } from "@/components/evidence";
import { NotificationBell } from "@/components/notifications";
import { ProjectSelector, useSelectedProject } from "./ProjectSelector";
import { NavPills } from "./NavPills";

// SummitFlow captures evidence for itself (dogfooding)
const SUMMITFLOW_PROJECT_ID = "summitflow";

// Logo dimensions
const LOGO_WIDE_WIDTH = 200;
const LOGO_HEIGHT = 56;
const LOGO_SQUARE_SIZE = 56;

// Fixed container width - must fit: expanded logo centered, or collapsed logo + text
const LOGO_CONTAINER_WIDTH = 220;

// In the 200px wide logo, the sun is at x=100 (center)
// To show a 56px square centered on the sun when collapsed:
// Shift left by: 100 - (56/2) = 72px
const LOGO_SHIFT_COLLAPSED = 72;

export function TopBar() {
  const router = useRouter();
  const [isSearchFocused, setIsSearchFocused] = useState(false);
  const [captureModalOpen, setCaptureModalOpen] = useState(false);
  const [currentUrl, setCurrentUrl] = useState("");
  const selectedProjectId = useSelectedProject();

  // Logo animation state
  const [isExpanded, setIsExpanded] = useState(false);
  const collapseTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Get current URL on client side
  useEffect(() => {
    setCurrentUrl(window.location.href);
  }, []);

  // Auto-collapse after 3.5 seconds
  useEffect(() => {
    if (isExpanded) {
      collapseTimeoutRef.current = setTimeout(() => {
        setIsExpanded(false);
      }, 3500);
    }

    return () => {
      if (collapseTimeoutRef.current) {
        clearTimeout(collapseTimeoutRef.current);
      }
    };
  }, [isExpanded]);

  const handleLogoClick = () => {
    router.push("/");
    if (!isExpanded) {
      setIsExpanded(true);
    }
  };

  return (
    <>
      <header className="h-20 flex-shrink-0 bg-slate-900 border-b border-slate-700/50 flex items-center px-6 gap-6">
        {/* Logo Container - FIXED WIDTH to prevent layout shift */}
        <button
          onClick={handleLogoClick}
          className="flex items-center flex-shrink-0 group focus:outline-none"
          aria-label="Go to dashboard"
          style={{
            width: LOGO_CONTAINER_WIDTH,
            height: LOGO_HEIGHT,
          }}
        >
          {/* Inner flex container - centers content when expanded */}
          <div
            className="flex items-center"
            style={{
              // When expanded: center the logo within the container
              // When collapsed: align left (logo + text side by side)
              justifyContent: isExpanded ? "center" : "flex-start",
              width: "100%",
              transition: "justify-content 0.3s ease-out",
            }}
          >
            {/* Logo wrapper - width animates between square and wide */}
            <div
              className="relative flex-shrink-0 overflow-hidden"
              style={{
                width: isExpanded ? LOGO_WIDE_WIDTH : LOGO_SQUARE_SIZE,
                height: LOGO_HEIGHT,
                transition: "width 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94)",
              }}
            >
              {/* Wide logo - shifts to show center when collapsed */}
              <Image
                src="/logo-wide-v4.svg"
                alt="SummitFlow"
                width={LOGO_WIDE_WIDTH}
                height={LOGO_HEIGHT}
                className="h-full"
                style={{
                  width: LOGO_WIDE_WIDTH,
                  minWidth: LOGO_WIDE_WIDTH,
                  // Shift left when collapsed to center the sun in the 56px window
                  transform: isExpanded
                    ? "translateX(0)"
                    : `translateX(-${LOGO_SHIFT_COLLAPSED}px)`,
                  transition: "transform 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94)",
                  filter: isExpanded
                    ? "drop-shadow(0 0 20px rgba(255,102,0,0.4)) drop-shadow(0 0 40px rgba(255,0,102,0.2))"
                    : "drop-shadow(0 0 12px rgba(255,102,0,0.3)) drop-shadow(0 0 24px rgba(255,0,102,0.15))",
                }}
                priority
              />
            </div>

            {/* Text - collapses via max-width, NO opacity fade */}
            <div
              className="overflow-hidden flex-shrink-0"
              style={{
                maxWidth: isExpanded ? 0 : 140,
                marginLeft: isExpanded ? 0 : 12,
                transition:
                  "max-width 0.6s cubic-bezier(0.25, 0.46, 0.45, 0.94), margin-left 0.6s cubic-bezier(0.25, 0.46, 0.45, 0.94)",
              }}
            >
              <span
                className="font-semibold text-xl tracking-tight whitespace-nowrap block"
                style={{
                  background:
                    "linear-gradient(90deg, #fff200 0%, #ff6600 50%, #ff0066 100%)",
                  WebkitBackgroundClip: "text",
                  WebkitTextFillColor: "transparent",
                  backgroundClip: "text",
                  // Slide left as it collapses
                  transform: isExpanded ? "translateX(-20px)" : "translateX(0)",
                  transition: "transform 0.5s cubic-bezier(0.25, 0.46, 0.45, 0.94)",
                }}
              >
                SummitFlow
              </span>
            </div>
          </div>

          {/* Subtle hover glow */}
          <div
            className="absolute inset-0 pointer-events-none rounded-lg opacity-0 group-hover:opacity-100"
            style={{
              boxShadow:
                "0 0 30px rgba(255,102,0,0.08), 0 0 60px rgba(255,0,102,0.05)",
              transition: "opacity 0.3s ease-out",
            }}
          />
        </button>

        {/* Vertical divider */}
        <div className="w-px h-10 bg-gradient-to-b from-transparent via-slate-600 to-transparent flex-shrink-0" />

        {/* Project Selector - wrapped in Suspense for useSearchParams */}
        <div className="relative z-20 flex-shrink-0">
          <Suspense fallback={<div className="w-40 h-9 bg-slate-800 rounded-lg animate-pulse" />}>
            <ProjectSelector />
          </Suspense>
        </div>

        {/* Nav Pills (only when project selected) - wrapped in Suspense for useSearchParams */}
        {selectedProjectId && (
          <Suspense fallback={<div className="w-64 h-9 bg-slate-800/50 rounded-lg animate-pulse" />}>
            <NavPills projectId={selectedProjectId} className="flex-shrink-0 z-10" />
          </Suspense>
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
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none" />
            <input
              type="text"
              className="input pl-12 pr-4 py-2.5 text-sm bg-slate-800/80 border-slate-700 w-64 focus:w-80 focus:border-outrun-500/50 transition-all duration-300"
              onFocus={() => setIsSearchFocused(true)}
              onBlur={() => setIsSearchFocused(false)}
            />
          </div>
        </div>

        {/* Right side actions */}
        <div className="flex items-center gap-2 flex-shrink-0">
          {/* About - first for discoverability */}
          <Link
            href="/about"
            className="p-3 rounded-lg text-slate-400 hover:bg-outrun-500/10 hover:text-outrun-400 transition-all duration-200"
            title="About SummitFlow"
          >
            <Info className="w-5 h-5" />
          </Link>

          {/* Terminal - external link */}
          <a
            href={(() => {
              const params = new URLSearchParams();
              if (selectedProjectId) params.set("project", selectedProjectId);
              const query = params.toString();
              return `https://terminal.summitflow.dev${query ? `?${query}` : ""}`;
            })()}
            target="_blank"
            rel="noopener noreferrer"
            className="p-3 rounded-lg text-slate-400 hover:bg-outrun-500/10 hover:text-outrun-400 transition-all duration-200 flex items-center gap-1"
            title="Open Terminal (new tab)"
          >
            <Terminal className="w-5 h-5" />
            <ExternalLink className="w-3 h-3" />
          </a>

          {/* Memory - link to global Memory page */}
          <Link
            href="/memory"
            className="p-3 rounded-lg text-slate-400 hover:bg-outrun-500/10 hover:text-outrun-400 transition-all duration-200"
            title="Memory"
          >
            <Brain className="w-5 h-5" />
          </Link>

          {/* Capture Evidence */}
          <button
            onClick={() => {
              setCurrentUrl(window.location.href);
              setCaptureModalOpen(true);
            }}
            className="p-3 rounded-lg text-slate-400 hover:bg-outrun-500/10 hover:text-outrun-400 transition-all duration-200"
            title="Capture Evidence (Screenshot)"
          >
            <Camera className="w-5 h-5" />
          </button>

          {/* Settings */}
          <Link
            href="/settings"
            className="p-3 rounded-lg text-slate-400 hover:bg-outrun-500/10 hover:text-outrun-400 transition-all duration-200"
            title="Settings"
          >
            <Settings className="w-5 h-5" />
          </Link>

          {/* Notifications */}
          <NotificationBell projectId={SUMMITFLOW_PROJECT_ID} />
        </div>
      </header>

      {/* Chrome accent line under header */}
      <div className="chrome-line" />

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
