import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies to the engine (FastAPI, port 8000).
// REALNESS LAW: the UI never invents data — every request here hits the real engine.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/events": { target: "http://localhost:8000", changeOrigin: true },
      "/ws": { target: "ws://localhost:8000", ws: true, changeOrigin: true },
    },
  },
});
