"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "motion/react";
import {
  X,
  Camera,
  RefreshCw,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Globe,
  AlertTriangle,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EvidenceCaptureModal } from "./EvidenceCaptureModal";

interface EvidenceBrowserProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  projectName: string;
  initialUrl: string;
}

interface CaptureResult {
  success: boolean;
  version?: number;
  feature_id?: string;
  criterion_id?: string;
  error?: string;
}

export function EvidenceBrowser({
  open,
  onOpenChange,
  projectId,
  projectName,
  initialUrl,
}: EvidenceBrowserProps) {
  const [currentUrl, setCurrentUrl] = useState(initialUrl);
  const [inputUrl, setInputUrl] = useState(initialUrl);
  const [isLoading, setIsLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [captureModalOpen, setCaptureModalOpen] = useState(false);
  const [history, setHistory] = useState<string[]>([initialUrl]);
  const [historyIndex, setHistoryIndex] = useState(0);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // Reset state when opened
  useEffect(() => {
    if (open) {
      setCurrentUrl(initialUrl);
      setInputUrl(initialUrl);
      setHistory([initialUrl]);
      setHistoryIndex(0);
      setLoadError(null);
    }
  }, [open, initialUrl]);

  // Handle navigation
  const navigate = useCallback((url: string, addToHistory = true) => {
    setLoadError(null);
    setIsLoading(true);
    setCurrentUrl(url);
    setInputUrl(url);

    if (addToHistory) {
      setHistory((prev) => {
        const newHistory = prev.slice(0, historyIndex + 1);
        newHistory.push(url);
        return newHistory;
      });
      setHistoryIndex((prev) => prev + 1);
    }
  }, [historyIndex]);

  const goBack = useCallback(() => {
    if (historyIndex > 0) {
      const newIndex = historyIndex - 1;
      setHistoryIndex(newIndex);
      navigate(history[newIndex], false);
    }
  }, [historyIndex, history, navigate]);

  const goForward = useCallback(() => {
    if (historyIndex < history.length - 1) {
      const newIndex = historyIndex + 1;
      setHistoryIndex(newIndex);
      navigate(history[newIndex], false);
    }
  }, [historyIndex, history, navigate]);

  const handleRefresh = useCallback(() => {
    if (iframeRef.current) {
      setIsLoading(true);
      setLoadError(null);
      iframeRef.current.src = currentUrl;
    }
  }, [currentUrl]);

  const handleUrlSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    if (inputUrl && inputUrl !== currentUrl) {
      navigate(inputUrl);
    }
  }, [inputUrl, currentUrl, navigate]);

  const handleIframeLoad = useCallback(() => {
    setIsLoading(false);
    // Try to get the iframe's current URL (may fail for cross-origin)
    try {
      const iframeUrl = iframeRef.current?.contentWindow?.location.href;
      if (iframeUrl && iframeUrl !== "about:blank") {
        setCurrentUrl(iframeUrl);
        setInputUrl(iframeUrl);
      }
    } catch {
      // Cross-origin restriction - can't access iframe URL
    }
  }, []);

  const handleIframeError = useCallback(() => {
    setIsLoading(false);
    setLoadError("Failed to load page. The page may block embedding (X-Frame-Options).");
  }, []);

  const handleOpenExternal = useCallback(() => {
    window.open(currentUrl, "_blank");
  }, [currentUrl]);

  const handleCaptureComplete = useCallback((result: CaptureResult) => {
    setCaptureModalOpen(false);
    if (result.success) {
      toast.success(`Captured evidence v${result.version}`);
    }
  }, []);

  // Handle escape key
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape" && open) {
        onOpenChange(false);
      }
    };
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [open, onOpenChange]);

  return (
    <>
      <AnimatePresence>
        {open && (
          <>
            {/* Backdrop */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm"
              onClick={() => onOpenChange(false)}
            />

            {/* Browser Panel */}
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ duration: 0.2 }}
              className="fixed inset-4 z-50 flex flex-col bg-slate-900 rounded-lg border border-slate-700 shadow-2xl overflow-hidden"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Header */}
              <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-700 bg-slate-900/95 shrink-0">
                {/* Navigation buttons */}
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={goBack}
                    disabled={historyIndex === 0}
                    className="h-8 w-8 p-0"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={goForward}
                    disabled={historyIndex >= history.length - 1}
                    className="h-8 w-8 p-0"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleRefresh}
                    disabled={isLoading}
                    className="h-8 w-8 p-0"
                  >
                    {isLoading ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <RefreshCw className="h-4 w-4" />
                    )}
                  </Button>
                </div>

                {/* URL bar */}
                <form onSubmit={handleUrlSubmit} className="flex-1 flex items-center">
                  <div className="relative flex-1">
                    <Globe className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
                    <Input
                      value={inputUrl}
                      onChange={(e) => setInputUrl(e.target.value)}
                      className="pl-9 pr-4 h-9 bg-slate-800/50 border-slate-700 font-mono text-sm"
                      placeholder="Enter URL..."
                    />
                  </div>
                </form>

                {/* Action buttons */}
                <div className="flex items-center gap-2">
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => setCaptureModalOpen(true)}
                    className="gap-1.5"
                  >
                    <Camera className="h-4 w-4" />
                    Capture
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleOpenExternal}
                    className="h-8 w-8 p-0"
                    title="Open in new tab"
                  >
                    <ExternalLink className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => onOpenChange(false)}
                    className="h-8 w-8 p-0"
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              </div>

              {/* Project info bar */}
              <div className="flex items-center gap-2 px-4 py-1.5 text-xs text-slate-500 border-b border-slate-800 bg-slate-900/50">
                <span>Project:</span>
                <span className="text-slate-300 font-medium">{projectName}</span>
                <span className="mx-1">•</span>
                <span className="mono">{projectId}</span>
              </div>

              {/* Content area */}
              <div className="flex-1 relative bg-white">
                {loadError ? (
                  <div className="absolute inset-0 flex flex-col items-center justify-center bg-slate-950 text-slate-400">
                    <AlertTriangle className="h-12 w-12 text-amber-500 mb-4" />
                    <p className="text-sm mb-2">{loadError}</p>
                    <div className="flex gap-2">
                      <Button variant="outline" size="sm" onClick={handleOpenExternal}>
                        <ExternalLink className="h-4 w-4 mr-1.5" />
                        Open in New Tab
                      </Button>
                      <Button variant="outline" size="sm" onClick={handleRefresh}>
                        <RefreshCw className="h-4 w-4 mr-1.5" />
                        Retry
                      </Button>
                    </div>
                  </div>
                ) : (
                  <iframe
                    ref={iframeRef}
                    src={currentUrl}
                    className="w-full h-full border-0"
                    onLoad={handleIframeLoad}
                    onError={handleIframeError}
                    sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
                    title={`${projectName} - Evidence Browser`}
                  />
                )}

                {/* Loading overlay */}
                {isLoading && (
                  <div className="absolute inset-0 flex items-center justify-center bg-slate-950/50">
                    <div className="flex items-center gap-3 px-4 py-2 rounded-lg bg-slate-800/90">
                      <Loader2 className="h-5 w-5 animate-spin text-phosphor-400" />
                      <span className="text-sm text-slate-300">Loading...</span>
                    </div>
                  </div>
                )}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* Evidence Capture Modal */}
      <EvidenceCaptureModal
        open={captureModalOpen}
        onClose={() => setCaptureModalOpen(false)}
        projectId={projectId}
        pageUrl={currentUrl}
        onCaptured={handleCaptureComplete}
      />
    </>
  );
}
