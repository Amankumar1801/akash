import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev: the API is proxied so the browser sees one origin (no CORS setup needed locally).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/v1": process.env.AKASH_API_URL ?? "http://127.0.0.1:8000" } },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
