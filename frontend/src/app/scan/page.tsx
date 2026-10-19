import type { Metadata } from "next";

import { ScanPage } from "@/components/scan-page";

// NEXT_PUBLIC_ variables are readable by anyone, so this must only ever hold the public API address.
const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// An owner-only tool: not linked from anywhere and kept out of search engines.
export const metadata: Metadata = {
  title: "Scan",
  robots: { index: false, follow: false },
};

export default function ScanRoute() {
  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-12">
      <ScanPage apiUrl={apiUrl} />
    </main>
  );
}
