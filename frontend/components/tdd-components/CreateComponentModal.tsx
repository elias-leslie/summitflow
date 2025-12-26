"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { createTddComponent, type CreateComponentRequest } from "@/lib/api";

interface CreateComponentModalProps {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess?: () => void;
}

export function CreateComponentModal({
  projectId,
  open,
  onOpenChange,
  onSuccess,
}: CreateComponentModalProps) {
  const [name, setName] = useState("");
  const [componentId, setComponentId] = useState("");
  const [description, setDescription] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Auto-generate component_id from name
  const handleNameChange = (value: string) => {
    setName(value);
    // Generate component_id: lowercase, replace spaces with underscores
    const generated = value
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, "")
      .replace(/\s+/g, "_")
      .slice(0, 50);
    setComponentId(generated);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !componentId.trim()) return;

    setIsSubmitting(true);
    setError(null);

    try {
      const request: CreateComponentRequest = {
        component_id: componentId,
        name: name.trim(),
        description: description.trim() || undefined,
      };
      await createTddComponent(projectId, request);

      // Reset form
      setName("");
      setComponentId("");
      setDescription("");
      onOpenChange(false);
      onSuccess?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create component");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleClose = () => {
    if (!isSubmitting) {
      setName("");
      setComponentId("");
      setDescription("");
      setError(null);
      onOpenChange(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="w-full max-w-md">
        <DialogClose onClose={handleClose} />
        <DialogHeader>
          <DialogTitle>Create Component</DialogTitle>
          <DialogDescription>
            Add a new component to track capabilities for.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {/* Name */}
          <div className="space-y-1.5">
            <label htmlFor="name" className="text-sm font-medium text-slate-300">
              Name <span className="text-red-400">*</span>
            </label>
            <Input
              id="name"
              value={name}
              onChange={(e) => handleNameChange(e.target.value)}
              placeholder="e.g., User Authentication"
              disabled={isSubmitting}
              required
            />
          </div>

          {/* Component ID */}
          <div className="space-y-1.5">
            <label htmlFor="componentId" className="text-sm font-medium text-slate-300">
              Component ID <span className="text-red-400">*</span>
            </label>
            <Input
              id="componentId"
              value={componentId}
              onChange={(e) => setComponentId(e.target.value)}
              placeholder="e.g., user_authentication"
              disabled={isSubmitting}
              required
            />
            <p className="text-xs text-slate-500">
              Auto-generated from name. Must be unique.
            </p>
          </div>

          {/* Description */}
          <div className="space-y-1.5">
            <label htmlFor="description" className="text-sm font-medium text-slate-300">
              Description
            </label>
            <textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this component do?"
              disabled={isSubmitting}
              rows={3}
              className="w-full rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-sm
                text-slate-100 placeholder:text-slate-500 focus:border-phosphor-500
                focus:outline-none focus:ring-1 focus:ring-phosphor-500 disabled:opacity-50"
            />
          </div>

          {/* Error message */}
          {error && (
            <div className="text-sm text-red-400 bg-red-400/10 rounded-md px-3 py-2">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-2">
            <Button
              type="button"
              variant="outline"
              onClick={handleClose}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={isSubmitting || !name.trim() || !componentId.trim()}
            >
              {isSubmitting && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              Create Component
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
