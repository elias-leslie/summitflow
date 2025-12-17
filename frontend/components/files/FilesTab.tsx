/**
 * Files Tab - Explorer with Inline Details
 *
 * Unified file explorer with:
 * - Tree/table hybrid view (folders expand to show files)
 * - Sortable columns (Name, Files, LOC, Size)
 * - Color indicators for bloat (left border + colored text)
 * - Inline details expansion (click row to show details below)
 */

"use client";

import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Folder,
  FolderOpen,
  File,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  Loader2,
  Home,
  ChevronRightIcon,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  X,
  GitCommit as GitCommitIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  fetchFileSummary,
  fetchFileChildren,
  fetchGitHistory,
  triggerFileScan,
  type FileNode,
  type FileSortField,
  type SortDir,
} from "@/lib/api";
import { cn } from "@/lib/utils";

interface FilesTabProps {
  projectId: string;
}

// Helper functions
const formatNumber = (n: number | undefined | null) => (n ?? 0).toLocaleString();
const formatBytes = (bytes: number | undefined | null) => {
  const b = bytes ?? 0;
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / (1024 * 1024)).toFixed(1)} MB`;
};

const formatDate = (dateStr: string | null) => {
  if (!dateStr) return "-";
  const date = new Date(dateStr);
  return date.toLocaleDateString();
};

// Inline Details Component
function InlineDetails({
  projectId,
  node,
  onClose,
  depth,
}: {
  projectId: string;
  node: FileNode;
  onClose: () => void;
  depth: number;
}) {
  const isDir = node.isDirectory;
  const loc = isDir ? node.totalLoc || 0 : node.linesOfCode;
  const bloatStatus = node.bloatLevel;
  const staleStatus = node.staleStatus;

  // Fetch git history for files only
  const { data: gitHistory, isLoading: historyLoading } = useQuery({
    queryKey: ["files", projectId, "history", node.path],
    queryFn: () => fetchGitHistory(projectId, node.path),
    enabled: !isDir,
    staleTime: 60000,
  });

  return (
    <div
      className={cn(
        "mx-2 mb-1 rounded border bg-gray-50 dark:bg-gray-900",
        bloatStatus === "critical" && "border-red-300 bg-red-50 dark:bg-red-950",
        bloatStatus === "warning" && "border-yellow-300 bg-yellow-50 dark:bg-yellow-950",
        !bloatStatus && "border-gray-200 dark:border-gray-700"
      )}
      style={{ marginLeft: depth * 20 + 8 }}
    >
      <div className="p-3">
        {/* Header row */}
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="flex items-center gap-2">
            {isDir ? (
              <Folder className="h-4 w-4 text-blue-500" />
            ) : (
              <File className="h-4 w-4 text-gray-500" />
            )}
            <span className="font-medium text-sm">{node.name}</span>
            {bloatStatus && (
              <Badge
                variant={bloatStatus === "critical" ? "rose" : bloatStatus === "warning" ? "amber" : "outline"}
                className="text-xs"
              >
                {bloatStatus}
              </Badge>
            )}
            {staleStatus && staleStatus !== "fresh" && (
              <Badge variant="outline" className="text-xs">
                {staleStatus}
              </Badge>
            )}
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} className="h-6 w-6 p-0">
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>

        {/* Path */}
        <div className="text-xs text-gray-500 mb-2 font-mono truncate">{node.path}</div>

        {/* Stats grid */}
        <div className="grid grid-cols-4 gap-2 text-xs">
          <div className="bg-white dark:bg-gray-800 rounded px-2 py-1.5">
            <div className="text-gray-500">LOC</div>
            <div
              className={cn(
                "font-semibold",
                bloatStatus === "critical" && "text-red-500",
                bloatStatus === "warning" && "text-yellow-500"
              )}
            >
              {formatNumber(loc)}
            </div>
          </div>
          <div className="bg-white dark:bg-gray-800 rounded px-2 py-1.5">
            <div className="text-gray-500">Size</div>
            <div className="font-semibold">{formatBytes(node.sizeBytes)}</div>
          </div>
          {isDir ? (
            <>
              <div className="bg-white dark:bg-gray-800 rounded px-2 py-1.5">
                <div className="text-gray-500">Files</div>
                <div className="font-semibold">{formatNumber(node.fileCount)}</div>
              </div>
              <div className="bg-white dark:bg-gray-800 rounded px-2 py-1.5">
                <div className="text-gray-500">Subdirs</div>
                <div className="font-semibold">{formatNumber(node.subdirCount)}</div>
              </div>
            </>
          ) : (
            <>
              <div className="bg-white dark:bg-gray-800 rounded px-2 py-1.5">
                <div className="text-gray-500">Type</div>
                <div className="font-semibold">{node.extension || "-"}</div>
              </div>
              <div className="bg-white dark:bg-gray-800 rounded px-2 py-1.5">
                <div className="text-gray-500">Modified</div>
                <div className="font-semibold">{formatDate(node.lastModified)}</div>
              </div>
            </>
          )}
        </div>

        {/* Stale info row - only show for files with stale data */}
        {!isDir && (node.lastCommitDays !== null || node.referenceCount !== null) && (
          <div className="grid grid-cols-2 gap-2 text-xs mt-2">
            <div className="bg-white dark:bg-gray-800 rounded px-2 py-1.5">
              <div className="text-gray-500">Last Commit</div>
              <div
                className={cn(
                  "font-semibold",
                  node.lastCommitDays !== null && node.lastCommitDays >= 90 && "text-orange-500"
                )}
              >
                {node.lastCommitDays !== null ? `${node.lastCommitDays} days ago` : "-"}
              </div>
            </div>
            <div className="bg-white dark:bg-gray-800 rounded px-2 py-1.5">
              <div className="text-gray-500">References</div>
              <div className={cn("font-semibold", node.referenceCount === 0 && "text-orange-500")}>
                {node.referenceCount ?? "-"}
              </div>
            </div>
          </div>
        )}

        {/* Git History section - for files only */}
        {!isDir && (
          <div className="mt-3 pt-2 border-t border-gray-200 dark:border-gray-700">
            <div className="flex items-center gap-2 mb-2">
              <GitCommitIcon className="h-3.5 w-3.5 text-gray-500" />
              <span className="text-xs font-medium text-gray-500">
                Recent Commits
                {gitHistory?.totalCommits ? ` (${gitHistory.totalCommits} total)` : ""}
              </span>
            </div>
            {historyLoading ? (
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <Loader2 className="h-3 w-3 animate-spin" />
                <span>Loading history...</span>
              </div>
            ) : gitHistory?.error ? (
              <div className="text-xs text-gray-500 italic">{gitHistory.error}</div>
            ) : gitHistory?.commits.length === 0 ? (
              <div className="text-xs text-gray-500 italic">No git history found</div>
            ) : (
              <div className="space-y-1.5">
                {gitHistory?.commits.slice(0, 3).map((commit) => (
                  <div
                    key={commit.fullHash}
                    className="flex items-start gap-2 text-xs bg-white dark:bg-gray-800 rounded px-2 py-1.5"
                  >
                    <span className="font-mono text-blue-500 flex-shrink-0">{commit.hash}</span>
                    <div className="flex-1 min-w-0">
                      <div className="truncate" title={commit.subject}>
                        {commit.subject}
                      </div>
                      <div className="text-gray-500">
                        {commit.author} · {new Date(commit.date).toLocaleDateString()}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// File Row Component
function FileRow({
  projectId,
  node,
  depth,
  isExpanded,
  isDetailsOpen,
  isLoading,
  onToggleExpand,
  onToggleDetails,
  children,
}: {
  projectId: string;
  node: FileNode;
  depth: number;
  isExpanded: boolean;
  isDetailsOpen: boolean;
  isLoading: boolean;
  onToggleExpand: () => void;
  onToggleDetails: () => void;
  children?: React.ReactNode;
}) {
  const isDir = node.isDirectory;
  const loc = isDir ? node.totalLoc || 0 : node.linesOfCode;
  const bloatBorder =
    node.bloatLevel === "critical"
      ? "border-l-red-500"
      : node.bloatLevel === "warning"
        ? "border-l-yellow-500"
        : "border-l-transparent";

  return (
    <>
      <div
        className={cn(
          "flex items-center py-1.5 px-2 hover:bg-gray-100 dark:hover:bg-gray-800 cursor-pointer border-l-2",
          bloatBorder,
          isDetailsOpen && "bg-gray-100 dark:bg-gray-800"
        )}
        style={{ paddingLeft: depth * 20 + 8 }}
        onClick={onToggleDetails}
      >
        {/* Expand chevron */}
        {isDir ? (
          <button
            className="p-0.5 hover:bg-gray-200 dark:hover:bg-gray-700 rounded mr-1"
            onClick={(e) => {
              e.stopPropagation();
              onToggleExpand();
            }}
          >
            {isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin text-gray-400" />
            ) : isExpanded ? (
              <ChevronDown className="h-4 w-4 text-gray-500" />
            ) : (
              <ChevronRight className="h-4 w-4 text-gray-500" />
            )}
          </button>
        ) : (
          <span className="w-5" />
        )}

        {/* Icon */}
        {isDir ? (
          isExpanded ? (
            <FolderOpen className="h-4 w-4 text-blue-500 mr-2 flex-shrink-0" />
          ) : (
            <Folder className="h-4 w-4 text-blue-500 mr-2 flex-shrink-0" />
          )
        ) : (
          <File className="h-4 w-4 text-gray-500 mr-2 flex-shrink-0" />
        )}

        {/* Name */}
        <span
          className={cn(
            "flex-1 truncate text-sm",
            node.bloatLevel === "critical" && "text-red-500 font-medium",
            node.bloatLevel === "warning" && "text-yellow-600"
          )}
          title={node.path}
        >
          {node.name}
        </span>

        {/* Stats columns */}
        <span className="w-16 text-right text-xs text-gray-500">
          {isDir ? formatNumber(node.fileCount) : "-"}
        </span>
        <span
          className={cn(
            "w-16 text-right text-xs",
            node.bloatLevel === "critical" && "text-red-500",
            node.bloatLevel === "warning" && "text-yellow-500",
            !node.bloatLevel && "text-gray-500"
          )}
        >
          {formatNumber(loc)}
        </span>
        <span className="w-20 text-right text-xs text-gray-500">{formatBytes(node.sizeBytes)}</span>
      </div>

      {/* Inline details panel */}
      {isDetailsOpen && (
        <InlineDetails
          projectId={projectId}
          node={node}
          onClose={onToggleDetails}
          depth={depth}
        />
      )}

      {/* Children */}
      {isExpanded && children}
    </>
  );
}

// Main Component
export function FilesTab({ projectId }: FilesTabProps) {
  const queryClient = useQueryClient();

  // State
  const [sortField, setSortField] = useState<FileSortField>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [foldersFirst, setFoldersFirst] = useState(true);
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(new Set());
  const [detailsOpenPaths, setDetailsOpenPaths] = useState<Set<string>>(new Set());
  const [loadedChildren, setLoadedChildren] = useState<Map<string, FileNode[]>>(new Map());
  const [loadingPaths, setLoadingPaths] = useState<Set<string>>(new Set());
  const [currentPath, setCurrentPath] = useState<string[]>([]);

  // Queries
  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ["files", projectId, "summary"],
    queryFn: () => fetchFileSummary(projectId),
  });

  const rootPath = currentPath.join("/");
  const { data: rootChildren, isLoading: rootLoading } = useQuery({
    queryKey: ["files", projectId, "children", rootPath, sortField, sortDir, foldersFirst],
    queryFn: () => fetchFileChildren(projectId, rootPath, sortField, sortDir, foldersFirst),
  });

  // Mutations
  const scanMutation = useMutation({
    mutationFn: () => triggerFileScan(projectId),
    onSuccess: () => {
      alert("File scan started");
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["files", projectId] });
        setLoadedChildren(new Map());
        setExpandedPaths(new Set());
        setDetailsOpenPaths(new Set());
      }, 5000);
    },
    onError: () => alert("Failed to start scan"),
  });

  // Handlers
  const loadChildren = useCallback(
    async (path: string) => {
      if (loadedChildren.has(path)) return;
      setLoadingPaths((prev) => new Set(prev).add(path));
      try {
        const children = await fetchFileChildren(projectId, path, sortField, sortDir, foldersFirst);
        setLoadedChildren((prev) => new Map(prev).set(path, children));
      } finally {
        setLoadingPaths((prev) => {
          const next = new Set(prev);
          next.delete(path);
          return next;
        });
      }
    },
    [projectId, sortField, sortDir, foldersFirst, loadedChildren]
  );

  const toggleExpand = useCallback(
    (path: string) => {
      setExpandedPaths((prev) => {
        const next = new Set(prev);
        if (next.has(path)) {
          next.delete(path);
        } else {
          next.add(path);
          loadChildren(path);
        }
        return next;
      });
    },
    [loadChildren]
  );

  const toggleDetails = useCallback((path: string) => {
    setDetailsOpenPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }, []);

  const handleSort = (field: FileSortField) => {
    if (sortField === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDir("asc");
    }
    // Clear loaded children to refresh with new sort
    setLoadedChildren(new Map());
    setExpandedPaths(new Set());
  };

  const navigateTo = useCallback((pathIndex: number) => {
    setCurrentPath((prev) => prev.slice(0, pathIndex));
    setExpandedPaths(new Set());
    setDetailsOpenPaths(new Set());
    setLoadedChildren(new Map());
  }, []);

  const navigateInto = useCallback((folderName: string) => {
    setCurrentPath((prev) => [...prev, folderName]);
    setExpandedPaths(new Set());
    setDetailsOpenPaths(new Set());
    setLoadedChildren(new Map());
  }, []);

  // Render tree recursively
  const renderTree = (nodes: FileNode[], depth: number) => {
    return nodes.map((node) => {
      const children = loadedChildren.get(node.path) || [];
      const isExpanded = expandedPaths.has(node.path);
      const isLoading = loadingPaths.has(node.path);
      const isDetailsOpen = detailsOpenPaths.has(node.path);

      return (
        <FileRow
          key={node.path}
          projectId={projectId}
          node={node}
          depth={depth}
          isExpanded={isExpanded}
          isDetailsOpen={isDetailsOpen}
          isLoading={isLoading}
          onToggleExpand={() => toggleExpand(node.path)}
          onToggleDetails={() => toggleDetails(node.path)}
        >
          {isExpanded && children.length > 0 && renderTree(children, depth + 1)}
        </FileRow>
      );
    });
  };

  // Sort icon component
  const SortIcon = ({ field }: { field: FileSortField }) => {
    if (sortField !== field) return <ArrowUpDown className="h-3 w-3 ml-1 text-gray-400" />;
    return sortDir === "asc" ? (
      <ArrowUp className="h-3 w-3 ml-1 text-blue-500" />
    ) : (
      <ArrowDown className="h-3 w-3 ml-1 text-blue-500" />
    );
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 p-4 border-b">
        <div className="flex items-center gap-4">
          <h2 className="text-lg font-semibold">Files</h2>
          {summary && (
            <div className="flex items-center gap-3 text-sm text-gray-500">
              <span>{formatNumber(summary.totalFiles)} files</span>
              <span>{formatNumber(summary.totalLoc)} LOC</span>
              {(summary.bloatWarnings > 0 || summary.bloatCritical > 0) && (
                <Badge variant="amber">
                  {summary.bloatWarnings + summary.bloatCritical} bloated
                </Badge>
              )}
            </div>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => scanMutation.mutate()}
          disabled={scanMutation.isPending}
        >
          {scanMutation.isPending ? (
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4 mr-2" />
          )}
          Scan Files
        </Button>
      </div>

      {/* Breadcrumb */}
      <div className="flex items-center gap-1 px-4 py-2 text-sm border-b bg-gray-50 dark:bg-gray-900">
        <Button
          variant="ghost"
          size="sm"
          className="h-6 px-2"
          onClick={() => navigateTo(0)}
          disabled={currentPath.length === 0}
        >
          <Home className="h-3.5 w-3.5" />
        </Button>
        {currentPath.map((segment, i) => (
          <div key={i} className="flex items-center gap-1">
            <ChevronRightIcon className="h-3.5 w-3.5 text-gray-400" />
            <Button
              variant="ghost"
              size="sm"
              className="h-6 px-2"
              onClick={() => navigateTo(i + 1)}
            >
              {segment}
            </Button>
          </div>
        ))}
      </div>

      {/* Column headers */}
      <div className="flex items-center py-2 px-2 text-xs font-medium text-gray-500 bg-gray-50 dark:bg-gray-900 border-b">
        <button
          className="flex items-center flex-1 pl-7 hover:text-gray-700 dark:hover:text-gray-300"
          onClick={() => handleSort("name")}
        >
          Name <SortIcon field="name" />
        </button>
        <button
          className="flex items-center justify-end w-16 hover:text-gray-700 dark:hover:text-gray-300"
          onClick={() => handleSort("files")}
        >
          Files <SortIcon field="files" />
        </button>
        <button
          className="flex items-center justify-end w-16 hover:text-gray-700 dark:hover:text-gray-300"
          onClick={() => handleSort("loc")}
        >
          LOC <SortIcon field="loc" />
        </button>
        <button
          className="flex items-center justify-end w-20 hover:text-gray-700 dark:hover:text-gray-300"
          onClick={() => handleSort("size")}
        >
          Size <SortIcon field="size" />
        </button>
      </div>

      {/* File tree */}
      <div className="flex-1 overflow-auto">
        {rootLoading ? (
          <div className="flex items-center justify-center p-8">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
          </div>
        ) : rootChildren?.length === 0 ? (
          <div className="flex items-center justify-center p-8 text-gray-500">
            No files found. Try running a scan.
          </div>
        ) : (
          rootChildren && renderTree(rootChildren, 0)
        )}
      </div>
    </div>
  );
}
