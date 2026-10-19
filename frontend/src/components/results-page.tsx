"use client";

import { useState } from "react";

import { recordedLabel, toListItem, type SavedScans } from "@/lib/samples";

import { Dashboard } from "./dashboard";

/**
 * The public page: saved real scans in the same dashboard the owner uses. It has no way to start
 * a scan, asks for no password and makes no network request: everything comes from the file
 * built into the site.
 */
export function ResultsPage({ samples }: { samples: SavedScans }) {
  const [shownId, setShownId] = useState<number | null>(null);

  if (samples.scans.length === 0) {
    return (
      <section className="space-y-4">
        <h1 className="text-3xl font-semibold">Saved scan results</h1>
        <p>No saved scans yet.</p>
      </section>
    );
  }

  const weak = samples.scans.find((s) => s.scan.bot_id === "acme-weak") ?? samples.scans[0];
  const shown = samples.scans.find((s) => s.scan.id === shownId) ?? weak;
  // Compare opens ready: the scan on screen against the other saved one.
  const other = samples.scans.find((s) => s.scan.id !== shown.scan.id);

  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-3xl font-semibold">Saved scan results</h1>
        <p>
          These are saved real scans, not live ones. Nothing on this page runs a scan or calls an
          AI. They show a weak and a hardened demo support bot given the same tests.
        </p>
        <p className="rounded border-2 p-3 text-sm">{recordedLabel(shown)}</p>
      </header>
      <Dashboard
        key={shown.scan.id}
        detail={shown}
        history={samples.scans.map(toListItem)}
        onOpen={setShownId}
        loadScan={async (scanId) => {
          const found = samples.scans.find((s) => s.scan.id === scanId);
          if (!found) throw new Error("no such saved scan");
          return found;
        }}
        defaultCompareId={other?.scan.id}
      />
    </section>
  );
}
