"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Camera,
  Loader2,
  FolderOpen,
  Search,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Link2,
  CheckCircle2,
  Crosshair,
  Zap,
} from "lucide-react";
import { clsx } from "clsx";

interface AcceptanceCriterion {
  id: string;
  criterion: string;
  verification?: string;
  type: string;
  passed?: boolean | null;
}

interface Feature {
  capability_id: string;
  name: string;
  category: string | null;
  acceptance_criteria: AcceptanceCriterion[];
}

interface EvidenceCaptureResult {
  success: boolean;
  version?: number;
  capability_id?: string;
  criterion_id?: string;
  error?: string;
  evidence?: {
    console: { errorCount: number; warningCount: number };
    network: { failedRequests: number };
    metadata: { url: string; capturedAt: string };
  };
}

interface EvidenceCaptureModalProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  pageUrl: string;
  onCaptured: (result: EvidenceCaptureResult) => void;
}

type SortField = "capability_id" | "name" | "category" | "ui_count" | "url_match";
type SortDirection = "asc" | "desc";

// Extract path from URL for matching
function extractPath(url: string): string {
  try {
    const parsed = new URL(url);
    return parsed.pathname;
  } catch {
    // If it's already a path or invalid URL
    return url.startsWith("/") ? url : `/${url}`;
  }
}

// Check if a feature/criterion matches the current URL path
function checkUrlMatch(
  feature: Feature,
  currentPath: string
): { matches: boolean; matchingCriteria: string[] } {
  const matchingCriteria: string[] = [];
  const pathLower = currentPath.toLowerCase();

  for (const criterion of feature.acceptance_criteria || []) {
    if (criterion.type !== "ui") continue;

    // Check verification field for URL/path
    const verification = criterion.verification?.toLowerCase() || "";
    const criterionText = criterion.criterion.toLowerCase();

    // Match patterns: "screenshot /status", "/status", "http://...//status"
    if (
      verification.includes(pathLower) ||
      criterionText.includes(pathLower) ||
      // Also check if path segments match (e.g., "status" in "/status/details")
      pathLower.split("/").some(
        (segment) =>
          segment && (verification.includes(segment) || criterionText.includes(segment))
      )
    ) {
      matchingCriteria.push(criterion.id);
    }
  }

  return { matches: matchingCriteria.length > 0, matchingCriteria };
}

export function EvidenceCaptureModal({
  open,
  onClose,
  projectId,
  pageUrl,
  onCaptured,
}: EvidenceCaptureModalProps) {
  const [mode, setMode] = useState<"debug" | "new" | "existing">("debug");
  const [selectedFeature, setSelectedFeature] = useState<string>("");
  const [selectedCriterion, setSelectedCriterion] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState("");
  const [urlMatchOnly, setUrlMatchOnly] = useState(false);
  const [sortField, setSortField] = useState<SortField>("url_match");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [isCapturing, setIsCapturing] = useState(false);
  // New Feature form fields
  const [newFeatureName, setNewFeatureName] = useState("");
  const [newFeatureCategory, setNewFeatureCategory] = useState("UI");

  const currentPath = extractPath(pageUrl);

  // Shared Screen Capture API logic - captures exactly what user sees
  // Returns base64 PNG or throws error
  const captureScreenshotBase64 = useCallback(async (): Promise<string> => {
    // Check if Screen Capture API is available (requires secure context)
    if (!navigator.mediaDevices?.getDisplayMedia) {
      const isLocalhost = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
      const msg = isLocalhost
        ? "Screen Capture API not available in this browser"
        : `Screen Capture requires HTTPS or localhost. To enable for ${window.location.hostname}:\n\n` +
          "Chrome: chrome://flags/#unsafely-treat-insecure-origin-as-secure\n" +
          `Add: http://${window.location.host}`;
      throw new Error(msg);
    }

    // IMPORTANT: Close the modal BEFORE triggering screen capture
    // This prevents the modal from appearing in the screenshot
    onClose();

    // Wait for the modal to be removed from DOM
    await new Promise((resolve) => setTimeout(resolve, 150));

    // Request screen capture with preference for current tab
    const stream = await navigator.mediaDevices.getDisplayMedia({
      video: {
        displaySurface: "browser",
      },
      // @ts-expect-error - preferCurrentTab is a newer API not in all TypeScript defs
      preferCurrentTab: true,
    });

    try {
      const track = stream.getVideoTracks()[0];

      // Use ImageCapture API if available, fallback to video element approach
      let bitmap: ImageBitmap;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const ImageCaptureAPI = (window as any).ImageCapture;
      if (typeof ImageCaptureAPI !== "undefined") {
        const imageCapture = new ImageCaptureAPI(track);
        bitmap = await imageCapture.grabFrame();
      } else {
        // Fallback for browsers without ImageCapture
        const video = document.createElement("video");
        video.srcObject = stream;
        video.muted = true;
        await video.play();

        // Wait for video to have dimensions
        await new Promise<void>((resolve) => {
          if (video.videoWidth > 0) {
            resolve();
          } else {
            video.onloadedmetadata = () => resolve();
          }
        });

        bitmap = await createImageBitmap(video);
        video.pause();
        video.srcObject = null;
      }

      // Stop the stream immediately after capture
      track.stop();

      // Convert bitmap to canvas to get base64 PNG
      const canvas = document.createElement("canvas");
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      const ctx = canvas.getContext("2d");
      if (!ctx) throw new Error("Failed to get canvas context");
      ctx.drawImage(bitmap, 0, 0);
      bitmap.close();

      const dataUrl = canvas.toDataURL("image/png");
      return dataUrl.split(",")[1];
    } finally {
      // Always clean up stream
      stream.getTracks().forEach((t) => t.stop());
    }
  }, [onClose]);

  // Gather client-side console errors and network failures (must be before captureDebug)
  const gatherClientSideEvidence = useCallback(() => {
    const errors: string[] = [];
    const warnings: string[] = [];
    const networkFailures: Array<{ url: string; status: number; statusText: string }> = [];

    // Get recent performance entries for failed requests
    if (typeof performance !== "undefined" && performance.getEntriesByType) {
      const resources = performance.getEntriesByType("resource") as PerformanceResourceTiming[];
      // Check for resources that took too long or had issues (heuristic)
      resources.forEach((r) => {
        // Resources with 0 transferSize but non-zero duration might have failed
        // This is imperfect but catches some failures
        if (r.transferSize === 0 && r.duration > 0 && r.responseStatus && r.responseStatus >= 400) {
          networkFailures.push({
            url: r.name,
            status: r.responseStatus || 0,
            statusText: "Failed",
          });
        }
      });
    }

    // Check for any error elements on page (error boundaries, etc.)
    const errorElements = document.querySelectorAll('[data-error], .error, [role="alert"]');
    errorElements.forEach((el) => {
      const text = el.textContent?.trim();
      if (text && text.length < 500) {
        errors.push(text);
      }
    });

    return {
      console: {
        errors: errors.slice(0, 10),
        warnings: warnings.slice(0, 10),
        errorCount: errors.length,
        warningCount: warnings.length,
      },
      network: {
        failures: networkFailures.slice(0, 10),
        failureCount: networkFailures.length,
      },
    };
  }, []);

  // Quick Debug capture - saves to debug folder with evidence (no DB entry)
  const captureDebug = useCallback(async () => {
    setIsCapturing(true);

    try {
      const clientEvidence = gatherClientSideEvidence();
      const base64 = await captureScreenshotBase64();

      const response = await fetch(`/api/projects/${projectId}/evidence/debug-capture`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          screenshot_base64: base64,
          url: pageUrl,
          page_title: document.title,
          client_evidence: clientEvidence,
        }),
      });

      if (!response.ok) throw new Error("Failed to upload screenshot");

      const result = await response.json();
      toast.success("Debug captured! Claude: Read data/debug-captures/latest.png");
      onCaptured({
        success: true,
        version: 1,
        capability_id: "DEBUG",
        criterion_id: "debug",
        evidence: {
          console: clientEvidence.console,
          network: clientEvidence.network,
          metadata: { url: pageUrl, capturedAt: new Date().toISOString() },
        },
        ...result,
      });
    } catch (error) {
      console.error("Debug capture failed:", error);
      if (error instanceof Error && error.name === "NotAllowedError") {
        toast.error("Screen capture cancelled - permission required");
      } else if (error instanceof Error && error.message.includes("chrome://flags")) {
        toast.error(error.message, { duration: 10000 });
      } else {
        toast.error(error instanceof Error ? error.message : "Failed to capture");
      }
    } finally {
      setIsCapturing(false);
    }
  }, [projectId, pageUrl, onCaptured, captureScreenshotBase64, gatherClientSideEvidence]);

  // Feature capture - saves to feature/criterion with DB entry
  const captureForFeature = useCallback(async (capabilityId: string, criterionId: string) => {
    setIsCapturing(true);

    try {
      // Gather evidence BEFORE screenshot (while page is in current state)
      const clientEvidence = gatherClientSideEvidence();

      const base64 = await captureScreenshotBase64();

      // Send to viewport-capture endpoint (creates DB entry for feature)
      const response = await fetch(`/api/projects/${projectId}/evidence/viewport-capture`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          capability_id: capabilityId,
          criterion_id: criterionId,
          screenshot_base64: base64,
          url: pageUrl,
          viewport_width: window.innerWidth,
          viewport_height: window.innerHeight,
          scroll_x: window.scrollX,
          scroll_y: window.scrollY,
          page_title: document.title,
          client_evidence: clientEvidence,
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to upload screenshot");
      }

      const result = await response.json();
      toast.success(`Evidence captured (v${result.version}) for ${capabilityId}`);
      onCaptured(result);
    } catch (error) {
      console.error("Feature capture failed:", error);
      if (error instanceof Error && error.name === "NotAllowedError") {
        toast.error("Screen capture cancelled - permission required");
      } else if (error instanceof Error && error.message.includes("chrome://flags")) {
        toast.error(error.message, { duration: 10000 });
      } else {
        toast.error(error instanceof Error ? error.message : "Failed to capture evidence");
      }
    } finally {
      setIsCapturing(false);
    }
  }, [projectId, pageUrl, onCaptured, captureScreenshotBase64, gatherClientSideEvidence]);

  // Fetch existing features (deprecated - features replaced with capabilities)
  const { data: featuresData, isLoading: loadingFeatures } = useQuery<{
    features: Feature[];
  }>({
    queryKey: ["features-for-evidence", projectId],
    queryFn: async () => {
      // Features API deprecated, return empty to maintain compatibility
      return { features: [] };
    },
    enabled: open && mode === "existing",
  });

  // Process features with URL matching and filtering
  const processedFeatures = useMemo(() => {
    if (!featuresData?.features) return [];

    return featuresData.features
      .map((feature) => {
        const uiCriteria = (feature.acceptance_criteria || []).filter((c) => c.type === "ui");
        const urlMatchInfo = checkUrlMatch(feature, currentPath);
        return {
          ...feature,
          uiCriteria,
          uiCount: uiCriteria.length,
          urlMatch: urlMatchInfo.matches,
          matchingCriteriaIds: urlMatchInfo.matchingCriteria,
        };
      })
      .filter((f) => f.uiCount > 0); // Only show features with UI criteria
  }, [featuresData, currentPath]);

  // Filter and sort features
  const filteredFeatures = useMemo(() => {
    let result = processedFeatures;

    // Search filter
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      result = result.filter(
        (f) =>
          f.capability_id.toLowerCase().includes(query) ||
          f.name.toLowerCase().includes(query) ||
          (f.category || "").toLowerCase().includes(query) ||
          f.uiCriteria.some((c) => c.criterion.toLowerCase().includes(query))
      );
    }

    // URL match filter
    if (urlMatchOnly) {
      result = result.filter((f) => f.urlMatch);
    }

    // Sort
    result.sort((a, b) => {
      let comparison = 0;
      switch (sortField) {
        case "capability_id":
          comparison = a.capability_id.localeCompare(b.capability_id);
          break;
        case "name":
          comparison = a.name.localeCompare(b.name);
          break;
        case "category":
          comparison = (a.category || "").localeCompare(b.category || "");
          break;
        case "ui_count":
          comparison = a.uiCount - b.uiCount;
          break;
        case "url_match":
          // URL matches first, then by feature ID
          comparison = (b.urlMatch ? 1 : 0) - (a.urlMatch ? 1 : 0);
          if (comparison === 0) {
            comparison = a.capability_id.localeCompare(b.capability_id);
          }
          break;
      }
      return sortDirection === "asc" ? comparison : -comparison;
    });

    return result;
  }, [processedFeatures, searchQuery, urlMatchOnly, sortField, sortDirection]);

  // Get selected feature data
  const selectedFeatureData = processedFeatures.find(
    (f) => f.capability_id === selectedFeature
  );

  // Reset state when modal opens/closes
  useEffect(() => {
    if (!open) {
      setMode("debug");
      setSelectedFeature("");
      setSelectedCriterion("");
      setSearchQuery("");
      setUrlMatchOnly(false);
    }
  }, [open]);

  // Auto-select first matching criterion when feature is selected
  useEffect(() => {
    if (selectedFeatureData && !selectedCriterion) {
      // Prefer matching criteria, otherwise first UI criterion
      if (selectedFeatureData.matchingCriteriaIds.length > 0) {
        setSelectedCriterion(selectedFeatureData.matchingCriteriaIds[0]);
      } else if (selectedFeatureData.uiCriteria.length > 0) {
        setSelectedCriterion(selectedFeatureData.uiCriteria[0].id);
      }
    }
  }, [selectedFeatureData, selectedCriterion]);

  // Handle capture - ALL modes use Screen Capture API
  const handleCapture = async () => {
    if (mode === "debug") {
      // Quick Debug - no DB entry
      await captureDebug();
    } else if (mode === "new") {
      // New Feature - create feature with user-provided name, then capture
      if (!newFeatureName.trim()) {
        toast.error("Please enter a feature name");
        return;
      }
      try {
        const response = await fetch(`/api/projects/${projectId}/features/quick`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: newFeatureName.trim(),
            category: newFeatureCategory,
            url: pageUrl,
          }),
        });
        if (!response.ok) throw new Error("Failed to create feature");
        const newFeature = await response.json();
        const criterionId = newFeature.acceptance_criteria?.[0]?.id || "ac-001";
        await captureForFeature(newFeature.capability_id, criterionId);
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "Failed to create feature");
      }
    } else {
      // Existing Feature - use selected feature/criterion
      if (!selectedFeature || !selectedCriterion) {
        toast.error("Please select a feature and criterion");
        return;
      }
      await captureForFeature(selectedFeature, selectedCriterion);
    }
  };

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDirection(field === "url_match" ? "desc" : "asc");
    }
  };

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field) return <ArrowUpDown className="h-3 w-3 opacity-50" />;
    return sortDirection === "asc" ? (
      <ArrowUp className="h-3 w-3" />
    ) : (
      <ArrowDown className="h-3 w-3" />
    );
  };

  const isBusy = isCapturing;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className={clsx(
        "sm:max-w-md transition-all duration-200",
        mode === "existing" && "sm:max-w-2xl"
      )}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Camera className="h-5 w-5" />
            Capture Evidence
          </DialogTitle>
          <DialogDescription>
            Capture screenshot and page state for:{" "}
            <code className="text-xs bg-slate-800 px-1 rounded mono">{currentPath}</code>
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Mode selector */}
          <div className="flex gap-2">
            <Button
              variant={mode === "debug" ? "primary" : "outline"}
              size="sm"
              onClick={() => setMode("debug")}
              className="flex-1"
            >
              <Zap className="h-4 w-4 mr-2" />
              Quick Debug
            </Button>
            <Button
              variant={mode === "new" ? "primary" : "outline"}
              size="sm"
              onClick={() => setMode("new")}
              className="flex-1"
            >
              <Crosshair className="h-4 w-4 mr-2" />
              New Feature
            </Button>
            <Button
              variant={mode === "existing" ? "primary" : "outline"}
              size="sm"
              onClick={() => setMode("existing")}
              className="flex-1"
            >
              <FolderOpen className="h-4 w-4 mr-2" />
              Existing
            </Button>
          </div>

          {mode === "debug" ? (
            <div className="rounded-lg border border-phosphor-500/30 bg-phosphor-500/5 p-4 text-sm space-y-2">
              <p className="font-medium text-phosphor-400">
                Quick Debug - no DB entry
              </p>
              <ul className="text-slate-400 text-xs space-y-1">
                <li>• Captures exactly what you see on screen</li>
                <li>• Saves to debug-captures/ with evidence</li>
                <li>• Claude can read: data/debug-captures/latest.png</li>
                <li>• Auto-cleanup keeps last 20 captures</li>
              </ul>
              <p className="text-xs text-amber-400 mt-2">
                A permission popup will appear - select this tab to capture.
              </p>
            </div>
          ) : mode === "new" ? (
            <div className="space-y-3">
              <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-3 text-xs text-slate-400">
                Creates a new feature with your screenshot as evidence.
              </div>
              <div className="space-y-2">
                <Label htmlFor="feature-name" className="text-sm">Feature Name</Label>
                <Input
                  id="feature-name"
                  placeholder="e.g., Status Page Services Table"
                  value={newFeatureName}
                  onChange={(e) => setNewFeatureName(e.target.value)}
                  className="h-9"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="feature-category" className="text-sm">Category</Label>
                <select
                  id="feature-category"
                  value={newFeatureCategory}
                  onChange={(e) => setNewFeatureCategory(e.target.value)}
                  className="w-full h-9 px-3 rounded-md border border-slate-700 bg-slate-900 text-sm text-slate-200 focus:outline-none focus:border-phosphor-500/50 focus:ring-1 focus:ring-phosphor-500/20 transition-all"
                >
                  <option value="UI">UI</option>
                  <option value="Dashboard">Dashboard</option>
                  <option value="Status">Status</option>
                  <option value="Sitemap">Sitemap</option>
                  <option value="Evidence">Evidence</option>
                  <option value="Vision">Vision</option>
                  <option value="Settings">Settings</option>
                </select>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {/* Search and filter controls */}
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-500" />
                  <Input
                    placeholder="Search features..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-9 h-9"
                  />
                </div>
                <div className="flex items-center gap-2 px-3 border border-slate-700 rounded-md bg-slate-800/30">
                  <Checkbox
                    id="url-match"
                    checked={urlMatchOnly}
                    onCheckedChange={(c) => setUrlMatchOnly(c === true)}
                  />
                  <Label htmlFor="url-match" className="text-xs cursor-pointer whitespace-nowrap">
                    <Link2 className="h-3 w-3 inline mr-1" />
                    URL match only
                  </Label>
                </div>
              </div>

              {/* Features table */}
              <div className="border border-slate-700 rounded-md">
                {/* Table header */}
                <div className="grid grid-cols-[1fr_2fr_1fr_60px_50px] gap-2 px-3 py-2 bg-slate-800/50 border-b border-slate-700 text-xs font-medium">
                  <button
                    className="flex items-center gap-1 hover:text-phosphor-400 text-left"
                    onClick={() => handleSort("capability_id")}
                  >
                    ID <SortIcon field="capability_id" />
                  </button>
                  <button
                    className="flex items-center gap-1 hover:text-phosphor-400 text-left"
                    onClick={() => handleSort("name")}
                  >
                    Name <SortIcon field="name" />
                  </button>
                  <button
                    className="flex items-center gap-1 hover:text-phosphor-400 text-left"
                    onClick={() => handleSort("category")}
                  >
                    Category <SortIcon field="category" />
                  </button>
                  <button
                    className="flex items-center gap-1 hover:text-phosphor-400 text-center justify-center"
                    onClick={() => handleSort("ui_count")}
                  >
                    UI <SortIcon field="ui_count" />
                  </button>
                  <button
                    className="flex items-center gap-1 hover:text-phosphor-400 text-center justify-center"
                    onClick={() => handleSort("url_match")}
                    title="URL Match"
                  >
                    <Link2 className="h-3 w-3" /> <SortIcon field="url_match" />
                  </button>
                </div>

                {/* Table body */}
                <ScrollArea className="h-[280px]">
                  {loadingFeatures ? (
                    <div className="flex items-center justify-center py-8">
                      <Loader2 className="h-5 w-5 animate-spin text-slate-500" />
                    </div>
                  ) : filteredFeatures.length === 0 ? (
                    <div className="text-center py-8 text-sm text-slate-500">
                      {searchQuery || urlMatchOnly
                        ? "No features match your filters"
                        : "No features with UI criteria found"}
                    </div>
                  ) : (
                    filteredFeatures.map((feature) => (
                      <button
                        key={feature.capability_id}
                        className={clsx(
                          "w-full grid grid-cols-[1fr_2fr_1fr_60px_50px] gap-2 px-3 py-2 text-xs text-left",
                          "hover:bg-slate-800/50 border-b border-slate-700/50 transition-colors",
                          selectedFeature === feature.capability_id &&
                            "bg-phosphor-500/10 hover:bg-phosphor-500/20"
                        )}
                        onClick={() => {
                          setSelectedFeature(feature.capability_id);
                          setSelectedCriterion("");
                        }}
                      >
                        <span className="mono truncate">{feature.capability_id}</span>
                        <span className="truncate">{feature.name}</span>
                        <span className="truncate text-slate-500">
                          {feature.category || "N/A"}
                        </span>
                        <span className="text-center">{feature.uiCount}</span>
                        <span className="text-center">
                          {feature.urlMatch && (
                            <Link2 className="h-3.5 w-3.5 text-phosphor-500 mx-auto" />
                          )}
                        </span>
                      </button>
                    ))
                  )}
                </ScrollArea>
              </div>

              {/* Selected feature criteria */}
              {selectedFeatureData && (
                <div className="space-y-2">
                  <Label className="text-xs text-slate-400">
                    Select UI Criterion for{" "}
                    <span className="mono">{selectedFeature}</span>:
                  </Label>
                  <div className="border border-slate-700 rounded-md divide-y divide-slate-700 max-h-[120px] overflow-y-auto">
                    {selectedFeatureData.uiCriteria.map((criterion) => {
                      const isMatching = selectedFeatureData.matchingCriteriaIds.includes(
                        criterion.id
                      );
                      return (
                        <button
                          key={criterion.id}
                          className={clsx(
                            "w-full flex items-start gap-2 px-3 py-2 text-left text-xs",
                            "hover:bg-slate-800/50 transition-colors",
                            selectedCriterion === criterion.id &&
                              "bg-phosphor-500/10 hover:bg-phosphor-500/20"
                          )}
                          onClick={() => setSelectedCriterion(criterion.id)}
                        >
                          <span
                            className={clsx(
                              "mono shrink-0 mt-0.5",
                              selectedCriterion === criterion.id && "text-phosphor-400"
                            )}
                          >
                            {criterion.id}
                          </span>
                          <span className="flex-1 line-clamp-2">{criterion.criterion}</span>
                          {isMatching && (
                            <Link2 className="h-3.5 w-3.5 text-phosphor-500 shrink-0 mt-0.5" />
                          )}
                          {selectedCriterion === criterion.id && (
                            <CheckCircle2 className="h-3.5 w-3.5 text-phosphor-400 shrink-0 mt-0.5" />
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Stats */}
              <div className="text-xs text-slate-500">
                {filteredFeatures.length} features
                {urlMatchOnly && ` (${processedFeatures.filter((f) => f.urlMatch).length} URL matches)`}
                {selectedFeature && selectedCriterion && (
                  <span className="ml-2 text-phosphor-400">
                    → {selectedFeature} / {selectedCriterion}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-700 pt-4">
          <Button variant="outline" onClick={onClose} disabled={isBusy}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={handleCapture}
            disabled={
              isBusy ||
              (mode === "new" && !newFeatureName.trim()) ||
              (mode === "existing" && (!selectedFeature || !selectedCriterion))
            }
          >
            {isBusy ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Capturing...
              </>
            ) : (
              <>
                <Camera className="h-4 w-4 mr-2" />
                Capture
              </>
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
