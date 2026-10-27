import type { Status } from "@/lib/scan";

/** How a result looks on the row of flags and in the badge. */
export type Look = "pass" | "fail" | "unclear";

export function lookOf(status: Status): Look {
  if (status === "pass") return "pass";
  if (status === "fail") return "fail";
  return "unclear";
}

/**
 * A failed normal request is not an attack that got through: the bot did not do something it
 * should have. It gets the amber look so the red flags count only attacks, as the headline does.
 */
export function lookOfResult(r: { kind: string; status: Status }): Look {
  return r.kind === "positive" && r.status === "fail" ? "unclear" : lookOf(r.status);
}

/**
 * The row of flags, one per test. A finished test shows its outcome; the next one blinks while the
 * run goes on. `total` can be unknown (an MCP check), then the row simply grows.
 */
export function FlagStrip({
  looks,
  total,
  running = false,
  className = "",
}: {
  looks: Look[];
  total?: number;
  running?: boolean;
  className?: string;
}) {
  const count = Math.max(total ?? 0, looks.length + (running ? 1 : 0));
  return (
    <div className={`flagstrip ${className}`.trim()} aria-hidden="true">
      {Array.from({ length: count }, (_, i) => {
        const look = looks[i];
        const state = look ?? (running && i === looks.length ? "now" : "");
        return (
          <span key={i} className={`mf ${state}`.trim()}>
            <i />
            <b />
          </span>
        );
      })}
    </div>
  );
}

/** The small red flag raised on a reply that broke a rule. */
export function RaisedFlag() {
  return (
    <span className="bflag" aria-hidden="true">
      <i />
      <b />
    </span>
  );
}
