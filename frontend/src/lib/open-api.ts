// What the open pages (quick scan, MCP check) share: plain-words refusals and reading a scan back
// with the secret view key that starting it returned.
import type { ScanDetail } from "@/lib/scan";
import { describeError } from "@/lib/setup";
import type { SetupApi } from "@/lib/setup-api";

/** Plain words for a refusal. A 401 means the backend has not opened the page's calls. */
export function problemFor(status: number, body: unknown): string {
  if (status === 401) return "This tool is not open yet. Please try again later.";
  return describeError(status, body as never);
}

export async function readOpenScan(
  api: SetupApi,
  scanId: number,
  viewKey: string,
): Promise<ScanDetail> {
  const result = await api.call<ScanDetail>(
    "GET",
    `/open-scans/${scanId}?key=${encodeURIComponent(viewKey)}`,
  );
  if (!result.ok) throw new Error(`scan request failed with ${result.status}`);
  return result.data;
}

/** The address of a finished scan's report. The view key is the link's secret. */
export function reportPath(scanId: number, viewKey: string): string {
  return `/report/${scanId}?key=${encodeURIComponent(viewKey)}`;
}

export function hostOf(address: string): string {
  try {
    return new URL(address).host;
  } catch {
    return address;
  }
}
