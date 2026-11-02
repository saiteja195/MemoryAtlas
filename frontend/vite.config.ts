import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": { target: "http://localhost:8000", rewrite: (p) => p.replace(/^\/api/, "") } } },
  // The graph library is most of the bundle; keep it in its own file so app changes re-download little.
  build: { rollupOptions: { output: { manualChunks: { graph: ["cytoscape", "cytoscape-fcose"] } } }, chunkSizeWarningLimit: 600 },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
