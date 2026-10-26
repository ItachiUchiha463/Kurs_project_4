// Типи відповідей API (hand-written; v1.3: генерувати з /api/openapi.json через openapi-typescript)
export type Status = 'ok' | 'warning' | 'critical' | 'unavailable' | 'unknown'
export type Severity = 'warning' | 'critical'
export type IncidentStatus = 'open' | 'acknowledged' | 'resolved' | 'suppressed'

export interface Target {
  id: number
  name: string
  type: 'server' | 'service' | 'container' | 'database'
  source: 'manual' | 'discovered'
  hidden: boolean
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

export interface MetricStat { avg: number; max: number }
export interface ReportRow {
  target_id: number
  name: string
  type: Target['type']
  availability_pct: number
  incidents: number
  warning: number
  critical: number
  mean_detect_s: number | null
  mean_recover_s: number | null
  metrics: Record<string, MetricStat>
}
export interface Report {
  start: string
  end: string
  incidents: number
  critical: number
  rows: ReportRow[]
  top_causes: { cause: string; count: number }[]
}

export interface ThresholdItem {
  metric: string
  agg: string
  window_s: number
  warn: number | null
  crit: number | null
  direction: 'above' | 'below' | 'equals'
  duration_s: number
  source: 'default' | 'template' | 'target'
  levels_editable: boolean
}

export interface RuleCondition {
  scope: 'self' | 'host' | 'siblings'
  metric: string
  op: string
  value: number
  agg: 'last' | 'avg' | 'max' | 'min' | 'delta'
  window_s: number
  instance: string | null
  sibling_type: 'container' | 'database' | 'service' | null
  match: 'any' | 'all'
}
export interface Rule {
  id: number
  name: string
  cause: string
  recommendation: string
  applies_to: string[]
  conditions: RuleCondition[]
  priority: number
  enabled: boolean
  own: boolean
}
export interface RuleTest {
  ratio: number
  matched: boolean
  evidence: { ok: boolean; text: string; value: string }[]
}
