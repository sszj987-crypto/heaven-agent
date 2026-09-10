import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The macOS desktop bundle serves these assets from the bundled Python API.
  // Keeping the UI static removes Node.js from the end-user runtime.
  output: "export",
  devIndicators: false,
  outputFileTracingRoot: process.cwd(),
  turbopack: {
    root: process.cwd(),
  },
};

export default nextConfig;
