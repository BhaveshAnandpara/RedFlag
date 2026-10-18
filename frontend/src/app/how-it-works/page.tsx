import type { Metadata } from "next";

import { HowItWorks } from "@/components/how-it-works";
import recordings from "@/data/recordings.json";
import type { Recordings } from "@/lib/recordings";

export const metadata: Metadata = {
  title: "How Redflag tests your AI",
  description: "Recorded attacks on a weak and a hardened demo support bot, side by side.",
};

export default function HowItWorksPage() {
  return (
    <main className="mx-auto w-full max-w-5xl px-6 py-12">
      <HowItWorks recordings={recordings as unknown as Recordings} />
    </main>
  );
}
