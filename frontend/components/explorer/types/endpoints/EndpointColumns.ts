/**
 * EndpointColumns - Column definitions for endpoints explorer
 */

import type { ExplorerColumn } from "../../types";
import type { ExplorerEntry } from "@/lib/api/explorer";

export const endpointColumns: ExplorerColumn<ExplorerEntry>[] = [
  {
    key: "name",
    label: "Endpoint",
    render: () => null,
  },
  {
    key: "method",
    label: "Method",
    width: "70px",
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
