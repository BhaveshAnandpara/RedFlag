import type { Metadata } from "next";

import { ResultsPage } from "@/components/results-page";
import samples from "@/data/sample-scans.json";
import type { SavedScans } from "@/lib/samples";

export const metadata: Metadata = {
  title: "Saved scan results",
  description:
    "Saved real scans of a weak and a hardened demo bot, shown in the full Redflag dashboard.",
};

export default function ResultsRoute() {
  return (
    <main className="mx-auto w-full max-w-5xl px-6 py-12">
      <ResultsPage samples={samples as unknown as SavedScans} />
    </main>
  );
}
