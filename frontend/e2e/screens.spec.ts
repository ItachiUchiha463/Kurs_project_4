import { expect, test, type Page } from '@playwright/test'
import path from 'node:path'

// Знімки справжнього інтерфейсу для записки: SCREENS=1 SCREENS_DIR=<папка> npx playwright test screens
// Без SCREENS тест пропускається, щоб не входити в звичайний прогін.
test.skip(!process.env.SCREENS, 'лише для підготовки ілюстрацій')
test.use({ viewport: { width: 1280, height: 800 }, colorScheme: 'light' })

const DIR = process.env.SCREENS_DIR ?? 'screens'
const PASSWORD = 'Passw0rd1'
const email = `shots-${Date.now()}@example.com`
const shot = (page: Page, name: string, fullPage = false) => page.screenshot({ path: path.join(DIR, `app-${name}.png`), fullPage })

test('знімки інтерфейсу', async ({ page }) => {
  test.setTimeout(180_000)
  await page.goto('/login')
  await expect(page.locator('#email')).toBeVisible()
  await shot(page, 'login')

  await page.goto('/register')
  await page.locator('#full_name').fill('Ада Лавлейс')
  await page.locator('#email').fill(email)
  await page.locator('#password').fill(PASSWORD)
  await page.locator('#repeat').fill(PASSWORD)
  await page.getByRole('button', { name: 'Зареєструватися' }).click()
  await expect(page).toHaveURL(/\/targets\/new/)
  await page.locator('#name').fill('web-01')
  await page.getByRole('button', { name: 'Далі' }).click()
  const first = (await page.getByText(/--token 'vgl_[\w-]+'/).first().innerText()).match(/vgl_[\w-]+/)![0]
  await shot(page, 'add-server')

  const auth = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('vigil.token'))}` }
  const tokens: Record<string, string> = { 'web-01': first }
  for (const name of ['db-01', 'app-02']) {
    const r = await page.request.post('/api/targets', { headers: auth, data: { name, type: 'server' } })
    tokens[name] = (await r.json()).agent_token
  }
  await page.request.put('/api/thresholds', { headers: auth, data: { metric: 'disk_usage', target_id: null, warn: 85, crit: 95, duration_s: 0 } })

  // історія за останні 45 хвилин: записи старші за кілька хвилин лише зберігаються, інцидентів не відкривають
  const rec = (host: string, metric: string, value: number, ageMin: number, instance = '') => ({
    host, metric, instance, value, timestamp: new Date(Date.now() - ageMin * 60_000).toISOString(),
  })
  for (const [host, base] of [['web-01', 38], ['db-01', 22], ['app-02', 15]] as const) {
    const records = []
    for (let m = 45; m >= 0; m -= 1) {
      const wave = Math.sin(m / 5) * 8
      records.push(rec(host, 'cpu_usage', Math.max(2, base + wave), m), rec(host, 'ram_usage', 48 + (45 - m) * 0.1 + wave / 4, m),
        rec(host, 'disk_usage', host === 'web-01' ? 70 + (45 - m) * 0.6 : 40, m, '/'))
    }
    const r = await page.request.post('/api/ingest', { headers: { Authorization: `Bearer ${tokens[host]}` }, data: records.slice(0, 2000) })
    expect(r.status()).toBe(200)
  }
  await page.request.post('/api/ingest', { headers: { Authorization: `Bearer ${tokens['web-01']}` }, data: [rec('web-01', 'disk_usage', 97, 0, '/')] })

  await page.goto('/')
  await expect(page.getByText('Критично').or(page.getByText('Критичний стан')).first()).toBeVisible({ timeout: 15_000 })
  await page.waitForTimeout(1500)
  await shot(page, 'dashboard')

  await page.locator('a[href^="/targets/"]').filter({ hasText: 'web-01' }).first().click()  // картка об’єкта, а не рядок інциденту
  await expect(page.locator('svg.recharts-surface').first()).toBeVisible({ timeout: 15_000 })
  await page.waitForTimeout(1500)
  await shot(page, 'object', true)

  await page.goto('/incidents')
  await page.getByRole('link', { name: 'web-01' }).first().click()
  await expect(page.getByLabel('Діагностика')).toContainText('Заповнення диска')
  await page.waitForTimeout(1000)
  await shot(page, 'incident', true)

  await page.goto('/settings')
  await page.waitForTimeout(1000)
  await shot(page, 'settings')
  await page.getByRole('tab', { name: /Правила/ }).click()
  await page.waitForTimeout(800)
  await shot(page, 'rules')

  await page.goto('/reports')
  await page.waitForTimeout(1500)
  await shot(page, 'reports', true)

  await page.goto('/profile')
  await page.waitForTimeout(800)
  await shot(page, 'profile')
})
