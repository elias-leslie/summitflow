/**
 * Explorer Demo Page
 *
 * Test page for the unified explorer components.
 * Shows all component states with mock data.
 */

"use client";

import { useMemo } from "react";
import {
  ExplorerShell,
  DataList,
  DataRow,
  ColumnValue,
  StatusIndicator,
  type ExplorerType,
  type HealthStatus,
  type ExplorerColumn,
} from "@/components/explorer";
import { Database, Hash, Clock, Layers } from "lucide-react";

// Mock data types
interface MockTable {
  id: string;
  name: string;
  healthStatus: HealthStatus;
  rowCount: number;
  columnCount: number;
  daysSinceUpdate: number | null;
  category: string;
  columns: string[];
}

interface MockTask {
  id: string;
  name: string;
  healthStatus: HealthStatus;
  schedule: string;
  lastRun: string | null;
  successRate: number;
  avgDuration: string;
}

// Generate mock database tables
const mockTables: MockTable[] = [
  {
    id: "1",
    name: "users",
    healthStatus: "fresh",
    rowCount: 2345678,
    columnCount: 12,
    daysSinceUpdate: 0,
    category: "core",
    columns: ["id", "email", "name", "created_at", "updated_at", "password_hash", "role", "avatar_url", "settings", "last_login_at", "verified", "deleted_at"],
  },
  {
    id: "2",
    name: "orders",
    healthStatus: "fresh",
    rowCount: 890234,
    columnCount: 18,
    daysSinceUpdate: 0,
    category: "transactions",
    columns: ["id", "user_id", "total", "status", "created_at", "updated_at"],
  },
  {
    id: "3",
    name: "sessions",
    healthStatus: "stale",
    rowCount: 45678,
    columnCount: 8,
    daysSinceUpdate: 14,
    category: "auth",
    columns: ["id", "user_id", "token", "expires_at", "created_at", "ip_address", "user_agent", "revoked"],
  },
  {
    id: "4",
    name: "audit_logs",
    healthStatus: "fresh",
    rowCount: 12890456,
    columnCount: 10,
    daysSinceUpdate: 0,
    category: "system",
    columns: ["id", "actor_id", "action", "resource_type", "resource_id", "metadata", "ip_address", "created_at"],
  },
  {
    id: "5",
    name: "legacy_cache",
    healthStatus: "orphan",
    rowCount: 0,
    columnCount: 5,
    daysSinceUpdate: 180,
    category: "deprecated",
    columns: ["key", "value", "expires_at", "created_at", "updated_at"],
  },
  {
    id: "6",
    name: "notifications",
    healthStatus: "stale",
    rowCount: 567890,
    columnCount: 9,
    daysSinceUpdate: 7,
    category: "messaging",
    columns: ["id", "user_id", "type", "title", "body", "read_at", "created_at"],
  },
  {
    id: "7",
    name: "products",
    healthStatus: "fresh",
    rowCount: 12345,
    columnCount: 15,
    daysSinceUpdate: 1,
    category: "catalog",
    columns: ["id", "sku", "name", "description", "price", "stock", "category_id"],
  },
  {
    id: "8",
    name: "old_metrics",
    healthStatus: "orphan",
    rowCount: 234,
    columnCount: 4,
    daysSinceUpdate: 365,
    category: "deprecated",
    columns: ["id", "name", "value", "recorded_at"],
  },
];

// Generate mock celery tasks
const mockTasks: MockTask[] = [
  {
    id: "1",
    name: "process_payments",
    healthStatus: "fresh",
    schedule: "every 5m",
    lastRun: new Date(Date.now() - 3 * 60000).toISOString(),
    successRate: 99.8,
    avgDuration: "1.2s",
  },
  {
    id: "2",
    name: "send_notifications",
    healthStatus: "fresh",
    schedule: "every 1m",
    lastRun: new Date(Date.now() - 45000).toISOString(),
    successRate: 98.5,
    avgDuration: "0.3s",
  },
  {
    id: "3",
    name: "sync_inventory",
    healthStatus: "stale",
    schedule: "every 15m",
    lastRun: new Date(Date.now() - 2 * 60 * 60000).toISOString(),
    successRate: 87.2,
    avgDuration: "45s",
  },
  {
    id: "4",
    name: "cleanup_sessions",
    healthStatus: "fresh",
    schedule: "daily 3am",
    lastRun: new Date(Date.now() - 8 * 60 * 60000).toISOString(),
    successRate: 100,
    avgDuration: "2.1s",
  },
  {
    id: "5",
    name: "legacy_report_gen",
    healthStatus: "orphan",
    schedule: "manual",
    lastRun: null,
    successRate: 0,
    avgDuration: "—",
  },
];

// Column definitions
const tableColumns: ExplorerColumn<MockTable>[] = [
  {
    key: "name",
    label: "Table",
    render: (item) => (
      <div className="flex items-center gap-2">
        <Database className="w-4 h-4 text-cyan-400" />
        <span className="font-mono text-sm text-slate-200">{item.name}</span>
        <span className="text-xs text-slate-600">{item.category}</span>
      </div>
    ),
  },
  {
    key: "rowCount",
    label: "Rows",
    width: "100px",
    align: "right",
    render: (item) => (
      <ColumnValue mono muted={item.rowCount === 0} highlight={item.rowCount > 1000000}>
        {formatNumber(item.rowCount)}
      </ColumnValue>
    ),
  },
  {
    key: "columnCount",
    label: "Cols",
    width: "60px",
    align: "right",
    render: (item) => <ColumnValue mono muted>{item.columnCount}</ColumnValue>,
  },
  {
    key: "daysSinceUpdate",
    label: "Updated",
    width: "100px",
    align: "right",
    render: (item) => (
      <ColumnValue muted={item.daysSinceUpdate === null}>
        {item.daysSinceUpdate === null
          ? "—"
          : item.daysSinceUpdate === 0
            ? "today"
            : `${item.daysSinceUpdate}d ago`}
      </ColumnValue>
    ),
  },
];

const taskColumns: ExplorerColumn<MockTask>[] = [
  {
    key: "name",
    label: "Task",
    render: (item) => (
      <span className="font-mono text-sm text-slate-200">{item.name}</span>
    ),
  },
  {
    key: "schedule",
    label: "Schedule",
    width: "120px",
    render: (item) => (
      <ColumnValue muted className="text-xs">{item.schedule}</ColumnValue>
    ),
  },
  {
    key: "successRate",
    label: "Success",
    width: "80px",
    align: "right",
    render: (item) => (
      <ColumnValue
        mono
        highlight={item.successRate >= 99}
        muted={item.successRate === 0}
        className={item.successRate < 90 && item.successRate > 0 ? "text-amber-400" : ""}
      >
        {item.successRate > 0 ? `${item.successRate}%` : "—"}
      </ColumnValue>
    ),
  },
  {
    key: "avgDuration",
    label: "Avg Time",
    width: "80px",
    align: "right",
    render: (item) => <ColumnValue mono muted>{item.avgDuration}</ColumnValue>,
  },
];

function formatNumber(n: number): string {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return n.toString();
}

export default function ExplorerDemoPage() {
  return (
    <div className="min-h-screen bg-slate-950 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <header className="animate-in">
          <h1 className="text-2xl font-bold text-slate-100 display">
            Explorer Components Demo
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Prototype of the unified explorer UI with mock data
          </p>
        </header>

        {/* Main Explorer */}
        <div className="h-[600px] animate-fade-in">
          <ExplorerShell projectId="demo">
            {(props) => <ExplorerContent {...props} />}
          </ExplorerShell>
        </div>

        {/* Component Showcase */}
        <div className="grid grid-cols-2 gap-6 animate-fade-in stagger-2">
          <ComponentShowcase title="Status Indicators">
            <div className="flex flex-wrap gap-6">
              <StatusIndicator status="fresh" showLabel size="lg" />
              <StatusIndicator status="active" showLabel size="lg" />
              <StatusIndicator status="stale" showLabel size="lg" />
              <StatusIndicator status="orphan" showLabel size="lg" />
              <StatusIndicator status="unknown" showLabel size="lg" />
            </div>
          </ComponentShowcase>

          <ComponentShowcase title="Size Variants">
            <div className="flex items-center gap-6">
              <div className="flex items-center gap-2">
                <StatusIndicator status="fresh" size="sm" />
                <span className="text-xs text-slate-500">Small</span>
              </div>
              <div className="flex items-center gap-2">
                <StatusIndicator status="fresh" size="md" />
                <span className="text-xs text-slate-500">Medium</span>
              </div>
              <div className="flex items-center gap-2">
                <StatusIndicator status="fresh" size="lg" />
                <span className="text-xs text-slate-500">Large</span>
              </div>
            </div>
          </ComponentShowcase>
        </div>
      </div>
    </div>
  );
}

function ExplorerContent({
  type,
  filter,
  sortField,
  sortDir,
  expandedIds,
  onSort,
  onToggleExpand,
}: {
  type: ExplorerType;
  filter: HealthStatus | "all";
  sortField: string;
  sortDir: "asc" | "desc";
  expandedIds: Set<string>;
  onSort: (field: string) => void;
  onToggleExpand: (id: string) => void;
}) {
  // Filter data based on active filter
  const filteredTables = useMemo(() => {
    if (filter === "all") return mockTables;
    return mockTables.filter((t) => t.healthStatus === filter);
  }, [filter]);

  const filteredTasks = useMemo(() => {
    if (filter === "all") return mockTasks;
    return mockTasks.filter((t) => t.healthStatus === filter);
  }, [filter]);

  if (type === "database") {
    return (
      <DataList
        items={filteredTables}
        columns={tableColumns}
        sortField={sortField}
        sortDir={sortDir}
        onSort={onSort}
        emptyMessage="No tables match the current filter"
        emptyIcon={<Database className="w-12 h-12" />}
        renderRow={(table) => (
          <DataRow
            key={table.id}
            id={table.id}
            healthStatus={table.healthStatus}
            isExpanded={expandedIds.has(table.id)}
            onToggle={onToggleExpand}
            renderContent={() => (
              <div className="flex items-center gap-4 flex-1 min-w-0">
                {tableColumns.map((col) => (
                  <div
                    key={col.key}
                    style={{
                      width: col.width,
                      flex: col.width ? undefined : 1,
                      textAlign: col.align,
                    }}
                  >
                    {col.render(table)}
                  </div>
                ))}
              </div>
            )}
            renderDetail={() => <TableDetail table={table} />}
          />
        )}
      />
    );
  }

  if (type === "celery") {
    return (
      <DataList
        items={filteredTasks}
        columns={taskColumns}
        sortField={sortField}
        sortDir={sortDir}
        onSort={onSort}
        emptyMessage="No tasks match the current filter"
        renderRow={(task) => (
          <DataRow
            key={task.id}
            id={task.id}
            healthStatus={task.healthStatus}
            isExpanded={expandedIds.has(task.id)}
            onToggle={onToggleExpand}
            renderContent={() => (
              <div className="flex items-center gap-4 flex-1 min-w-0">
                {taskColumns.map((col) => (
                  <div
                    key={col.key}
                    style={{
                      width: col.width,
                      flex: col.width ? undefined : 1,
                      textAlign: col.align,
                    }}
                  >
                    {col.render(task)}
                  </div>
                ))}
              </div>
            )}
            renderDetail={() => <TaskDetail task={task} />}
          />
        )}
      />
    );
  }

  // Placeholder for other types
  return (
    <div className="flex items-center justify-center h-full text-slate-500">
      <p>{type} explorer coming soon...</p>
    </div>
  );
}

function TableDetail({ table }: { table: MockTable }) {
  return (
    <div className="space-y-4">
      {/* Overview */}
      <div className="grid grid-cols-4 gap-4">
        <MetricCard icon={<Hash />} label="Rows" value={formatNumber(table.rowCount)} />
        <MetricCard icon={<Layers />} label="Columns" value={String(table.columnCount)} />
        <MetricCard icon={<Clock />} label="Age" value={table.daysSinceUpdate ? `${table.daysSinceUpdate}d` : "—"} />
        <MetricCard label="Category" value={table.category} />
      </div>

      {/* Columns */}
      <div>
        <h4 className="text-xs font-medium text-slate-500 uppercase tracking-wide mb-2">
          Columns ({table.columns.length})
        </h4>
        <div className="flex flex-wrap gap-1.5">
          {table.columns.map((col) => (
            <span
              key={col}
              className="px-2 py-0.5 text-xs font-mono bg-slate-800 text-slate-400 rounded"
            >
              {col}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function TaskDetail({ task }: { task: MockTask }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-4">
        <MetricCard label="Schedule" value={task.schedule} />
        <MetricCard label="Success Rate" value={task.successRate > 0 ? `${task.successRate}%` : "N/A"} />
        <MetricCard label="Avg Duration" value={task.avgDuration} />
        <MetricCard
          label="Last Run"
          value={task.lastRun ? new Date(task.lastRun).toLocaleString() : "Never"}
        />
      </div>
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
}: {
  icon?: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="bg-slate-800/50 rounded-lg px-3 py-2">
      <div className="flex items-center gap-1.5 text-xs text-slate-500 mb-1">
        {icon && <span className="opacity-60">{icon}</span>}
        <span>{label}</span>
      </div>
      <div className="text-sm font-medium text-slate-200">{value}</div>
    </div>
  );
}

function ComponentShowcase({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="card p-4">
      <h3 className="text-sm font-medium text-slate-400 mb-4">{title}</h3>
      {children}
    </div>
  );
}
