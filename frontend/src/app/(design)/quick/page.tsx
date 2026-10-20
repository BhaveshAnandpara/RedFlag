import type { Metadata } from "next";

import { QuickScanPage } from "@/components/quick-scan-page";

// NEXT_PUBLIC_ variables are readable by anyone, so this must only ever hold the public API address.
const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const metadata: Metadata = {
  title: "Quick scan · Redflag",
  description: "A starter pack of tests, run on your bot in one go.",
};

export default function QuickRoute() {
  return <QuickScanPage apiUrl={apiUrl} />;
}
