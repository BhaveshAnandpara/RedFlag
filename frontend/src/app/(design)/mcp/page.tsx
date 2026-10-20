import type { Metadata } from "next";

import { McpPage } from "@/components/mcp-page";

// NEXT_PUBLIC_ variables are readable by anyone, so this must only ever hold the public API address.
const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const metadata: Metadata = {
  title: "Check an MCP server · Redflag",
  description: "Check an MCP server's tool descriptions, and its tools if you tick them.",
};

export default function McpRoute() {
  return <McpPage apiUrl={apiUrl} />;
}
