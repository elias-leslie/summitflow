/**
 * FileColumns - Column definitions for files explorer
 */

import type { ExplorerColumn } from "../../types";
import type { ExplorerEntry } from "@/lib/api/explorer";

export const fileColumns: ExplorerColumn<ExplorerEntry>[] = [
  {
    key: "name",
    label: "Name",
    render: () => null, // Handled by FileRow
  },
  {
    key: "lines_of_code",
    label: "LOC",
    width: "80px",
    align: "right",
    render: () => null,
  },
  {
    key: "size_bytes",
    label: "Size",
    width: "80px",
    align: "right",
    render: () => null,
  },
  {
    key: "last_scanned_at",
    label: "Modified",
    width: "100px",
    align: "right",
    render: () => null,
  },
];
