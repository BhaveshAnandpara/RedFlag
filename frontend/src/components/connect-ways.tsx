export type Way = "http" | "curl" | "mcp";

const WAYS: [Way, string][] = [
  ["http", "HTTP endpoint"],
  ["curl", "curl command"],
  ["mcp", "MCP server"],
];

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
      <span className="hint">Works with: HTTP bots, curl or code, MCP servers</span>
    </div>
  );
}
