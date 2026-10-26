// Типи відповідей API (hand-written; v1.3: генерувати з /api/openapi.json через openapi-typescript)
export type Status = 'ok' | 'warning' | 'critical' | 'unavailable' | 'unknown'
export type Severity = 'warning' | 'critical'
export type IncidentStatus = 'open' | 'acknowledged' | 'resolved' | 'suppressed'

export interface Target {
  id: number
  name: string
  type: 'server' | 'service'
  check_type: 'agent' | 'http' | 'tcp' | 'ping'
  address: string | null
  host_id: number | null
  ping_enabled: boolean
  interval_s: number
  status: Status
  last_seen: string | null
  agent_version: string | null
  clock_offset_s: number | null
  latest: Record<string, number>
}
export interface TargetCreated extends Target {
  agent_token: string | null
}

export interface Incident {
  id: number
  target_id: number
  target_name: string
  metric: string
  instance: string
  severity: Severity
  status: IncidentStatus
  value_at_open: number | null
  first_breach_at: string | null
  started_at: string
  acknowledged_at: string | null
  resolved_at: string | null
  resolve_comment: string | null
  suppressed_by: number | null
  suppressed_count: number
}
export interface IncidentEvent {
  type: string
  value: number | null
  ts: string
  note: string | null
}
export interface Evidence {
  ok: boolean
  text: string
  value: string
}
export interface Diagnosis {
  cause: string
  recommendation: string
  matched_ratio: number
  evidence: Evidence[]
  alternatives: { name: string; ok: number; total: number }[]
}
export interface IncidentDetail extends Incident {
  events: IncidentEvent[]
  diagnosis: Diagnosis | null
  related: Incident[]
}

export interface Me {
  id: number
  email: string
  full_name: string
  telegram_linked: boolean
  notify_min_severity: Severity
}
export interface TelegramLink {
  code: string
  url: string | null
  expires_in_s: number
}
export interface Point {
  ts: string
  value: number
}

// Події WebSocket (ТЗ 10.1)
export type LiveEvent =
  | { type: 'ready' }
  | { type: 'metrics'; target_id: number; status: Status; last_seen: string | null; values: Record<string, number> }
  | { type: 'incident'; change: string; incident: Incident }
