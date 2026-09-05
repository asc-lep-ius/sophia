import { paraglideVitePlugin } from "@inlang/paraglide-js";
import tailwindcss from "@tailwindcss/vite";
import { sveltekit } from "@sveltejs/kit/vite";
import { svelteTesting } from "@testing-library/svelte/vite";
import { defineConfig } from "vitest/config";

const API_PROXY_TARGET =
  process.env.SOPHIA_API_PROXY_TARGET ?? "http://127.0.0.1:8000";

/**
 * In production Caddy serves /app from this server and /api from the API on
 * one origin. Dev and preview have no Caddy, so the browser-side study calls
 * (and the SSE stream, which cannot carry headers and so needs the session
 * cookie) would otherwise be cross-origin.
 */
const apiProxy = {
  "/api": {
    target: API_PROXY_TARGET,
    changeOrigin: false,
    ws: false,
  },
};

export default defineConfig({
  plugins: [
    tailwindcss(),
    sveltekit(),
    paraglideVitePlugin({
      project: "./project.inlang",
      outdir: "./src/lib/paraglide",
      strategy: ["cookie", "preferredLanguage", "baseLocale"],
    }),
    svelteTesting(),
  ],
  server: { proxy: apiProxy },
  preview: { proxy: apiProxy },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["tests/unit/**/*.{test,spec}.ts"],
    setupFiles: ["./vitest-setup.ts"],
  },
});
