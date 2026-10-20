import { JetBrains_Mono, Space_Grotesk } from "next/font/google";

import { Suspense } from "react";

import { DesignHeader } from "@/components/design/design-header";
import { HeaderView } from "@/components/design/header-view";

import "./design.css";

const spaceGrotesk = Space_Grotesk({
  variable: "--font-space-grotesk",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

// The pages that carry the Redflag design: quick scan, MCP check and the report. The look comes
// from design/explore, through scripts/build-design-css.mjs.
export default function DesignLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className={`rfd ${spaceGrotesk.variable} ${jetbrainsMono.variable}`}>
      <Suspense fallback={<HeaderView current={null} />}>
        <DesignHeader />
      </Suspense>
      {children}
    </div>
  );
}
