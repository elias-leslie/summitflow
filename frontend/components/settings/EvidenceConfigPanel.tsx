"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Loader2,
  Camera,
  Bot,
  Monitor,
  AlertTriangle,
  Clock,
  Save,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

// ============================================================================
// Types
// ============================================================================

interface ViewportConfig {
  name: string;
  width: number;
  height: number;
}

interface EvidenceConfig {
  project_id: string;
  enabled_types: string[];
  capture_schedule: string;
  environments: string[];
  viewports: ViewportConfig[];
  auto_expand_elements: boolean;
  regression_threshold: number;
  ai_review_enabled: boolean;
}

interface EvidenceConfigPanelProps {
  projectId: string;
}

// ============================================================================
// Constants
// ============================================================================

const CAPTURE_TYPES = [
  { id: "screenshot", label: "Screenshots", icon: Camera, description: "Capture page screenshots" },
  { id: "console_log", label: "Console Logs", icon: AlertTriangle, description: "Capture console errors and warnings" },
  { id: "api_response", label: "API Responses", icon: Monitor, description: "Capture API endpoint responses" },
];

const SCHEDULE_OPTIONS = [
  { value: "manual", label: "Manual Only" },
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "on_deploy", label: "On Deploy" },
];

const DEFAULT_VIEWPORTS: ViewportConfig[] = [
  { name: "desktop", width: 1280, height: 720 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "mobile", width: 390, height: 844 },
];

// ============================================================================
// API Functions
// ============================================================================

async function fetchEvidenceConfig(projectId: string): Promise<EvidenceConfig> {
  const res = await fetch(`/api/projects/${projectId}/evidence/config`);
  if (!res.ok) {
    throw new Error("Failed to fetch evidence config");
  }
  return res.json();
}

async function updateEvidenceConfig(
  projectId: string,
  config: Partial<EvidenceConfig>
): Promise<EvidenceConfig> {
  const res = await fetch(`/api/projects/${projectId}/evidence/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!res.ok) {
    throw new Error("Failed to update evidence config");
  }
  return res.json();
}

// ============================================================================
// Component
// ============================================================================

export function EvidenceConfigPanel({ projectId }: EvidenceConfigPanelProps) {
  const queryClient = useQueryClient();

  // Local form state
  const [enabledTypes, setEnabledTypes] = useState<string[]>([]);
  const [captureSchedule, setCaptureSchedule] = useState("daily");
  const [viewports, setViewports] = useState<ViewportConfig[]>(DEFAULT_VIEWPORTS);
  const [regressionThreshold, setRegressionThreshold] = useState(5);
  const [aiReviewEnabled, setAiReviewEnabled] = useState(false);
  const [autoExpandElements, setAutoExpandElements] = useState(true);
  const [hasChanges, setHasChanges] = useState(false);

  // Fetch config
  const { data: config, isLoading } = useQuery({
    queryKey: ["evidence-config", projectId],
    queryFn: () => fetchEvidenceConfig(projectId),
  });

  // Sync local state with fetched config
  useEffect(() => {
    if (config) {
      setEnabledTypes(config.enabled_types || []);
      setCaptureSchedule(config.capture_schedule || "daily");
      setViewports(config.viewports || DEFAULT_VIEWPORTS);
      setRegressionThreshold((config.regression_threshold || 0.05) * 100);
      setAiReviewEnabled(config.ai_review_enabled || false);
      setAutoExpandElements(config.auto_expand_elements ?? true);
      setHasChanges(false);
    }
  }, [config]);

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: () =>
      updateEvidenceConfig(projectId, {
        enabled_types: enabledTypes,
        capture_schedule: captureSchedule,
        viewports,
        regression_threshold: regressionThreshold / 100,
        ai_review_enabled: aiReviewEnabled,
        auto_expand_elements: autoExpandElements,
      }),
    onSuccess: () => {
      toast.success("Evidence settings saved");
      queryClient.invalidateQueries({ queryKey: ["evidence-config", projectId] });
      setHasChanges(false);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });

  const toggleType = (typeId: string) => {
    setEnabledTypes((prev) =>
      prev.includes(typeId) ? prev.filter((t) => t !== typeId) : [...prev, typeId]
    );
    setHasChanges(true);
  };

  const handleViewportChange = (index: number, field: keyof ViewportConfig, value: string | number) => {
    setViewports((prev) => {
      const updated = [...prev];
      updated[index] = { ...updated[index], [field]: value };
      return updated;
    });
    setHasChanges(true);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-2xl">
      {/* Capture Types */}
      <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
        <h3 className="text-sm font-medium text-slate-200 mb-4 flex items-center gap-2">
          <Camera className="w-4 h-4 text-slate-400" />
          Capture Types
        </h3>
        <div className="space-y-3">
          {CAPTURE_TYPES.map((type) => (
            <label
              key={type.id}
              className={cn(
                "flex items-center gap-3 p-3 rounded-md border cursor-pointer transition-colors",
                enabledTypes.includes(type.id)
                  ? "border-phosphor-500 bg-phosphor-500/10"
                  : "border-slate-600 hover:border-slate-500"
              )}
            >
              <input
                type="checkbox"
                checked={enabledTypes.includes(type.id)}
                onChange={() => toggleType(type.id)}
                className="accent-phosphor-500"
              />
              <type.icon className="w-4 h-4 text-slate-400" />
              <div className="flex-1">
                <div className="text-sm font-medium text-slate-200">{type.label}</div>
                <div className="text-xs text-slate-400">{type.description}</div>
              </div>
            </label>
          ))}
        </div>
      </div>

      {/* Schedule */}
      <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
        <h3 className="text-sm font-medium text-slate-200 mb-4 flex items-center gap-2">
          <Clock className="w-4 h-4 text-slate-400" />
          Capture Schedule
        </h3>
        <select
          value={captureSchedule}
          onChange={(e) => {
            setCaptureSchedule(e.target.value);
            setHasChanges(true);
          }}
          className="w-full bg-slate-800 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-phosphor-500"
        >
          {SCHEDULE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {/* Viewports */}
      <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
        <h3 className="text-sm font-medium text-slate-200 mb-4 flex items-center gap-2">
          <Monitor className="w-4 h-4 text-slate-400" />
          Viewports
        </h3>
        <div className="space-y-3">
          {viewports.map((vp, idx) => (
            <div key={idx} className="flex items-center gap-3">
              <input
                type="text"
                value={vp.name}
                onChange={(e) => handleViewportChange(idx, "name", e.target.value)}
                className="flex-1 bg-slate-800 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-phosphor-500"
                placeholder="Name"
              />
              <input
                type="number"
                value={vp.width}
                onChange={(e) => handleViewportChange(idx, "width", parseInt(e.target.value) || 0)}
                className="w-24 bg-slate-800 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-phosphor-500"
                placeholder="Width"
              />
              <span className="text-slate-500">x</span>
              <input
                type="number"
                value={vp.height}
                onChange={(e) => handleViewportChange(idx, "height", parseInt(e.target.value) || 0)}
                className="w-24 bg-slate-800 border border-slate-600 rounded-md px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-phosphor-500"
                placeholder="Height"
              />
            </div>
          ))}
        </div>
      </div>

      {/* Regression Threshold */}
      <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
        <h3 className="text-sm font-medium text-slate-200 mb-2 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-slate-400" />
          Regression Threshold
        </h3>
        <p className="text-xs text-slate-400 mb-4">
          Pixel difference percentage above which a visual change is flagged as a regression.
        </p>
        <div className="flex items-center gap-4">
          <input
            type="range"
            min={1}
            max={20}
            value={regressionThreshold}
            onChange={(e) => {
              setRegressionThreshold(parseInt(e.target.value));
              setHasChanges(true);
            }}
            className="flex-1 accent-phosphor-500"
          />
          <span className="text-sm font-mono text-slate-200 w-12 text-right">
            {regressionThreshold}%
          </span>
        </div>
      </div>

      {/* AI Review */}
      <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Bot className="w-4 h-4 text-slate-400" />
            <div>
              <h3 className="text-sm font-medium text-slate-200">AI Review</h3>
              <p className="text-xs text-slate-400">
                Automatically analyze screenshots for visual issues
              </p>
            </div>
          </div>
          <Switch
            checked={aiReviewEnabled}
            onCheckedChange={(checked) => {
              setAiReviewEnabled(checked);
              setHasChanges(true);
            }}
          />
        </div>
      </div>

      {/* Save Button */}
      <div className="flex justify-end">
        <Button
          onClick={() => saveMutation.mutate()}
          disabled={!hasChanges || saveMutation.isPending}
          className="flex items-center gap-2"
        >
          {saveMutation.isPending ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Save className="w-4 h-4" />
          )}
          Save Settings
        </Button>
      </div>
    </div>
  );
}
