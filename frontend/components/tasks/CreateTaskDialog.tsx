"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { fetchFeatures, createTask, type TaskType } from "@/lib/api";

interface CreateTaskDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
}

const PRIORITY_OPTIONS = [
  { value: 0, label: "P0 - Critical" },
  { value: 1, label: "P1 - High" },
  { value: 2, label: "P2 - Medium" },
  { value: 3, label: "P3 - Low" },
  { value: 4, label: "P4 - Backlog" },
];

const TYPE_OPTIONS: { value: TaskType; label: string }[] = [
  { value: "feature", label: "Feature" },
  { value: "bug", label: "Bug" },
  { value: "task", label: "Task" },
];

export function CreateTaskDialog({
  open,
  onOpenChange,
  projectId,
}: CreateTaskDialogProps) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState(2);
  const [taskType, setTaskType] = useState<TaskType>("task");
  const [featureId, setFeatureId] = useState<number | null>(null);
  const [labels, setLabels] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch features for the select dropdown
  const { data: featuresData } = useQuery({
    queryKey: ["features", projectId],
    queryFn: () => fetchFeatures(projectId, { limit: 100 }),
    enabled: open,
  });

  const features = featuresData?.features ?? [];

  const resetForm = () => {
    setTitle("");
    setDescription("");
    setPriority(2);
    setTaskType("task");
    setFeatureId(null);
    setLabels("");
    setError(null);
  };

  const handleClose = () => {
    resetForm();
    onOpenChange(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!title.trim()) {
      setError("Title is required");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const labelsArray = labels
        .split(",")
        .map((l) => l.trim())
        .filter((l) => l);

      await createTask(projectId, {
        title: title.trim(),
        description: description.trim() || undefined,
        priority,
        task_type: taskType,
        feature_id: featureId ?? undefined,
        labels: labelsArray.length > 0 ? labelsArray : undefined,
      });

      // Invalidate queries to refresh the list
      queryClient.invalidateQueries({ queryKey: ["tasks", projectId] });

      handleClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create task");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="w-full max-w-lg">
        <DialogClose onClose={handleClose} />
        <DialogHeader>
          <DialogTitle>Create Task</DialogTitle>
          <DialogDescription>
            Add a new task to track work
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* Title */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">
              Title <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Brief description of the task"
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-md text-white
                placeholder:text-slate-500 focus:border-phosphor-500 focus:ring-1 focus:ring-phosphor-500"
              required
            />
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Detailed description (optional)"
              rows={3}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-md text-white
                placeholder:text-slate-500 focus:border-phosphor-500 focus:ring-1 focus:ring-phosphor-500 resize-none"
            />
          </div>

          {/* Priority and Type */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">
                Priority
              </label>
              <select
                value={priority}
                onChange={(e) => setPriority(parseInt(e.target.value))}
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-md text-white
                  focus:border-phosphor-500 focus:ring-1 focus:ring-phosphor-500"
              >
                {PRIORITY_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">
                Type
              </label>
              <select
                value={taskType}
                onChange={(e) => setTaskType(e.target.value as TaskType)}
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-md text-white
                  focus:border-phosphor-500 focus:ring-1 focus:ring-phosphor-500"
              >
                {TYPE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Feature (optional) */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">
              Linked Feature
            </label>
            <select
              value={featureId ?? ""}
              onChange={(e) => setFeatureId(e.target.value ? parseInt(e.target.value) : null)}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-md text-white
                focus:border-phosphor-500 focus:ring-1 focus:ring-phosphor-500"
            >
              <option value="">No feature linked</option>
              {features.filter(f => f.id !== null).map((feature) => (
                <option key={feature.id} value={feature.id!}>
                  {feature.feature_id} - {feature.name}
                </option>
              ))}
            </select>
          </div>

          {/* Labels */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">
              Labels (comma-separated)
            </label>
            <input
              type="text"
              value={labels}
              onChange={(e) => setLabels(e.target.value)}
              placeholder="complexity:small, domains:backend"
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-md text-white
                placeholder:text-slate-500 focus:border-phosphor-500 focus:ring-1 focus:ring-phosphor-500"
            />
          </div>

          {/* Error */}
          {error && (
            <div className="p-3 bg-red-950/50 border border-red-800 rounded-md">
              <p className="text-sm text-red-400">{error}</p>
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-4 border-t border-slate-800">
            <Button type="button" variant="ghost" onClick={handleClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={loading}>
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Creating...
                </>
              ) : (
                "Create Task"
              )}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
