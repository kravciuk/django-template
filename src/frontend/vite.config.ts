import { resolve } from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Backend-integration mode (see https://vite.dev/guide/backend-integration):
// Django (via django-vite, see core/settings/base.py's DJANGO_VITE) serves
// the actual HTML page - this config only produces/serves the JS/CSS asset
// graph, mounted into the page's #header-root/#home-root divs.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
  // Matches STATICFILES_DIRS' ("frontend", .../dist) prefix and
  // DJANGO_VITE's static_url_prefix - built asset URLs must resolve under
  // /static/frontend/ in production.
  base: "/static/frontend/",
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    // Lets the Django-served page (a different origin/port in dev) load
    // this dev server's HMR client and modules.
    cors: true,
    origin: "http://localhost:5173",
  },
  build: {
    manifest: true,
    outDir: "dist",
    rollupOptions: {
      input: resolve(__dirname, "src/main.tsx"),
    },
  },
});
