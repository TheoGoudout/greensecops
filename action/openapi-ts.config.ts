import { defineConfig } from "@hey-api/openapi-ts"

// Types-only output: the action calls the API with plain fetch (src/api.ts)
// and only consumes the generated request/response types.
export default defineConfig({
  input: "./openapi.json",
  output: "./src/client",

  plugins: ["@hey-api/typescript"],
})
