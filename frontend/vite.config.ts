import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.DASHBOARD_BACKEND_URL || "http://127.0.0.1:8000";
  const apiKey = env.DASHBOARD_BACKEND_API_KEY || "test-only-api-key";
  return {
    plugins: [react()],
    server: {
      proxy: {
        "/api": {
          target: backend,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ""),
          headers: { "X-API-Key": apiKey },
        },
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: "./src/test/setup.ts",
      css: true,
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.includes("recharts") || id.includes("d3-") || id.includes("victory-vendor")) return "charts";
            if (id.includes("@tanstack")) return "query";
            if (id.includes("lucide-react")) return "icons";
            if (id.includes("react") || id.includes("scheduler")) return "react";
            return undefined;
          },
        },
      },
    },
  };
});
