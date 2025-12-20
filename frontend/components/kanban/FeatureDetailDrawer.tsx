"use client";

import { useState, useEffect } from "react";
import {
  CheckCircle2,
  XCircle,
  HelpCircle,
  Edit2,
  Save,
  X,
  Play,
  Clock,
  Loader2,
  Pause,
} from "lucide-react";

import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetBody, SheetClose } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { Feature, AcceptanceCriterion, FeatureTask } from "@/lib/api";
import { fetchFeatureTasks } from "@/lib/api";

interface FeatureDetailDrawerProps {
  feature: Feature | null;
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onStartClick?: (feature: Feature) => void;
  onFeatureUpdate?: (featureId: string, updates: Partial<Feature>) => void;
}

// ============================================================================
// Priority Colors
// ============================================================================

const priorityColors: Record<number, { bg: string; text: string; border: string }> = {
  1: { bg: "bg-rose-500/20", text: "text-rose-400", border: "border-rose-500/30" },
  2: { bg: "bg-orange-500/20", text: "text-orange-400", border: "border-orange-500/30" },
  3: { bg: "bg-amber-500/20", text: "text-amber-400", border: "border-amber-500/30" },
  4: { bg: "bg-blue-500/20", text: "text-blue-400", border: "border-blue-500/30" },
  5: { bg: "bg-slate-500/20", text: "text-slate-400", border: "border-slate-500/30" },
};

// ============================================================================
// Criterion Row Component
// ============================================================================

function CriterionRow({ criterion }: { criterion: AcceptanceCriterion }) {
  const isPassed = criterion.passed === true;
  const isFailed = criterion.passed === false;

  return (
    <div className="flex items-start gap-3 py-2.5 border-b border-slate-800 last:border-0">
      <span className="shrink-0 mt-0.5">
        {isPassed ? (
          <CheckCircle2 className="h-4 w-4 text-phosphor-400" />
        ) : isFailed ? (
          <XCircle className="h-4 w-4 text-rose-400" />
        ) : (
          <HelpCircle className="h-4 w-4 text-amber-400" />
        )}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="mono text-xs text-slate-500">{criterion.id}</span>
          <span className="text-xs px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 border border-blue-500/30">
            {criterion.type}
          </span>
        </div>
        <p className="text-sm text-slate-300">{criterion.criterion}</p>
      </div>
    </div>
  );
}

// ============================================================================
// Task Row Component
// ============================================================================

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${mins}m`;
}

function TaskRow({ task }: { task: FeatureTask }) {
  const statusConfig: Record<string, { icon: React.ReactNode; color: string }> = {
    pending: { icon: <Clock className="h-3.5 w-3.5" />, color: "text-slate-400" },
    running: { icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />, color: "text-blue-400" },
    completed: { icon: <CheckCircle2 className="h-3.5 w-3.5" />, color: "text-phosphor-400" },
    failed: { icon: <XCircle className="h-3.5 w-3.5" />, color: "text-rose-400" },
    paused: { icon: <Pause className="h-3.5 w-3.5" />, color: "text-amber-400" },
  };

  const config = statusConfig[task.status] || statusConfig.pending;

  return (
    <div className="flex items-center justify-between py-2.5 border-b border-slate-800 last:border-0">
      <div className="flex items-center gap-2 min-w-0">
        <span className={`shrink-0 ${config.color}`}>{config.icon}</span>
        <span className="text-sm text-slate-300 truncate">{task.title}</span>
      </div>
      <div className="flex items-center gap-3 shrink-0 text-xs text-slate-500">
        {task.started_at && (
          <span>{new Date(task.started_at).toLocaleDateString()}</span>
        )}
        {task.duration_seconds !== null && (
          <span className="mono">{formatDuration(task.duration_seconds)}</span>
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Feature Detail Drawer
// ============================================================================

export function FeatureDetailDrawer({
  feature,
  projectId,
  open,
  onOpenChange,
  onStartClick,
  onFeatureUpdate,
}: FeatureDetailDrawerProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [tasks, setTasks] = useState<FeatureTask[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);

  // Fetch tasks when feature changes
  useEffect(() => {
    if (!feature || !open) {
      setTasks([]);
      return;
    }

    const loadTasks = async () => {
      setTasksLoading(true);
      try {
        const fetchedTasks = await fetchFeatureTasks(projectId, feature.feature_id);
        setTasks(fetchedTasks);
      } catch (error) {
        console.error("Failed to fetch feature tasks:", error);
        setTasks([]);
      } finally {
        setTasksLoading(false);
      }
    };

    loadTasks();
  }, [feature, projectId, open]);

  if (!feature) return null;

  const criteria = feature.acceptance_criteria ?? [];
  const passedCount = criteria.filter((c) => c.passed).length;
  const totalCount = criteria.length;
  const progressPct = totalCount > 0 ? (passedCount / totalCount) * 100 : 0;
  const allPassed = totalCount > 0 && passedCount === totalCount;
  const priority = feature.priority ?? feature.effective_priority ?? 3;
  const colors = priorityColors[priority] || priorityColors[5];

  const handleEditStart = () => {
    setEditName(feature.name);
    setEditDescription(feature.description || "");
    setIsEditing(true);
  };

  const handleEditCancel = () => {
    setIsEditing(false);
    setEditName("");
    setEditDescription("");
  };

  const handleEditSave = () => {
    onFeatureUpdate?.(feature.feature_id, {
      name: editName,
      description: editDescription,
    });
    setIsEditing(false);
  };

  const handleStartClick = () => {
    onStartClick?.(feature);
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="max-w-lg">
        <SheetHeader className="relative">
          <SheetClose onClose={() => onOpenChange(false)} />
          <div className="flex items-center gap-2 mb-2">
            <span className="mono text-sm text-slate-500">{feature.feature_id}</span>
            <span className={`text-xs px-1.5 py-0.5 rounded border mono font-medium ${colors.bg} ${colors.text} ${colors.border}`}>
              P{priority}
            </span>
            {feature.category && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-400 border border-slate-600">
                {feature.category}
              </span>
            )}
          </div>
          {isEditing ? (
            <Input
              value={editName}
              onChange={(e) => setEditName(e.target.value)}
              className="text-lg font-semibold"
              autoFocus
            />
          ) : (
            <SheetTitle>{feature.name}</SheetTitle>
          )}
        </SheetHeader>

        <SheetBody className="space-y-6">
          {/* Action Buttons */}
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              className="flex-1 gap-2"
              onClick={handleStartClick}
            >
              <Play className="h-4 w-4" />
              Start Task
            </Button>
            {isEditing ? (
              <>
                <Button variant="outline" size="sm" onClick={handleEditCancel}>
                  <X className="h-4 w-4" />
                </Button>
                <Button variant="primary" size="sm" onClick={handleEditSave}>
                  <Save className="h-4 w-4" />
                </Button>
              </>
            ) : (
              <Button variant="outline" size="sm" onClick={handleEditStart}>
                <Edit2 className="h-4 w-4" />
              </Button>
            )}
          </div>

          {/* Description */}
          <div>
            <h3 className="text-sm font-medium text-slate-400 mb-2">Description</h3>
            {isEditing ? (
              <Textarea
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
                rows={3}
                placeholder="Enter feature description..."
              />
            ) : (
              <p className="text-sm text-slate-300">
                {feature.description || <span className="italic text-slate-500">No description</span>}
              </p>
            )}
          </div>

          {/* Acceptance Criteria */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-slate-400">Acceptance Criteria</h3>
              {totalCount > 0 && (
                <span className={`text-sm mono font-medium ${allPassed ? "text-phosphor-400" : "text-slate-400"}`}>
                  {passedCount}/{totalCount}
                </span>
              )}
            </div>

            {/* Progress Bar */}
            {totalCount > 0 && (
              <div className="h-1.5 w-full bg-slate-700 rounded-full overflow-hidden mb-3">
                <div
                  className={`h-full transition-all duration-300 ${allPassed ? "bg-phosphor-500" : "bg-blue-500"}`}
                  style={{ width: `${progressPct}%` }}
                />
              </div>
            )}

            {/* Criteria List */}
            <div className="rounded-lg border border-slate-700 bg-slate-900/50">
              {criteria.length > 0 ? (
                <div className="divide-y divide-slate-800 p-3">
                  {criteria.map((criterion) => (
                    <CriterionRow key={criterion.id} criterion={criterion} />
                  ))}
                </div>
              ) : (
                <div className="p-4 text-center text-sm text-slate-500 italic">
                  No acceptance criteria defined
                </div>
              )}
            </div>
          </div>

          {/* Execution History */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-slate-400">Execution History</h3>
              {tasks.length > 0 && (
                <Badge variant="slate" className="text-xs">
                  {tasks.length}
                </Badge>
              )}
            </div>

            <div className="rounded-lg border border-slate-700 bg-slate-900/50">
              {tasksLoading ? (
                <div className="p-4 text-center">
                  <Loader2 className="h-4 w-4 animate-spin text-slate-500 mx-auto" />
                </div>
              ) : tasks.length > 0 ? (
                <div className="divide-y divide-slate-800 p-3">
                  {tasks.map((task) => (
                    <TaskRow key={task.id} task={task} />
                  ))}
                </div>
              ) : (
                <div className="p-4 text-center text-sm text-slate-500 italic">
                  No tasks executed yet
                </div>
              )}
            </div>
          </div>

          {/* Metadata */}
          <div className="text-xs text-slate-500 space-y-1 pt-4 border-t border-slate-800">
            {feature.created_at && (
              <p>Created: {new Date(feature.created_at).toLocaleDateString()}</p>
            )}
            {feature.last_verified_at && (
              <p>Last verified: {new Date(feature.last_verified_at).toLocaleDateString()}</p>
            )}
          </div>
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}
