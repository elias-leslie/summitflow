/**
 * PageColumns - Column definitions for pages explorer
 */

import type { ExplorerColumn } from "../../types";
import type { ExplorerEntry } from "@/lib/api/explorer";

export const pageColumns: ExplorerColumn<ExplorerEntry>[] = [
  {
    key: "name",
    label: "Page",
    render: () => null,
  },
  {
    key: "route_params",
    label: "Params",
    width: "100px",
    render: () => null,
  },
  {
    key: "http_status",
    label: "Status",
    width: "70px",
    align: "center",
    render: () => null,
  },
  {
    key: "response_time_ms",
    label: "Response",
    width: "80px",
    align: "right",
    render: () => null,
  },
];
