"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { Loader2, AlertCircle, ArrowLeft, Kanban } from "lucide-react";
import Link from "next/link";

import { KanbanBoard, type KanbanStatus } from "@/components/kanban/KanbanBoard";
import { FeatureDetailDrawer } from "@/components/kanban/FeatureDetailDrawer";
import { useFeatures, useUpdateFeatureStatus } from "@/hooks/useFeatures";
import { Button } from "@/components/ui/button";
import type { Feature } from "@/lib/api";

export default function KanbanPage() {
  const params = useParams();
  const projectId = params.id as string;

  const [selectedFeature, setSelectedFeature] = useState<Feature | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Fetch features
  const { data, isLoading, error } = useFeatures(projectId);
  const features = data?.features ?? [];

  // Status update mutation
  const updateStatus = useUpdateFeatureStatus(projectId);

  // Handle status change from drag-drop
  const handleStatusChange = (featureId: string, newStatus: KanbanStatus) => {
    updateStatus.mutate({ featureId, newStatus });
  };

  // Handle feature card click
  const handleFeatureClick = (feature: Feature) => {
    setSelectedFeature(feature);
    setDrawerOpen(true);
  };

  // Handle start click from card or drawer
  const handleStartClick = (feature: Feature) => {
    // Move to in_progress if not already there
    if (feature.status !== "in_progress") {
      updateStatus.mutate({ featureId: feature.feature_id, newStatus: "in_progress" });
    }
    // TODO: Navigate to task creation or open task modal
    console.log("Start clicked for:", feature.feature_id);
  };

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Loader2 className="h-8 w-8 animate-spin text-phosphor-400" />
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] text-center">
        <AlertCircle className="h-12 w-12 text-rose-400 mb-4" />
        <h2 className="text-lg font-medium text-white mb-2">Failed to load features</h2>
        <p className="text-sm text-slate-400 mb-4">{error.message}</p>
        <Button variant="outline" onClick={() => window.location.reload()}>
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link href={`/projects/${projectId}`}>
            <Button variant="ghost" size="sm" className="gap-2">
              <ArrowLeft className="h-4 w-4" />
              Back
            </Button>
          </Link>
          <div className="flex items-center gap-2">
            <Kanban className="h-5 w-5 text-phosphor-400" />
            <h1 className="text-xl font-semibold text-white">Kanban Board</h1>
          </div>
        </div>
        <div className="text-sm text-slate-500">
          {features.length} features
        </div>
      </div>

      {/* Kanban Board */}
      <KanbanBoard
        features={features}
        onStatusChange={handleStatusChange}
        onFeatureClick={handleFeatureClick}
        onStartClick={handleStartClick}
      />

      {/* Feature Detail Drawer */}
      <FeatureDetailDrawer
        feature={selectedFeature}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        onStartClick={handleStartClick}
      />
    </div>
  );
}
