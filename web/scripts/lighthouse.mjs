import { spawn } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { chromium } from '@playwright/test'
import lighthouse from 'lighthouse'
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1', '--port', '5174'], { stdio: 'ignore', windowsHide: true })
let browser
try {
  let ready = false
  for (let i = 0; i < 50; i++) {
    try { if ((await fetch('http://127.0.0.1:5174')).ok) { ready = true; break } } catch { /* waiting for local server */ }
    await new Promise(resolve => setTimeout(resolve, 200))
  }
  if (!ready) throw new Error('Local production preview failed to start')
  browser = await chromium.launch({ args: ['--remote-debugging-port=9222'] })
  const result = await lighthouse('http://127.0.0.1:5174', { port: 9222, output: 'json', logLevel: 'error', onlyCategories: ['performance', 'accessibility', 'best-practices'], formFactor: 'desktop', screenEmulation: { mobile: false, width: 1350, height: 940, deviceScaleFactor: 1, disabled: false }, throttlingMethod: 'provided' })
  await mkdir('test-results', { recursive: true })
  await writeFile('test-results/lighthouse.json', result.report)
  const scores = Object.fromEntries(Object.entries(result.lhr.categories).map(([key, value]) => [key, Math.round(value.score * 100)]))
  console.log(JSON.stringify(scores))
  if (scores.performance < 85 || scores.accessibility < 95 || scores['best-practices'] < 90) {
    console.log(Object.values(result.lhr.audits).filter(a => a.score !== null && a.score < 1).map(a => `${a.id}: ${a.title}`).join('\n'))
    process.exitCode = 1
  }
} finally { await browser?.close(); server.kill() }
