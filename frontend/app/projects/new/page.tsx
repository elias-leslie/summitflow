"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FolderPlus, AlertCircle } from "lucide-react";
import Link from "next/link";
import { createProject } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

function generateProjectId(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 50);
}

export default function NewProjectPage() {
  const router = useRouter();
  const queryClient = useQueryClient();

  const [name, setName] = useState("");
  const [projectId, setProjectId] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [healthEndpoint, setHealthEndpoint] = useState("/api/health");
  const [errors, setErrors] = useState<Record<string, string>>({});

  const mutation = useMutation({
    mutationFn: createProject,
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      router.push(`/projects/${project.id}`);
    },
    onError: (error: Error) => {
      setErrors({ submit: error.message });
    },
  });

  const handleNameChange = (value: string) => {
    setName(value);
    if (!projectId || projectId === generateProjectId(name)) {
      setProjectId(generateProjectId(value));
    }
  };

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {};

    if (!name.trim()) {
      newErrors.name = "Project name is required";
    }
    if (!projectId.trim()) {
      newErrors.projectId = "Project ID is required";
    } else if (!/^[a-z0-9-]+$/.test(projectId)) {
      newErrors.projectId = "Project ID must be lowercase alphanumeric with hyphens";
    }
    if (!baseUrl.trim()) {
      newErrors.baseUrl = "Base URL is required";
    } else {
      try {
        new URL(baseUrl);
      } catch {
        newErrors.baseUrl = "Invalid URL format";
      }
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;

    mutation.mutate({
      id: projectId,
      name: name.trim(),
      base_url: baseUrl.trim(),
      health_endpoint: healthEndpoint.trim() || undefined,
    });
  };

  return (
    <div className="p-6 space-y-6 max-w-2xl mx-auto">
      {/* Header */}
      <header className="animate-in">
        <Link
          href="/"
          className="text-xs text-slate-500 hover:text-phosphor-400 flex items-center gap-1 mb-3 transition-colors"
        >
          <ArrowLeft className="w-3 h-3" />
          Back to Dashboard
        </Link>

        <div className="flex items-center gap-4">
          <div className="w-14 h-14 rounded-xl bg-slate-800 flex items-center justify-center">
            <FolderPlus className="w-7 h-7 text-phosphor-400" />
          </div>
          <div>
            <h1 className="display text-2xl font-semibold text-white">Create Project</h1>
            <p className="text-sm text-slate-400 mt-1">Register a new project for tracking</p>
          </div>
        </div>
      </header>

      {/* Form Card */}
      <form onSubmit={handleSubmit} className="card p-6 space-y-5">
        {/* Submit Error */}
        {errors.submit && (
          <div className="flex items-center gap-2 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
            <AlertCircle className="w-4 h-4 shrink-0" />
            {errors.submit}
          </div>
        )}

        {/* Project Name */}
        <div className="space-y-2">
          <Label htmlFor="name">Project Name *</Label>
          <Input
            id="name"
            value={name}
            onChange={(e) => handleNameChange(e.target.value)}
            placeholder="My Awesome Project"
            className={errors.name ? "border-red-500/50" : ""}
          />
          {errors.name && <p className="text-xs text-red-400">{errors.name}</p>}
        </div>

        {/* Project ID */}
        <div className="space-y-2">
          <Label htmlFor="projectId">Project ID *</Label>
          <Input
            id="projectId"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value.toLowerCase())}
            placeholder="my-awesome-project"
            className={`mono ${errors.projectId ? "border-red-500/50" : ""}`}
          />
          <p className="text-xs text-slate-500">
            Auto-generated from name. Must be lowercase alphanumeric with hyphens.
          </p>
          {errors.projectId && <p className="text-xs text-red-400">{errors.projectId}</p>}
        </div>

        {/* Base URL */}
        <div className="space-y-2">
          <Label htmlFor="baseUrl">Base URL *</Label>
          <Input
            id="baseUrl"
            type="url"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="https://example.com"
            className={errors.baseUrl ? "border-red-500/50" : ""}
          />
          <p className="text-xs text-slate-500">The root URL of your application</p>
          {errors.baseUrl && <p className="text-xs text-red-400">{errors.baseUrl}</p>}
        </div>

        {/* Health Endpoint */}
        <div className="space-y-2">
          <Label htmlFor="healthEndpoint">Health Endpoint</Label>
          <Input
            id="healthEndpoint"
            value={healthEndpoint}
            onChange={(e) => setHealthEndpoint(e.target.value)}
            placeholder="/api/health"
            className="mono"
          />
          <p className="text-xs text-slate-500">Endpoint for health checks (optional)</p>
        </div>

        {/* Submit Button */}
        <div className="flex items-center gap-3 pt-2">
          <button
            type="submit"
            disabled={mutation.isPending}
            className="btn-primary text-sm flex items-center gap-2"
          >
            {mutation.isPending ? (
              <>
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Creating...
              </>
            ) : (
              <>
                <FolderPlus className="w-4 h-4" />
                Create Project
              </>
            )}
          </button>
          <Link href="/" className="btn-secondary text-sm">
            Cancel
          </Link>
        </div>
      </form>
    </div>
  );
}
