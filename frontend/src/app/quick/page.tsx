import type { Metadata } from "next";

import { QuickScanPage } from "@/components/quick-scan-page";

// NEXT_PUBLIC_ variables are readable by anyone, so this must only ever hold the public API address.
const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// An owner-only tool for now: kept out of search engines, and locked behind the owner password.
export const metadata: Metadata = {
  title: "Quick scan",
  robots: { index: false, follow: false },
};

export default function QuickRoute() {
  return (
    <main className="mx-auto w-full max-w-6xl px-6 py-12">
      <QuickScanPage apiUrl={apiUrl} />
    </main>
  );
}
