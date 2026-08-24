import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // This app lives beside the backend inside a larger repo, and there are
  // lockfiles further up the tree. Without this, Next infers a workspace root
  // several directories above and traces files that have nothing to do with
  // the frontend.
  outputFileTracingRoot: path.join(__dirname),

  images: {
    // Seed data uses stable public placeholders; real artwork will come from
    // TMDB image paths.
    remotePatterns: [
      { protocol: "https", hostname: "picsum.photos" },
      { protocol: "https", hostname: "fastly.picsum.photos" },
      { protocol: "https", hostname: "image.tmdb.org" },
    ],
  },
};

export default nextConfig;
