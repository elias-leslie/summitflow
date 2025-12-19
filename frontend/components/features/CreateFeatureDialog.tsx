"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

interface CreateFeatureDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
}

interface AcceptanceCriterion {
  id: string;
  description: string;
}

const CATEGORY_OPTIONS = [
  "ui",
  "backend",
  "api",
  "database",
  "infrastructure",
  "security",
  "performance",
  "testing",
  "documentation",
  "other",
];

const PRIORITY_OPTIONS = [
  { value: 0, label: "P0 - Critical" },
  { value: 1, label: "P1 - High" },
  { value: 2, label: "P2 - Medium" },
  { value: 3, label: "P3 - Low" },
  { value: 4, label: "P4 - Backlog" },
];

export function CreateFeatureDialog({
  open,
  onOpenChange,
  projectId,
}: CreateFeatureDialogProps) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [category, setCategory] = useState("ui");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState(2);
  const [criteria, setCriteria] = useState<AcceptanceCriterion[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resetForm = () => {
    setName("");
    setCategory("ui");
    setDescription("");
    setPriority(2);
    setCriteria([]);
    setError(null);
  };

  const handleClose = () => {
    resetForm();
    onOpenChange(false);
  };

  const addCriterion = () => {
    setCriteria([
      ...criteria,
      { id: `ac-${Date.now()}`, description: "" },
    ]);
  };

  const removeCriterion = (id: string) => {
    setCriteria(criteria.filter((c) => c.id !== id));
  };

  const updateCriterion = (id: string, description: string) => {
    setCriteria(
      criteria.map((c) => (c.id === id ? { ...c, description } : c))
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!name.trim()) {
      setError("Name is required");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      // Create the feature
      const res = await fetch(`/api/projects/${projectId}/features`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          category,
          description: description.trim() || null,
          priority,
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || "Failed to create feature");
      }

      const result = await res.json();
      const featureId = result.feature_id;

      // Add acceptance criteria if any
      for (const criterion of criteria) {
        if (criterion.description.trim()) {
          await fetch(
            `/api/projects/${projectId}/features/${featureId}/criteria`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                description: criterion.description.trim(),
              }),
            }
          );
        }
      }

      // Invalidate queries to refresh the list
      queryClient.invalidateQueries({ queryKey: ["features", projectId] });

      handleClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create feature");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="w-full max-w-lg">
        <DialogClose onClose={handleClose} />
        <DialogHeader>
          <DialogTitle>Create Feature</DialogTitle>
          <DialogDescription>
            Add a new feature to track and verify
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">
              Name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Feature name"
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-md text-white
                placeholder:text-slate-500 focus:border-phosphor-500 focus:ring-1 focus:ring-phosphor-500"
              required
            />
          </div>

          {/* Category */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">
              Category
            </label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-md text-white
                focus:border-phosphor-500 focus:ring-1 focus:ring-phosphor-500"
            >
              {CATEGORY_OPTIONS.map((cat) => (
                <option key={cat} value={cat}>
                  {cat.charAt(0).toUpperCase() + cat.slice(1)}
                </option>
              ))}
            </select>
          </div>

          {/* Priority */}
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

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Feature description (optional)"
              rows={3}
              className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-md text-white
                placeholder:text-slate-500 focus:border-phosphor-500 focus:ring-1 focus:ring-phosphor-500 resize-none"
            />
          </div>

          {/* Acceptance Criteria */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-sm font-medium text-slate-300">
                Acceptance Criteria
              </label>
              <button
                type="button"
                onClick={addCriterion}
                className="flex items-center gap-1 text-xs text-phosphor-400 hover:text-phosphor-300"
              >
                <Plus className="w-3 h-3" />
                Add Criterion
              </button>
            </div>
            {criteria.length === 0 ? (
              <p className="text-sm text-slate-500 italic">
                No acceptance criteria yet
              </p>
            ) : (
              <div className="space-y-2">
                {criteria.map((criterion, index) => (
                  <div key={criterion.id} className="flex items-start gap-2">
                    <span className="text-xs text-slate-500 mt-2.5 w-6">
                      {index + 1}.
                    </span>
                    <input
                      type="text"
                      value={criterion.description}
                      onChange={(e) =>
                        updateCriterion(criterion.id, e.target.value)
                      }
                      placeholder="Criterion description"
                      className="flex-1 px-3 py-2 bg-slate-800 border border-slate-700 rounded-md text-white
                        placeholder:text-slate-500 focus:border-phosphor-500 focus:ring-1 focus:ring-phosphor-500 text-sm"
                    />
                    <button
                      type="button"
                      onClick={() => removeCriterion(criterion.id)}
                      className="p-2 text-slate-500 hover:text-red-400 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}
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
                "Create Feature"
              )}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
