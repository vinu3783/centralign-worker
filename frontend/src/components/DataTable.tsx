import type { ReactNode } from "react";
import { Spinner, cx } from "./ui";

export interface Column<T> {
  key: string;
  header: string;
  render?: (row: T) => ReactNode;
  className?: string;
  align?: "left" | "right";
}

/** Generic table. data-testid/data-loading let the browser tool and tests wait for real data. */
export function DataTable<T extends { id?: number | string }>({ columns, rows, loading, empty = "No records", rowTestId, rowClass, onRowClick }: {
  columns: Column<T>[];
  rows: T[] | null;
  loading?: boolean;
  empty?: string;
  rowTestId?: (row: T) => string;
  rowClass?: (row: T) => string | undefined;
  onRowClick?: (row: T) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
      <table data-testid="data-table" data-loading={loading || rows === null ? "true" : "false"} className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50">
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={cx("px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-slate-500", c.align === "right" ? "text-right" : "text-left")}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows === null || (loading && rows.length === 0) ? (
            <tr><td colSpan={columns.length} className="px-4 py-10 text-center text-slate-400"><Spinner className="mx-auto" /></td></tr>
          ) : rows.length === 0 ? (
            <tr><td colSpan={columns.length} className="px-4 py-10 text-center text-slate-400">{empty}</td></tr>
          ) : (
            rows.map((row, i) => (
              <tr key={row.id ?? i} data-row="true" data-testid={rowTestId?.(row)} onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={cx("transition-colors hover:bg-slate-50/80", onRowClick && "cursor-pointer", rowClass?.(row))}>
                {columns.map((c) => (
                  <td key={c.key} data-col={c.key} className={cx("px-4 py-2.5 align-middle text-slate-700", c.align === "right" && "text-right tabular-nums", c.className)}>
                    {c.render ? c.render(row) : String((row as Record<string, unknown>)[c.key] ?? "—")}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
