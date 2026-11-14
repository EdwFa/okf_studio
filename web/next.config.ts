import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  devIndicators: false,
  agentRules: false,
  // Dependencies are hoisted to the repository root by npm workspaces.
  turbopack: { root: path.resolve(__dirname, "..") },
};

export default nextConfig;
