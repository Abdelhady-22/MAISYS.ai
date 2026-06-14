import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/drugs": {
        target: "http://localhost:8002",
        changeOrigin: true,
      },
      "/auth": {
        target: "http://localhost:8001",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://localhost:8002",
        ws: true,
      },
    },
  },
});
