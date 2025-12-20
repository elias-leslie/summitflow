"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Compass,
  Loader2,
  AlertCircle,
  Lightbulb,
  Sparkles,
} from "lucide-react";

import { fetchVisionContent, type VisionContentResponse } from "@/lib/api";

// ============================================================================
// Types
// ============================================================================

interface VisionOverviewProps {
  projectId: string;
}

// ============================================================================
// Vision Content Section
// ============================================================================

interface ContentSectionProps {
  title: string;
  content: string;
  icon: React.ReactNode;
  variant?: "primary" | "secondary";
}

function ContentSection({ title, content, icon, variant = "secondary" }: ContentSectionProps) {
  const isPrimary = variant === "primary";

  return (
    <div
      className={`
        rounded-lg border p-5
        ${isPrimary
          ? "border-phosphor-500/30 bg-phosphor-500/5"
          : "border-slate-700 bg-slate-800/30"
        }
      `}
    >
      <div className="flex items-center gap-2 mb-3">
        <span className={isPrimary ? "text-phosphor-400" : "text-slate-400"}>
          {icon}
        </span>
        <h3 className={`font-semibold ${isPrimary ? "text-phosphor-400" : "text-slate-200"}`}>
          {title}
        </h3>
      </div>
      <p className="text-sm text-slate-400 leading-relaxed">
        {content}
      </p>
    </div>
  );
}

// ============================================================================
// Vision Overview Component
// ============================================================================

export function VisionOverview({ projectId }: VisionOverviewProps) {
  const { data, error, isLoading } = useQuery<VisionContentResponse>({
    queryKey: ["vision-content", projectId],
    queryFn: () => fetchVisionContent(projectId),
    enabled: !!projectId,
    staleTime: 1000 * 60 * 5, // 5 minutes
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-rose-400">
        <AlertCircle className="h-5 w-5" />
        <span>Failed to load vision content</span>
      </div>
    );
  }

  const content = data?.content || {};
  const missionItems = content.mission || [];
  const visionItems = content.vision || [];

  const hasContent = missionItems.length > 0 || visionItems.length > 0;

  if (!hasContent) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-slate-500">
        <Compass className="h-8 w-8 mb-2" />
        <span className="text-sm">No vision content defined</span>
        <span className="text-xs text-slate-600">Add a VISION.md to define project mission and goals</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold text-slate-200">Project Vision</h2>
        <p className="text-sm text-slate-500">
          Mission statement and guiding principles
        </p>
      </div>

      {/* Mission Statement */}
      {missionItems.length > 0 && (
        <ContentSection
          title={missionItems[0].title || "Mission"}
          content={missionItems[0].content}
          icon={<Compass className="h-5 w-5" />}
          variant="primary"
        />
      )}

      {/* Vision Sections */}
      {visionItems.length > 0 && (
        <div className="space-y-4">
          <h3 className="text-sm font-medium text-slate-400">Vision Narrative</h3>
          <div className="grid gap-4 sm:grid-cols-2">
            {visionItems.map((item, index) => (
              <ContentSection
                key={item.id || index}
                title={item.title || `Section ${index + 1}`}
                content={item.content}
                icon={index === 0 ? <Lightbulb className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}
              />
            ))}
          </div>
        </div>
      )}

      {/* Summary */}
      <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
        <div className="grid grid-cols-2 gap-4 text-center">
          <div>
            <div className="text-2xl font-semibold text-slate-200">
              {missionItems.length}
            </div>
            <div className="text-xs text-slate-500">Mission Statement{missionItems.length !== 1 ? "s" : ""}</div>
          </div>
          <div>
            <div className="text-2xl font-semibold text-slate-200">
              {visionItems.length}
            </div>
            <div className="text-xs text-slate-500">Vision Section{visionItems.length !== 1 ? "s" : ""}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
