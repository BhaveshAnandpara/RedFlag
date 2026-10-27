export type Way = "http" | "curl" | "mcp";

/** MCP servers are switched off for now: Test your bot only offers HTTP bots. The MCP flow stays in the code. */
export const MCP_ENABLED = false;

const WAYS: [Way, string][] = [
  ["http", "HTTP endpoint"],
  ["curl", "curl command"],
  ...(MCP_ENABLED ? ([["mcp", "MCP server"]] as [Way, string][]) : []),
];

/** A way that is switched off falls back to the plain HTTP form. */
export const usableWay = (way: Way): Way => (way === "mcp" && !MCP_ENABLED ? "http" : way);

/** The ways to connect, shown at the top of step 1 whichever one is chosen. */
export function ConnectWays({ value, onChange }: { value: Way; onChange: (way: Way) => void }) {
  return (
    <div className="f">
      <div className="ways" role="radiogroup" aria-label="How do you connect?">
        {WAYS.map(([way, label]) => (
          <button
            key={way}
            type="button"
            className="way"
            role="radio"
            aria-checked={value === way}
            onClick={() => onChange(way)}
          >
            {label}
          </button>
        ))}
      </div>
      <span className="hint">
        {MCP_ENABLED ? "Works with: HTTP bots, curl or code, MCP servers" : "Works with: HTTP bots, curl or code"}
      </span>
    </div>
  );
}
