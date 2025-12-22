"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Download, CheckCircle2, AlertTriangle, Loader2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { importTddTests, type ImportTestsResult } from "@/lib/api";

interface ImportTestsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
}

type SourceType = "pytest" | "vitest" | "playwright" | "all";

interface SourceOption {
  id: SourceType;
  name: string;
  description: string;
  color: string;
}

const SOURCE_OPTIONS: SourceOption[] = [
  {
    id: "pytest",
    name: "pytest",
    description: "Python unit/integration tests",
    color: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
  },
  {
    id: "vitest",
    name: "vitest",
    description: "JavaScript/TypeScript tests",
    color: "bg-cyan-500/20 text-cyan-400 border-cyan-500/30",
  },
  {
    id: "playwright",
    name: "playwright",
    description: "End-to-end browser tests",
    color: "bg-purple-500/20 text-purple-400 border-purple-500/30",
  },
];

export function ImportTestsDialog({
  open,
  onOpenChange,
  projectId,
}: ImportTestsDialogProps) {
  const queryClient = useQueryClient();
  const [selectedSources, setSelectedSources] = useState<Set<SourceType>>(new Set(["pytest", "vitest", "playwright"]));
  const [isImporting, setIsImporting] = useState(false);
  const [result, setResult] = useState<ImportTestsResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const toggleSource = (source: SourceType) => {
    setSelectedSources((prev) => {
      const next = new Set(prev);
      if (next.has(source)) {
        next.delete(source);
      } else {
        next.add(source);
      }
      return next;
    });
  };

  const handleImport = async () => {
    if (selectedSources.size === 0) return;

    setIsImporting(true);
    setError(null);
    setResult(null);

    try {
      // If all sources selected, use "all"
      const sourceType = selectedSources.size === SOURCE_OPTIONS.length ? "all" : Array.from(selectedSources).join(",");
      const importResult = await importTddTests(projectId, sourceType, true);
      setResult(importResult);
      // Refresh tests list
      queryClient.invalidateQueries({ queryKey: ["tdd-tests", projectId] });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to import tests");
    } finally {
      setIsImporting(false);
    }
  };

  const handleClose = () => {
    if (!isImporting) {
      setResult(null);
      setError(null);
      onOpenChange(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="w-full max-w-md">
        <DialogHeader>
          <DialogTitle>Import Tests</DialogTitle>
          <DialogDescription>
            Discover and import existing tests from your project
          </DialogDescription>
          <DialogClose onClose={handleClose} />
        </DialogHeader>

        <div className="p-5 space-y-5">
          {!result ? (
            <>
              {/* Source Selection */}
              <div className="space-y-3">
                <label className="text-xs font-medium text-slate-400 uppercase tracking-wider">
                  Test Sources
                </label>
                {SOURCE_OPTIONS.map((source) => (
                  <div
                    key={source.id}
                    className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                      selectedSources.has(source.id)
                        ? "border-phosphor-500/50 bg-phosphor-500/5"
                        : "border-slate-700 bg-slate-800/30 hover:bg-slate-800/50"
                    }`}
                    onClick={() => toggleSource(source.id)}
                  >
                    <Checkbox
                      checked={selectedSources.has(source.id)}
                      onCheckedChange={() => toggleSource(source.id)}
                    />
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className={`text-xs px-2 py-0.5 rounded border font-medium ${source.color}`}>
                          {source.name}
                        </span>
                      </div>
                      <p className="text-xs text-slate-500 mt-1">{source.description}</p>
                    </div>
                  </div>
                ))}
              </div>

              {/* Error */}
              {error && (
                <div className="flex items-center gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-rose-400 text-sm">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              {/* Actions */}
              <div className="flex gap-3 pt-2">
                <Button variant="outline" onClick={handleClose} disabled={isImporting} className="flex-1">
                  Cancel
                </Button>
                <Button
                  onClick={handleImport}
                  disabled={selectedSources.size === 0 || isImporting}
                  className="flex-1"
                >
                  {isImporting ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      Importing...
                    </>
                  ) : (
                    <>
                      <Download className="h-4 w-4 mr-2" />
                      Import Tests
                    </>
                  )}
                </Button>
              </div>
            </>
          ) : (
            <>
              {/* Results */}
              <div className="text-center">
                <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-phosphor-500/20 mb-4">
                  <CheckCircle2 className="h-6 w-6 text-phosphor-400" />
                </div>
                <h3 className="text-lg font-semibold text-white mb-2">Import Complete</h3>
                <div className="flex justify-center gap-4 text-sm">
                  <div>
                    <span className="text-2xl font-bold text-phosphor-400 mono">{result.imported_count}</span>
                    <div className="text-slate-500">imported</div>
                  </div>
                  <div>
                    <span className="text-2xl font-bold text-amber-400 mono">{result.skipped_count}</span>
                    <div className="text-slate-500">skipped</div>
                  </div>
                </div>
              </div>

              {/* Errors */}
              {result.errors.length > 0 && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
                  <div className="text-xs font-medium text-amber-400 mb-2">Warnings</div>
                  <ul className="text-xs text-amber-300 space-y-1">
                    {result.errors.map((err, i) => (
                      <li key={i}>{err}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Imported tests preview */}
              {result.tests.length > 0 && (
                <div className="max-h-48 overflow-y-auto space-y-1">
                  {result.tests.slice(0, 10).map((test) => (
                    <div
                      key={test.test_id}
                      className="flex items-center gap-2 px-2 py-1.5 rounded bg-slate-800/50 text-xs"
                    >
                      <Badge variant="slate" className="text-xs">
                        {test.test_type}
                      </Badge>
                      <span className="text-slate-300 truncate">{test.name}</span>
                    </div>
                  ))}
                  {result.tests.length > 10 && (
                    <div className="text-xs text-slate-500 text-center py-1">
                      +{result.tests.length - 10} more tests
                    </div>
                  )}
                </div>
              )}

              {/* Close button */}
              <Button onClick={handleClose} className="w-full">
                Done
              </Button>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
