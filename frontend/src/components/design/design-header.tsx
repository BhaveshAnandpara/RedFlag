"use client";

import { usePathname } from "next/navigation";

import { HeaderView } from "./header-view";

export function DesignHeader() {
  const path = usePathname();
  const current = path === "/quick" || path.startsWith("/quick/") ? "quick" : null;
  return <HeaderView current={current} />;
}
