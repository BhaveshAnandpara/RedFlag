import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // The site is the design pages (copied into public/design at build). They are served at the
  // root so the address bar reads / , /scan.html and /results.html, and their own links work.
  async rewrites() {
    return {
      beforeFiles: [
        { source: "/", destination: "/design/home.html" },
        { source: "/home.html", destination: "/design/home.html" },
        { source: "/scan.html", destination: "/design/scan.html" },
        { source: "/results.html", destination: "/design/results.html" },
        { source: "/scan-data.js", destination: "/design/scan-data.js" },
      ],
      afterFiles: [],
      fallback: [],
    };
  },
  // The MCP check is now a way to connect in Test your bot.
  async redirects() {
    return [{ source: "/mcp", destination: "/quick?connect=mcp", permanent: false }];
  },
  // The early design explorations stay reachable but out of search.
  async headers() {
    return [
      { source: "/design/hero-:name.html", headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }] },
      { source: "/design/type-options.html", headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }] },
    ];
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
