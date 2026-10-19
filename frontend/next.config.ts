import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // The design pages (copied into public/design at build) are previews: keep them out of search.
  async headers() {
    return [{ source: "/design/:path*", headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }] }];
  },
  async rewrites() {
    return [{ source: "/design", destination: "/design/home.html" }];
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
