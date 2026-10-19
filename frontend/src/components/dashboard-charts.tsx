import { donutSlices, type RiskBar, type SliceKey } from "@/lib/analytics";
import type { Counts } from "@/lib/scan";

import { TONE_CLASS } from "./status";

const SLICE_COLOUR: Record<SliceKey, string> = {
  pass: "var(--tone-green)",
  fail: "var(--tone-red)",
  unclear: "var(--tone-yellow)",
  not_applicable: "var(--tone-grey)",
};

const RADIUS = 40;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/** A donut of the results, with the same numbers listed beside it as text. */
export function Donut({ counts }: { counts: Counts }) {
  const slices = donutSlices(counts);
  const total = slices.reduce((sum, slice) => sum + slice.count, 0);
  const summary = slices.map((s) => `${s.count} ${s.label.toLowerCase()}`).join(", ");
  // Where each slice starts along the circle: the total length of the slices before it.
  const starts = slices.map((_, index) =>
    slices.slice(0, index).reduce((sum, s) => sum + (s.count / total) * CIRCUMFERENCE, 0),
  );
  return (
    <div className="flex flex-wrap items-center gap-6">
      <svg
        role="img"
        aria-label={`Results chart: ${summary || "no results yet"}`}
        viewBox="0 0 120 120"
        className="h-32 w-32"
      >
        <circle cx="60" cy="60" r={RADIUS} fill="none" stroke="var(--tone-grey-soft)" strokeWidth="20" />
        {slices.map((slice, index) => {
          const length = (slice.count / total) * CIRCUMFERENCE;
          return (
            <circle
              key={slice.key}
              cx="60"
              cy="60"
              r={RADIUS}
              fill="none"
              stroke={SLICE_COLOUR[slice.key]}
              strokeWidth="20"
              strokeDasharray={`${length} ${CIRCUMFERENCE - length}`}
              strokeDashoffset={-starts[index]}
              transform="rotate(-90 60 60)"
            />
          );
        })}
        <text x="60" y="66" textAnchor="middle" fontSize="20" fontWeight="600" fill="currentColor">
          {total}
        </text>
      </svg>
      <ul aria-label="Results by status" className="space-y-1 text-sm">
        {slices.map((slice) => (
          <li key={slice.key} className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className="inline-block h-3 w-3 rounded-sm"
              style={{ background: SLICE_COLOUR[slice.key] }}
            />
            <span>
              {slice.label}: {slice.count} ({Math.round((slice.count / total) * 100)}%)
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const SEGMENTS = [
  ["pass", "var(--tone-green)", "passed"],
  ["fail", "var(--tone-red)", "failed"],
  ["unclear", "var(--tone-yellow)", "unclear"],
  ["not_applicable", "var(--tone-grey)", "not applicable"],
] as const;

/** One stacked bar per risk, with its state in words. Untested risks are grey, never green. */
export function RiskBars({ bars }: { bars: RiskBar[] }) {
  return (
    <ul aria-label="Results by risk" className="space-y-2">
      {bars.map((bar) => {
        const counts = SEGMENTS.filter(([key]) => bar.segments[key] > 0)
          .map(([key, , word]) => `${bar.segments[key]} ${word}`)
          .join(" · ");
        return (
          <li
            key={bar.id}
            aria-label={`${bar.id} ${bar.name}`}
            data-tone={bar.tone}
            className={`space-y-1 rounded border-2 p-2 text-sm ${TONE_CLASS[bar.tone]}`}
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <span className="font-semibold">
                {bar.id} {bar.name}
              </span>
              <span className="font-semibold">{bar.label}</span>
            </div>
            <div
              aria-hidden="true"
              className="flex h-3 overflow-hidden rounded-sm"
              style={{ background: "var(--tone-grey-soft)" }}
            >
              {SEGMENTS.map(([key, colour]) =>
                bar.segments[key] > 0 ? (
                  <div
                    key={key}
                    style={{
                      width: `${(bar.segments[key] / bar.tests) * 100}%`,
                      background: colour,
                    }}
                  />
                ) : null,
              )}
            </div>
            <div>{bar.tests === 0 ? "No tests" : counts}</div>
          </li>
        );
      })}
    </ul>
  );
}
