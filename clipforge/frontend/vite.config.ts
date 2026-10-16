import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs on :8000 and Vite proxies /api to it,
// so the browser never needs (or sees) any API keys.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.VITE_API_TARGET || "http://localhost:8000", changeOrigin: true } },
  },
});
