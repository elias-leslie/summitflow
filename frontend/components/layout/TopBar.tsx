"use client";

import Link from "next/link";
import Image from "next/image";
import { useRouter, usePathname } from "next/navigation";
import { Search, Settings, LayoutGrid } from "lucide-react";
import { useState, useEffect, useRef } from "react";
import { NotificationBell } from "@/components/notifications";

const SUMMITFLOW_PROJECT_ID = "summitflow";

const LOGO_WIDE_WIDTH = 200;
const LOGO_HEIGHT = 56;
const LOGO_SQUARE_SIZE = 56;
const LOGO_CONTAINER_WIDTH = 220;
const LOGO_SHIFT_COLLAPSED = 72;

export function TopBar() {
  const router = useRouter();
  const pathname = usePathname();
  const [isSearchFocused, setIsSearchFocused] = useState(false);

  const [isExpanded, setIsExpanded] = useState(false);
  const collapseTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const isOnDashboard = pathname === "/";

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
      <header className="h-16 flex-shrink-0 bg-slate-900 border-b border-slate-700/50 flex items-center px-6 gap-4">
        {/* Logo Container */}
        <button
          onClick={handleLogoClick}
          className="flex items-center flex-shrink-0 group focus:outline-none"
          aria-label="Go to dashboard"
          style={{
            width: LOGO_CONTAINER_WIDTH,
            height: LOGO_HEIGHT,
          }}
        >
          <div
            className="flex items-center"
            style={{
              justifyContent: isExpanded ? "center" : "flex-start",
              width: "100%",
              transition: "justify-content 0.3s ease-out",
            }}
          >
            <div
              className="relative flex-shrink-0 overflow-hidden"
              style={{
                width: isExpanded ? LOGO_WIDE_WIDTH : LOGO_SQUARE_SIZE,
                height: LOGO_HEIGHT,
                transition: "width 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94)",
              }}
            >
              <Image
                src="/logo-wide-v4.svg"
                alt="SummitFlow"
                width={LOGO_WIDE_WIDTH}
                height={LOGO_HEIGHT}
                className="h-full"
                style={{
                  width: LOGO_WIDE_WIDTH,
                  minWidth: LOGO_WIDE_WIDTH,
                  transform: isExpanded
                    ? "translateX(0)"
                    : `translateX(-${LOGO_SHIFT_COLLAPSED}px)`,
                  transition:
                    "transform 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94)",
                  filter: isExpanded
                    ? "drop-shadow(0 0 20px rgba(255,102,0,0.4)) drop-shadow(0 0 40px rgba(255,0,102,0.2))"
                    : "drop-shadow(0 0 12px rgba(255,102,0,0.3)) drop-shadow(0 0 24px rgba(255,0,102,0.15))",
                }}
                priority
              />
            </div>

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
                  transform: isExpanded ? "translateX(-20px)" : "translateX(0)",
                  transition:
                    "transform 0.5s cubic-bezier(0.25, 0.46, 0.45, 0.94)",
                }}
              >
                SummitFlow
              </span>
            </div>
          </div>

          <div
            className="absolute inset-0 pointer-events-none rounded-lg opacity-0 group-hover:opacity-100"
            style={{
              boxShadow:
                "0 0 30px rgba(255,102,0,0.08), 0 0 60px rgba(255,0,102,0.05)",
              transition: "opacity 0.3s ease-out",
            }}
          />
        </button>

        {/* Dashboard link (when not on dashboard) */}
        {!isOnDashboard && (
          <>
            <div className="w-px h-8 bg-gradient-to-b from-transparent via-slate-600 to-transparent flex-shrink-0" />
            <Link
              href="/"
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-slate-400 hover:bg-outrun-500/10 hover:text-outrun-400 transition-all duration-200"
              title="Back to Dashboard"
            >
              <LayoutGrid className="w-4 h-4" />
              <span className="text-sm font-medium">Dashboard</span>
            </Link>
          </>
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
              placeholder="Search..."
              className="input pl-12 pr-4 py-2 text-sm bg-slate-800/80 border-slate-700 w-56 focus:w-72 focus:border-outrun-500/50 transition-all duration-300"
              onFocus={() => setIsSearchFocused(true)}
              onBlur={() => setIsSearchFocused(false)}
            />
          </div>
        </div>

        {/* Right side actions - minimal */}
        <div className="flex items-center gap-1 flex-shrink-0">
          {/* Settings */}
          <Link
            href="/settings"
            className="p-2.5 rounded-lg text-slate-400 hover:bg-outrun-500/10 hover:text-outrun-400 transition-all duration-200"
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
    </>
  );
}
