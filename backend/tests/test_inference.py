from app.engine.defaults import DEFAULT_THRESHOLDS
from app.engine.inference import Condition, Rule, diagnose, evaluate
from app.seed_rules import BASE_RULES

NAMES = {"self": "shop", "host": "web-01"}


def rule(name, conds, applies=("service",), priority=0, own=False):
    return Rule(None, name, name, "", applies, tuple(conds), priority, own)


CPU_HIGH = Condition("host", "cpu_usage", ">", 90, "avg", 300)
SLOW = Condition("self", "response_ms", ">", 1000, "avg", 300)


def facts(**kw):
    return {("host", "cpu_usage", "avg", 300, None, None): kw.get("cpu"), ("self", "response_ms", "avg", 300, None, None): kw.get("rt")}


def test_full_match_has_evidence_with_actual_values():
    m = evaluate(rule("CPU", [SLOW, CPU_HIGH]), facts(cpu=96.1, rt=1240), NAMES)
    assert m.ratio == 1.0
    assert [e.ok for e in m.evidence] == [True, True]
    assert m.evidence[1].text == "CPU web-01, середнє за 5 хв" and m.evidence[1].value == "96,1 % > 90 %"
    assert m.evidence[0].value == "1240 мс > 1000 мс"


def test_partial_match_and_missing_data():
    m = evaluate(rule("CPU", [SLOW, CPU_HIGH]), facts(cpu=50, rt=1240), NAMES)
    assert m.ratio == 0.5
    m = evaluate(rule("CPU", [SLOW, CPU_HIGH]), facts(cpu=None, rt=1240), NAMES)
    assert m.ratio == 0.5 and m.evidence[1].value == "немає даних" and not m.evidence[1].ok


def test_more_specific_rule_wins_then_own_then_priority():
    broad = rule("широке", [SLOW], priority=99)
    narrow = rule("вузьке", [SLOW, CPU_HIGH], priority=1)
    d = diagnose([broad, narrow], facts(cpu=96, rt=1500), NAMES, "service")
    assert d.primary.rule.name == "вузьке" and [m.rule.name for m in d.alternatives] == ["широке"]
    base, own = rule("базове", [SLOW]), rule("своє", [SLOW], own=True)
    assert diagnose([base, own], facts(rt=2000), NAMES, "service").primary.rule.name == "своє"
    low, high = rule("low", [SLOW], priority=1), rule("high", [SLOW], priority=9)
    assert diagnose([low, high], facts(rt=2000), NAMES, "service").primary.rule.name == "high"


def test_no_full_match_gives_no_primary_and_lists_possible_causes():
    d = diagnose([rule("CPU", [SLOW, CPU_HIGH])], facts(cpu=40, rt=1500), NAMES, "service")
    assert d.primary is None and d.alternatives[0].ratio == 0.5


def test_rules_for_other_target_types_are_ignored():
    d = diagnose([rule("тільки сервер", [SLOW], applies=("server",))], facts(rt=2000), NAMES, "service")
    assert d.primary is None and d.alternatives == []


def test_boundary_values_are_strict():
    assert evaluate(rule("x", [CPU_HIGH]), facts(cpu=90), NAMES).ratio == 0.0
    assert evaluate(rule("x", [Condition("host", "cpu_usage", ">=", 90, "avg", 300)]), facts(cpu=90), NAMES).ratio == 1.0


def _as_rules():
    return [Rule(None, r["name"], r["cause"], r["recommendation"], tuple(r["applies_to"]),
                 tuple(Condition(**c) for c in r["conditions"]), r["priority"]) for r in BASE_RULES]


def test_every_base_rule_starts_with_a_symptom_that_has_a_default_threshold():
    """«Правило повноти» (ТЗ 7.3): без порога на симптомі інцидент не відкриється й правило ніколи не розглянеться."""
    for r in _as_rules():
        first = r.conditions[0]
        assert first.scope == "self", r.name
        assert first.metric in DEFAULT_THRESHOLDS or first.metric == "status_code", f"{r.name}: немає порогу для {first.metric}"


def test_base_rules_are_well_formed():
    names = set()
    for r in _as_rules():
        assert r.name not in names and r.cause and r.recommendation and r.conditions
        names.add(r.name)
        for c in r.conditions:
            assert c.op in ("<", ">", "<=", ">=", "==") and isinstance(c.value, (int, float))


def test_siblings_conditions_any_and_all():
    def rule(match):
        return Rule(1, "R", "причина", "", ("database",),
                    (Condition("siblings", "container_running", "==", 0, sibling_type="container", match=match),))
    key = ("siblings", "container_running", "last", 0, None, "container")
    names = {"self": "db", "host": "web-01", "siblings": "на сервері"}
    assert evaluate(rule("any"), {key: [1.0, 0.0]}, names).ratio == 1.0   # хоч один контейнер зупинено
    assert evaluate(rule("all"), {key: [1.0, 0.0]}, names).ratio == 0.0   # не всі
    assert evaluate(rule("all"), {key: [0.0, 0.0]}, names).ratio == 1.0
    no_data = evaluate(rule("any"), {key: []}, names)
    assert no_data.ratio == 0.0 and no_data.evidence[0].value == "немає даних"
