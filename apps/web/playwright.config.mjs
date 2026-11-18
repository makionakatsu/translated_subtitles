import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  testMatch: 'video-pane.spec.mjs',
  outputDir: './.next/playwright-test-results',
  use: { baseURL: 'http://127.0.0.1:47929', browserName: 'chromium' },
  webServer: {
    command: 'pnpm exec next start --hostname 127.0.0.1 --port 47929',
    url: 'http://127.0.0.1:47929',
    reuseExistingServer: false,
    timeout: 30000,
  },
});
