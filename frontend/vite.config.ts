import { readFileSync } from "node:fs"
import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import { tanstackRouter } from "@tanstack/router-plugin/vite"
import react from "@vitejs/plugin-react-swc"
import { defineConfig } from "vitest/config"

// The version comes from package.json rather than from a VITE_ variable, so it
// needs no plumbing through the four places the other VITE_* values are
// supplied — scripts/bump_version.py already writes it there, and
// scripts/validate_versions.py keeps it equal to the root VERSION file. Read
// rather than imported to stay clear of tsconfig.node.json's narrow include.
const { version } = JSON.parse(
  readFileSync(path.resolve(__dirname, "package.json"), "utf-8"),
)

// https://vitejs.dev/config/
export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(version),
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: true,
    port: 5173,
    watch: {
      usePolling: true,
      ignored: ["**/node_modules/**", "**/.git/**"],
      interval: 1000,
    },
  },
  plugins: [
    tanstackRouter({
      target: "react",
      autoCodeSplitting: true,
    }),
    react(),
    tailwindcss(),
  ],
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
})
