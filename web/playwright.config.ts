import { defineConfig } from '@playwright/test'
import { resolve } from 'node:path'
const python = resolve(process.platform === 'win32' ? '../api/.venv/Scripts/python.exe' : '../api/.venv/bin/python')
export default defineConfig({ testDir: './e2e', fullyParallel: false, workers: 1, timeout: 30000, use: { baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure' }, webServer: [
  { command: `"${python}" ../scripts/serve_local.py`, url: 'http://127.0.0.1:8000/health', timeout: 60000, reuseExistingServer: !process.env.CI },
  { command: 'npm run preview', url: 'http://127.0.0.1:5173', timeout: 60000, reuseExistingServer: !process.env.CI }
] })
