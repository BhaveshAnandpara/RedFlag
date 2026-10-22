import Link from "next/link";

// The design pages (home, demo scan, saved results) are static files served at these addresses, so
// they are plain links. Quick scan and the MCP check are routes of the app. The links, and their
// order, match the nav in design/explore so every page shows the same one.
export function HeaderView({ current }: { current: "quick" | "mcp" | null }) {
  return (
    <header>
      <a className="brand" href="/">
        <svg viewBox="0 0 16 18" aria-hidden="true">
          <rect width="2" height="18" fill="#f4f4f2" />
          <path d="M2 1h13l-3 4 3 4H2z" fill="#ff3b3f" />
        </svg>
        Redflag
      </a>
      <nav aria-label="Main">
        <a href="/#scene">How it works</a>
        <a href="/scan.html">Demo scan</a>
        <Link href="/quick" aria-current={current === "quick" ? "page" : undefined}>
          Test your bot
        </Link>
        <Link href="/mcp" aria-current={current === "mcp" ? "page" : undefined}>
          MCP check
        </Link>
        <a href="/results.html">Results</a>
        <a href="https://github.com/BhaveshAnandpara/RedFlag#readme" target="_blank" rel="noopener">
          Docs
        </a>
      </nav>
    </header>
  );
}
