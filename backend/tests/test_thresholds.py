from datetime import datetime, timedelta, timezone

from app.engine.defaults import DEFAULT_THRESHOLDS
from app.engine.thresholds import Deescalate, Escalate, Open, Resolve, State, Threshold, classify, step

T0 = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
CPU = Threshold("cpu_usage", "last", warn=80, crit=95, duration_s=60)


def run(th, points, state=State()):
    """points: [(секунди від T0, значення)] -> усі дії з часом, у порядку надходження."""
    out = []
    for sec, v in points:
        state, actions = step(state, th, v, T0 + timedelta(seconds=sec))
        out += [(sec, a) for a in actions]
    return state, out


def test_classify():
    assert classify(50, CPU) is None
    assert classify(81, CPU) == "warning"
    assert classify(96, CPU) == "critical"
    assert classify(80, CPU) is None  # межа не входить: «більше за поріг»


def test_short_spike_does_not_open_incident():
    state, actions = run(CPU, [(0, 90), (30, 90), (40, 50)])
    assert actions == [] and state == State()


def test_opens_after_duration_with_first_breach_time():
    _, actions = run(CPU, [(0, 90), (30, 90), (60, 90)])
    assert len(actions) == 1
    sec, act = actions[0]
    assert sec == 60 and act == Open("warning", 90, T0)


def test_duration_zero_opens_immediately():
    th = Threshold("cpu_usage", warn=80, crit=95, duration_s=0)
    _, actions = run(th, [(0, 96)])
    assert actions == [(0, Open("critical", 96, T0))]


def test_breach_level_change_during_wait_uses_level_at_open_time():
    _, actions = run(CPU, [(0, 85), (30, 97), (60, 97)])
    assert actions[0][1].severity == "critical" and actions[0][1].first_breach_at == T0


def test_escalation_warning_to_critical():
    state, actions = run(CPU, [(0, 85), (60, 85), (90, 97)])
    assert [type(a) for _, a in actions] == [Open, Escalate]
    assert state.incident == "critical"


def test_deescalation_needs_hysteresis_below_crit():
    state, _ = run(CPU, [(0, 97), (60, 97)])
    assert state.incident == "critical"
    state, actions = run(CPU, [(70, 94)], state)  # 94 < 95, але не нижче 95 × 0,95 = 90,25
    assert actions == [] and state.incident == "critical"
    state, actions = run(CPU, [(80, 88)], state)
    assert actions == [(80, Deescalate("warning", 88))] and state.incident == "warning"


def test_hysteresis_from_lowest_threshold_prevents_flapping():
    state, _ = run(CPU, [(0, 85), (60, 85)])
    assert state.incident == "warning"
    # warn = 80 → закриття лише нижче 76; 78 – уже не порушення, але й не «спокій»
    state, actions = run(CPU, [(100, 78), (200, 78)], state)
    assert actions == [] and state.incident == "warning" and state.calm_since is None
    state, actions = run(CPU, [(300, 70)], state)
    assert actions == [] and state.calm_since is not None  # спокій розпочався, чекаємо duration_s
    state, actions = run(CPU, [(330, 70), (360, 70)], state)
    assert actions == [(360, Resolve(70))] and state == State()


def test_calm_period_resets_if_value_rises_again():
    state, _ = run(CPU, [(0, 85), (60, 85), (100, 70)])
    assert state.calm_since is not None
    state, actions = run(CPU, [(120, 78)], state)
    assert state.calm_since is None and actions == []
    state, actions = run(CPU, [(130, 70), (180, 70)], state)
    assert actions == []  # відлік спокою почався заново о 130 с
    _, actions = run(CPU, [(190, 70)], state)
    assert actions[0][1] == Resolve(70)


def test_breach_while_calm_keeps_incident_open():
    state, _ = run(CPU, [(0, 85), (60, 85), (100, 70)])
    state, actions = run(CPU, [(110, 90)], state)
    assert actions == [] and state.incident == "warning" and state.calm_since is None


def test_binary_metric_has_no_hysteresis_and_uses_duration():
    th = DEFAULT_THRESHOLDS["available"]  # crit = 0, 30 с
    state, actions = run(th, [(0, 0), (20, 0)])
    assert actions == []
    state, actions = run(th, [(30, 0)], state)
    assert actions[0][1] == Open("critical", 0, T0)
    state, actions = run(th, [(40, 1)], state)  # перший успіх – спокій починається
    assert actions == []
    _, actions = run(th, [(70, 1)], state)
    assert actions == [(70, Resolve(1))]


def test_agent_alive_opens_at_once():
    _, actions = run(DEFAULT_THRESHOLDS["agent_alive"], [(0, 0)])
    assert actions == [(0, Open("critical", 0, T0))]


def test_below_direction():
    th = Threshold("db_cache_hit_pct", warn=95, crit=90, direction="below", duration_s=0)
    assert classify(94, th) == "warning" and classify(89, th) == "critical" and classify(96, th) is None
    state, _ = run(th, [(0, 94)])
    _, actions = run(th, [(10, 98)], state)  # 98 > 95 × 1,05 = 99,75? ні – ще не чисто
    assert actions == []
    _, actions = run(th, [(20, 100)], state)
    assert actions == [(20, Resolve(100))]


def test_every_default_threshold_is_consistent():
    for th in DEFAULT_THRESHOLDS.values():
        assert th.warn is not None or th.crit is not None
        if th.warn is not None and th.crit is not None:
            assert (th.warn < th.crit) if th.direction == "above" else (th.warn > th.crit)
