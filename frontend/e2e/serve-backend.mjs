// Піднімає бекенд для E2E: окрема база vigil_e2e, міграції, початкові правила, uvicorn.
// Telegram вимкнено (порожній токен), інтервал між пакетами агента – 0, щоб тест не чекав.
import { execFileSync, spawn } from 'node:child_process'
import { readFileSync } from 'node:fs'

const dotenv = readFileSync('../.env', 'utf8')
const get = (k) => dotenv.match(new RegExp(`^${k}=(.*)$`, 'm'))?.[1]?.trim()
const dbUrl = get('DATABASE_URL').replace(/\/[^/]+$/, '/vigil_e2e')
const pgUser = get('POSTGRES_USER') ?? 'vigil'
const psql = (sql) => execFileSync('docker', ['exec', 'vigil-db-1', 'psql', '-U', pgUser, '-d', 'postgres', '-c', sql], { stdio: 'inherit' })

psql('DROP DATABASE IF EXISTS vigil_e2e WITH (FORCE)')
psql('CREATE DATABASE vigil_e2e')

const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python'
const env = {
  ...process.env, DATABASE_URL: dbUrl, JWT_SECRET: 'e2e-secret-at-least-32-characters-long-000',
  INGEST_MIN_INTERVAL_S: '0', TELEGRAM_BOT_TOKEN: '', SMTP_HOST: '', REGISTRATION_MODE: 'open',
}
const run = (args) => execFileSync(python, args, { cwd: '../backend', env, stdio: 'inherit' })
run(['-m', 'alembic', 'upgrade', 'head'])
run(['seed.py'])

const server = spawn(python, ['-m', 'uvicorn', 'app.main:app', '--port', '8000', '--workers', '1'], { cwd: '../backend', env, stdio: 'inherit' })
const stop = () => { server.kill(); process.exit(0) }
process.on('SIGTERM', stop)
process.on('SIGINT', stop)
server.on('exit', (code) => process.exit(code ?? 1))
