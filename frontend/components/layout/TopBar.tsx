"use client";

import { Search, Bell, RefreshCw, Terminal, Camera } from "lucide-react";
import { useState, useEffect } from "react";
import { EvidenceCaptureModal } from "@/components/evidence";

// SummitFlow captures evidence for itself (dogfooding)
const SUMMITFLOW_PROJECT_ID = "summitflow";

export function TopBar() {
  const [isSearchFocused, setIsSearchFocused] = useState(false);
  const [captureModalOpen, setCaptureModalOpen] = useState(false);
  const [currentUrl, setCurrentUrl] = useState("");

  // Get current URL on client side
  useEffect(() => {
    setCurrentUrl(window.location.href);
  }, []);

  return (
    <>
      <header className="h-14 flex-shrink-0 bg-slate-900/80 backdrop-blur-sm border-b border-slate-800 flex items-center justify-between px-6">
        {/* Search */}
        <div className="flex-1 max-w-xl">
          <div
            className={`relative transition-all duration-300 ${
              isSearchFocused ? "scale-[1.02]" : ""
            }`}
          >
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              type="text"
              placeholder="Search projects, features, files..."
              className="input pl-10 pr-16 py-2 text-sm bg-slate-850"
              onFocus={() => setIsSearchFocused(true)}
              onBlur={() => setIsSearchFocused(false)}
            />
            <kbd className="absolute right-3 top-1/2 -translate-y-1/2 px-1.5 py-0.5 text-[10px] mono text-slate-500 bg-slate-800 rounded border border-slate-700">
              ⌘K
            </kbd>
          </div>
        </div>

        {/* Right side actions */}
        <div className="flex items-center gap-2 ml-6">
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

          {/* Terminal shortcut */}
          <button
            className="btn-ghost p-2 rounded-lg"
            title="Open Terminal"
          >
            <Terminal className="w-4 h-4" />
          </button>

          {/* Refresh */}
          <button
            className="btn-ghost p-2 rounded-lg"
            title="Refresh Data"
          >
            <RefreshCw className="w-4 h-4" />
          </button>

          {/* Notifications */}
          <button
            className="btn-ghost p-2 rounded-lg relative"
            title="Notifications"
          >
            <Bell className="w-4 h-4" />
            <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-phosphor-500 rounded-full" />
          </button>

          {/* Separator */}
          <div className="w-px h-6 bg-slate-700 mx-2" />

          {/* Current time - terminal style */}
          <div className="mono text-xs text-slate-500 tabular-nums">
            <CurrentTime />
          </div>
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

function CurrentTime() {
  const [time, setTime] = useState<string | null>(null);

  useEffect(() => {
    // Set initial time on client only
    setTime(new Date().toLocaleTimeString("en-US", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }));

    // Update time every second
    const interval = setInterval(() => {
      setTime(new Date().toLocaleTimeString("en-US", {
        hour12: false,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }));
    }, 1000);

    return () => clearInterval(interval);
  }, []);

  return (
    <span className="flex items-center gap-1">
      <span className="text-phosphor-500">▸</span>
      <span suppressHydrationWarning>{time ?? "--:--:--"}</span>
    </span>
  );
}
