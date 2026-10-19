// The saved sample scans the public results page shows (frontend/src/data/sample-scans.json).
import type { ScanDetail, ScanListItem } from "@/lib/scan";

export type SavedScans = {
  format_version: number;
  saved_at: string | null;
  scans: ScanDetail[];
};

export function toListItem(detail: ScanDetail): ScanListItem {
  return {
    id: detail.scan.id,
    bot_id: detail.scan.bot_id,
    status: detail.scan.status,
    started_at: detail.scan.started_at,
    finished_at: detail.scan.finished_at,
    counts: detail.summary.counts,
  };
}

/** When a saved scan was recorded and which model answered, so it can never pass as live. */
export function recordedLabel(detail: ScanDetail): string {
  const date = new Date(detail.scan.started_at * 1000).toISOString().slice(0, 10);
  const models = detail.scan.models_used.length > 0 ? detail.scan.models_used.join(", ") : "no model";
  return `Recorded on ${date} with ${models}`;
}
