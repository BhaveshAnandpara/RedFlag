import type { Metadata } from "next";

import { RouterTestPage } from "@/components/router-test-page";

// NEXT_PUBLIC_ variables are readable by anyone, so this must only ever hold the public API address.
const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// An owner-only test tool: not linked from anywhere and kept out of search engines.
export const metadata: Metadata = {
  title: "Model router test",
  robots: { index: false, follow: false },
};

export default function RouterPage() {
  return (
    <main className="mx-auto w-full max-w-2xl px-6 py-12">
      <RouterTestPage apiUrl={apiUrl} />
    </main>
  );
}
