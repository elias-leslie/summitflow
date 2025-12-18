/**
 * Explorer Type Registry
 *
 * Central configuration for all explorer types.
 * Each type provides columns, row renderer, and detail renderer.
 */

import { Folder, Database, Zap, Globe, FileText } from "lucide-react";
import type { ExplorerColumn, ExplorerType as UIExplorerType } from "../types";
import type { ExplorerEntry, ExplorerEntryType } from "@/lib/api/explorer";

// Re-export type-specific components
export * from "./files";
export * from "./database";
export * from "./tasks";
export * from "./endpoints";
export * from "./pages";

// Import columns
import { fileColumns } from "./files";
import { tableColumns } from "./database";
import { taskColumns } from "./tasks";
import { endpointColumns } from "./endpoints";
import { pageColumns } from "./pages";

// Import row/detail components
import { FileRow, FileDetail } from "./files";
import { TableRow, TableDetail } from "./database";
import { TaskRow, TaskDetail } from "./tasks";
import { EndpointRow, EndpointDetail } from "./endpoints";
import { PageRow, PageDetail } from "./pages";

/**
 * Type configuration with all rendering info
 */
export interface ExplorerTypeConfig {
  /** API entry type */
  entryType: ExplorerEntryType;
  /** UI display type */
  uiType: UIExplorerType;
  /** Display label */
  label: string;
  /** Icon component */
  icon: typeof Folder;
  /** Brand color class */
  colorClass: string;
  /** Column definitions */
  columns: ExplorerColumn<ExplorerEntry>[];
  /** Row content renderer */
  RowComponent: React.ComponentType<{ entry: ExplorerEntry }>;
  /** Detail panel renderer */
  DetailComponent: React.ComponentType<{ entry: ExplorerEntry }>;
}

/**
 * Type configurations registry
 */
export const typeConfigs: Record<ExplorerEntryType, ExplorerTypeConfig> = {
  file: {
    entryType: "file",
    uiType: "files",
    label: "Files",
    icon: Folder,
    colorClass: "text-amber-500",
    columns: fileColumns,
    RowComponent: FileRow,
    DetailComponent: FileDetail,
  },
  table: {
    entryType: "table",
    uiType: "database",
    label: "Database",
    icon: Database,
    colorClass: "text-emerald-500",
    columns: tableColumns,
    RowComponent: TableRow,
    DetailComponent: TableDetail,
  },
  task: {
    entryType: "task",
    uiType: "celery",
    label: "Tasks",
    icon: Zap,
    colorClass: "text-yellow-500",
    columns: taskColumns,
    RowComponent: TaskRow,
    DetailComponent: TaskDetail,
  },
  endpoint: {
    entryType: "endpoint",
    uiType: "api",
    label: "Endpoints",
    icon: Globe,
    colorClass: "text-cyan-500",
    columns: endpointColumns,
    RowComponent: EndpointRow,
    DetailComponent: EndpointDetail,
  },
  page: {
    entryType: "page",
    uiType: "pages",
    label: "Pages",
    icon: FileText,
    colorClass: "text-purple-500",
    columns: pageColumns,
    RowComponent: PageRow,
    DetailComponent: PageDetail,
  },
};

/**
 * Map UI type to API entry type
 */
export const uiTypeToEntryType: Record<UIExplorerType, ExplorerEntryType> = {
  files: "file",
  database: "table",
  celery: "task",
  api: "endpoint",
  pages: "page",
};

/**
 * Map API entry type to UI type
 */
export const entryTypeToUiType: Record<ExplorerEntryType, UIExplorerType> = {
  file: "files",
  table: "database",
  task: "celery",
  endpoint: "api",
  page: "pages",
};

/**
 * Get config by UI type
 */
export function getTypeConfig(uiType: UIExplorerType): ExplorerTypeConfig {
  const entryType = uiTypeToEntryType[uiType];
  return typeConfigs[entryType];
}

/**
 * Get config by API entry type
 */
export function getTypeConfigByEntry(entryType: ExplorerEntryType): ExplorerTypeConfig {
  return typeConfigs[entryType];
}
