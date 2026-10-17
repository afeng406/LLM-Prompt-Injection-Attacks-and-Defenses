import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  workers: 1,
  timeout: 30000,
  outputDir: "../runs/browser-artifacts",
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:5173", channel: "msedge", headless: true },
});
