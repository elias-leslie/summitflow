"use client";

import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { Search, Terminal, Camera, Settings } from "lucide-react";
import { useState, useEffect, useRef } from "react";
import { EvidenceCaptureModal } from "@/components/evidence";
import { NotificationBell } from "@/components/notifications";
import { useTerminalState } from "@/lib/hooks/use-terminal-state";
import { ProjectSelector, useSelectedProject } from "./ProjectSelector";
import { NavPills } from "./NavPills";

// SummitFlow captures evidence for itself (dogfooding)
const SUMMITFLOW_PROJECT_ID = "summitflow";

// Logo dimensions
const LOGO_WIDE_WIDTH = 200;
const LOGO_SQUARE_SIZE = 56;
const LOGO_HEIGHT = 56;

// Cinematic zoom settings - the wide logo zooms from this scale to 1
// Higher = more zoomed in initially (showing just the sun/center)
const ZOOM_SCALE = 3.2;

export function TopBar() {
  const router = useRouter();
  const [isSearchFocused, setIsSearchFocused] = useState(false);
  const [captureModalOpen, setCaptureModalOpen] = useState(false);
  const [currentUrl, setCurrentUrl] = useState("");
  const { isOpen, toggle } = useTerminalState();
  const selectedProjectId = useSelectedProject();

  // Logo state - starts with square + text, transitions to wide panoramic
  const [isWideView, setIsWideView] = useState(false);
  const collapseTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Get current URL on client side
  useEffect(() => {
    setCurrentUrl(window.location.href);
  }, []);

  // Auto-return to default (logo + text) after 3.5 seconds
  useEffect(() => {
    if (isWideView) {
      collapseTimeoutRef.current = setTimeout(() => {
        setIsWideView(false);
      }, 3500);
    }

    return () => {
      if (collapseTimeoutRef.current) {
        clearTimeout(collapseTimeoutRef.current);
      }
    };
  }, [isWideView]);

  const handleLogoClick = () => {
    // Always navigate to dashboard
    router.push("/");

    // Trigger the cinematic wide view
    if (!isWideView) {
      setIsWideView(true);
    }
  };

  return (
    <>
      <header className="h-20 flex-shrink-0 bg-slate-900 border-b border-slate-700/50 flex items-center px-6 gap-6">
        {/* Logo - Cinematic "driving into sunset" animation */}
        <button
          onClick={handleLogoClick}
          className="flex items-center flex-shrink-0 group focus:outline-none relative"
          aria-label="Go to dashboard"
          style={{ height: LOGO_HEIGHT }}
        >
          {/* Logo container - animates width for the reveal */}
          <div
            className="relative overflow-hidden"
            style={{
              width: isWideView ? LOGO_WIDE_WIDTH : LOGO_SQUARE_SIZE,
              height: LOGO_HEIGHT,
              transition: 'width 1.2s cubic-bezier(0.25, 0.46, 0.45, 0.94)',
            }}
          >
            {/* Wide panoramic logo - the "full scene" that zooms out */}
            <div
              className="absolute inset-0"
              style={{
                // Transform origin set to where the sun is in the wide logo (~55% from left)
                transformOrigin: '55% 50%',
                // Start zoomed in, animate to full view
                transform: isWideView ? 'scale(1)' : `scale(${ZOOM_SCALE})`,
                opacity: isWideView ? 1 : 0,
                transition: `transform 1.2s cubic-bezier(0.25, 0.46, 0.45, 0.94), opacity 0.4s ease-out ${isWideView ? '0s' : '0.3s'}`,
                filter: isWideView
                  ? 'drop-shadow(0 0 20px rgba(255,102,0,0.4)) drop-shadow(0 0 40px rgba(255,0,102,0.2))'
                  : 'drop-shadow(0 0 10px rgba(255,102,0,0.2))',
              }}
            >
              <Image
                src="/logo-wide.svg"
                alt="SummitFlow"
                width={LOGO_WIDE_WIDTH}
                height={LOGO_HEIGHT}
                className="w-full h-full object-cover"
                priority
              />
            </div>

            {/* Square focused logo - fades out as we "drive into" the scene */}
            <div
              className="absolute inset-0 flex items-center justify-center"
              style={{
                opacity: isWideView ? 0 : 1,
                transform: isWideView ? 'scale(0.8)' : 'scale(1)',
                transition: `opacity 0.5s ease-out, transform 0.5s ease-out`,
                filter: 'drop-shadow(0 0 20px rgba(255,102,0,0.4)) drop-shadow(0 0 40px rgba(255,0,102,0.25))',
              }}
            >
              <Image
                src="/logo.svg"
                alt="SummitFlow"
                width={LOGO_SQUARE_SIZE}
                height={LOGO_SQUARE_SIZE}
                className="w-full h-full object-contain"
              />
            </div>

            {/* Cinematic light flare during transition */}
            <div
              className="absolute inset-0 pointer-events-none"
              style={{
                background: 'radial-gradient(ellipse at 55% 40%, rgba(255,200,100,0.4) 0%, transparent 50%)',
                opacity: isWideView ? 0 : 0,
                animation: isWideView ? 'cinematicFlare 1.2s ease-out forwards' : 'none',
              }}
            />

            {/* Horizon glow that intensifies during the "drive" */}
            <div
              className="absolute inset-0 pointer-events-none"
              style={{
                background: 'linear-gradient(to top, rgba(255,0,102,0.15) 0%, transparent 40%)',
                opacity: isWideView ? 1 : 0,
                transition: 'opacity 0.8s ease-out 0.3s',
              }}
            />
          </div>

          {/* Text container - slides away as we enter the wide view */}
          <div
            className="overflow-hidden"
            style={{
              maxWidth: isWideView ? '0px' : '200px',
              marginLeft: isWideView ? '0px' : '16px',
              opacity: isWideView ? 0 : 1,
              transition: `max-width 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94), margin-left 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94), opacity 0.4s ease-out`,
            }}
          >
            <span
              className="display font-semibold text-xl tracking-tight whitespace-nowrap block"
              style={{
                background: 'linear-gradient(90deg, #fff200 0%, #ff6600 50%, #ff0066 100%)',
                WebkitBackgroundClip: 'text',
                WebkitTextFillColor: 'transparent',
                backgroundClip: 'text',
                textShadow: '0 0 40px rgba(255,102,0,0.5), 0 0 80px rgba(255,0,102,0.3)',
                transform: isWideView ? 'translateX(-40px) scale(0.9)' : 'translateX(0) scale(1)',
                transition: 'transform 0.6s cubic-bezier(0.25, 0.46, 0.45, 0.94)',
              }}
            >
              SummitFlow
            </span>
          </div>

          {/* Subtle hover glow */}
          <div
            className="absolute inset-0 pointer-events-none rounded opacity-0 group-hover:opacity-100"
            style={{
              boxShadow: '0 0 30px rgba(255,102,0,0.08), 0 0 60px rgba(255,0,102,0.05)',
              transition: 'opacity 0.3s ease-out',
            }}
          />
        </button>

        {/* Vertical divider */}
        <div className="w-px h-10 bg-gradient-to-b from-transparent via-slate-600 to-transparent flex-shrink-0" />

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
            className={`relative transition-all duration-300 ${isSearchFocused ? "scale-[1.02]" : ""
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
          {/* Terminal toggle */}
          <button
            onClick={toggle}
            className={`p-3 rounded-lg transition-all duration-200 ${isOpen
                ? "bg-outrun-500/20 text-outrun-400 shadow-outrun-sm"
                : "text-slate-400 hover:bg-outrun-500/10 hover:text-outrun-400"
              }`}
            title={isOpen ? "Close Terminal" : "Open Terminal"}
          >
            <Terminal className="w-5 h-5" />
          </button>

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

      {/* Keyframe animations for cinematic effects */}
      <style jsx global>{`
        @keyframes cinematicFlare {
          0% {
            opacity: 0;
            transform: scale(0.8);
          }
          30% {
            opacity: 0.6;
            transform: scale(1.1);
          }
          100% {
            opacity: 0;
            transform: scale(1.5);
          }
        }
      `}</style>
    </>
  );
}
