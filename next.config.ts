import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep Next dev artifacts out of the production `.next` directory so a
  // desktop:dev session cannot poison a later packaged build.
  distDir: process.env.BLM_NEXT_DIST_DIR || ".next",
  typescript: {
    ignoreBuildErrors: true,
  },
  // The custom server binds 127.0.0.1 directly, so Next dev does not know the
  // hostname and blocks the HMR websocket as a cross-site request.
  allowedDevOrigins: ["127.0.0.1"],
};

export default nextConfig;
