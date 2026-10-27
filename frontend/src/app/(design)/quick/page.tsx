import type { Metadata } from "next";
import { Suspense } from "react";

import type { Way } from "@/components/connect-ways";
import { QuickScanPage } from "@/components/quick-scan-page";

// NEXT_PUBLIC_ variables are readable by anyone, so this must only ever hold the public API address.
const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const metadata: Metadata = {
  title: "Test your bot · Redflag",
  description: "Connect your bot or MCP server and run a starter pack of tests in one go.",
};

async function Connected({ searchParams }: { searchParams: Promise<{ connect?: string }> }) {
  const { connect } = await searchParams;
  const way: Way = connect === "mcp" || connect === "curl" ? connect : "http";
  return <QuickScanPage apiUrl={apiUrl} initialWay={way} />;
}

export default function QuickRoute({ searchParams }: { searchParams: Promise<{ connect?: string }> }) {
  return (
    <Suspense>
      <Connected searchParams={searchParams} />
    </Suspense>
  );
}
