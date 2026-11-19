import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Component tests: React components rendered in jsdom and driven the way a
// user drives them (Testing Library + user-event). The API client is mocked
// at the module boundary; every assertion is about what the user sees and
// which request the component sends. lib/ unit tests stay on node --test.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./", import.meta.url)) } },
  test: {
    environment: "jsdom",
    include: ["tests/components/**/*.test.tsx"],
    restoreMocks: true,
  },
});
