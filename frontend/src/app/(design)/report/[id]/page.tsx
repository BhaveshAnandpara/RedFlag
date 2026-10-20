import type { Metadata } from "next";
import { Suspense } from "react";

import { ReportLoader } from "@/components/report-loader";

// NEXT_PUBLIC_ variables are readable by anyone, so this must only ever hold the public API address.
const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// A report is for whoever has its link: kept out of search engines, and the link's secret key is
// not passed on to other sites.
export const metadata: Metadata = {
  title: "Report · Redflag",
  robots: { index: false, follow: false },
  referrer: "no-referrer",
};

export default function ReportRoute() {
  return (
    <Suspense
      fallback={
        <main className="d-report">
          <p className="card nomatch">Loading the report…</p>
        </main>
      }
    >
      <ReportLoader apiUrl={apiUrl} />
    </Suspense>
  );
}
