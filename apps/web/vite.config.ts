import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "../..", "");
  const apiHost = env.APP_HOST || "127.0.0.1";
  const apiPort = env.APP_PORT || "8000";
  const apiTarget = env.VITE_API_PROXY_TARGET || `http://${apiHost}:${apiPort}`;

  return {
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      port: 5173,
      proxy: {
        "/api": apiTarget
      }
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./tests/setup.ts"]
    }
  };
});
