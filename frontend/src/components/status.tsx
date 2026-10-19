import type { Tone } from "@/lib/analytics";
import type { Status } from "@/lib/scan";

// Full class names, written out, so Tailwind can see them. Colour is never the only signal:
// every badge carries its word.
export const TONE_CLASS: Record<Tone, string> = {
  green: "border-tone-green bg-tone-green-soft text-tone-green-ink",
  red: "border-tone-red bg-tone-red-soft text-tone-red-ink",
  yellow: "border-tone-yellow bg-tone-yellow-soft text-tone-yellow-ink",
  grey: "border-tone-grey bg-tone-grey-soft text-tone-grey-ink",
};

export const STATUS_WORD: Record<Status, string> = {
  pass: "PASS",
  fail: "FAIL",
  inconclusive: "INCONCLUSIVE",
  error: "ERROR",
  not_applicable: "NOT APPLICABLE",
};

export const STATUS_TONE: Record<Status, Tone> = {
  pass: "green",
  fail: "red",
  inconclusive: "yellow",
  error: "yellow",
  not_applicable: "grey",
};

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span
      className={`inline-block rounded border-2 px-2 py-0.5 text-xs font-semibold ${TONE_CLASS[STATUS_TONE[status]]}`}
    >
      {STATUS_WORD[status]}
    </span>
  );
}
