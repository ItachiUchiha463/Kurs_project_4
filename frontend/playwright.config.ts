import { defineConfig } from '@playwright/test'

// E2E: справжній браузер, справжній бекенд на окремій базі vigil_e2e, Vite як фронтенд.
// Потрібні Docker із запущеним контейнером бази (docker compose up -d db) і .venv бекенда.
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  workers: 1,  // тести одного сценарію ділять базу й користувачів
  reporter: [['list']],
  use: { baseURL: 'http://localhost:5173', channel: 'msedge', trace: 'retain-on-failure' },
  webServer: [
    { command: 'node e2e/serve-backend.mjs', url: 'http://localhost:8000/api/health', timeout: 120_000, reuseExistingServer: false },
    { command: 'npm run dev -- --port 5173', url: 'http://localhost:5173', reuseExistingServer: true },
  ],
})
