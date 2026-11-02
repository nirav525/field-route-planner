import json
from types import SimpleNamespace

import pytest

from planner import budget
from planner.baseline import nearest_neighbor
from planner.data import generate
from planner.metrics import log_decision, summarize
from planner.models import Rule
from planner.notes import NoteReaderUnavailable, check_rules, read_notes, validate_rule
from planner.problem import build_problem, check_plan
from planner.solver import solve

SITES, TECHS = generate()


def plan_with(rules=()):
    problem = build_problem(SITES, TECHS, list(rules))
    return solve(problem, time_limit_s=1), problem


def served(plan):
    return {s.site for r in plan.routes for s in r.stops}


def route_of(plan, tech):
    return next((r for r in plan.routes if r.tech == tech), None)


def test_plan_passes_the_independent_check():
    plan, problem = plan_with()
    assert plan.stops > 0
    assert check_plan(plan, problem) == []


def test_baseline_passes_the_independent_check():
    problem = build_problem(SITES, TECHS, [])
    assert check_plan(nearest_neighbor(problem), problem) == []


def test_solver_uses_fewer_miles_per_stop_than_baseline():
    plan, problem = plan_with()
    baseline = nearest_neighbor(problem)
    assert plan.miles / plan.stops < baseline.miles / baseline.stops


def test_tech_out_gets_no_stops():
    plan, problem = plan_with([Rule("tech_unavailable", tech="C")])
    assert route_of(plan, "C") is None
    assert check_plan(plan, problem) == []


def test_late_start_is_respected():
    plan, _ = plan_with([Rule("tech_start_after", tech="B", start="13:00")])
    route = route_of(plan, "B")
    assert all(s.arrive >= 13 * 60 for s in route.stops)


def test_assignment_is_respected():
    due = next(s.id for s in SITES if s.stock_pct < 60)
    plan, _ = plan_with([Rule("site_assign", tech="A", site=due)])
    assert due in {s.site for s in route_of(plan, "A").stops} or due in plan.dropped
    for tech in "BCD":
        assert due not in {s.site for s in route_of(plan, tech).stops}


def test_skip_removes_a_due_site():
    due = next(s.id for s in SITES if s.stock_pct < 60)
    plan, _ = plan_with([Rule("site_skip", site=due)])
    assert due not in served(plan) and due not in plan.dropped


def test_must_visit_adds_a_site_that_is_not_due():
    full = next(s.id for s in SITES if s.stock_pct >= 60)
    plan, _ = plan_with([Rule("site_must_visit", site=full)])
    assert full in served(plan)


def test_window_is_respected():
    due = next(s for s in SITES if s.stock_pct < 60 and s.open_min <= 10 * 60 and s.close_min >= 12 * 60)
    plan, problem = plan_with([Rule("site_window", site=due.id, start="10:00", end="12:00")])
    stop = next(s for r in plan.routes for s in r.stops if s.site == due.id)
    assert 10 * 60 <= stop.arrive and stop.depart <= 12 * 60
    assert check_plan(plan, problem) == []


def test_window_too_short_for_the_visit_drops_the_site():
    due = next(s for s in SITES if s.stock_pct < 60 and s.open_min <= 10 * 60 and s.close_min >= 11 * 60)
    plan, problem = plan_with([Rule("site_window", site=due.id, start="10:00", end="10:05")])
    assert due.id in plan.dropped
    assert check_plan(plan, problem) == []


def test_everyone_out_drops_everything():
    plan, problem = plan_with([Rule("tech_unavailable", tech=t.id) for t in TECHS])
    assert plan.stops == 0
    assert set(plan.dropped) == {s.id for s in problem.sites}


def test_check_plan_catches_a_broken_plan():
    plan, problem = plan_with()
    route = next(r for r in plan.routes if r.stops)
    route.stops[0].arrive = 0
    assert check_plan(plan, problem)


@pytest.mark.parametrize(
    "rule, fragment",
    [
        (Rule("tech_unavailable", tech="Z"), "no technician"),
        (Rule("site_skip", site="S99"), "no site"),
        (Rule("delete_everything"), "unknown rule type"),
        (Rule("tech_start_after", tech="A"), "needs start"),
        (Rule("tech_start_after", tech="A", start="1 PM"), "not a valid time"),
        (Rule("tech_start_after", tech="A", start="25:00"), "not a valid time"),
        (Rule("site_window", site="S01", start="12:00", end="10:00"), "not before"),
        (Rule("site_skip", site="S01", tech="A"), "should not have tech"),
    ],
)
def test_validator_rejects_bad_rules(rule, fragment):
    assert fragment in validate_rule(rule, TECHS, SITES)


def test_conflicting_rules_are_not_both_used():
    result = check_rules([Rule("site_skip", site="S01"), Rule("site_must_visit", site="S01")], TECHS, SITES)
    assert len(result.rules) == 1 and len(result.rejected) == 1


def test_assigning_to_a_tech_who_is_out_is_a_conflict():
    result = check_rules([Rule("tech_unavailable", tech="A"), Rule("site_assign", tech="A", site="S01")], TECHS, SITES)
    assert len(result.rejected) == 1


def test_reading_the_same_rule_twice_adds_nothing():
    first = Rule("tech_unavailable", tech="C", source="Tech C is out")
    again = Rule("tech_unavailable", tech="C", source="C is off today")
    result = check_rules([again], TECHS, SITES, existing=[first])
    assert result.rules == [] and result.rejected == []


@pytest.mark.parametrize(
    "first, second",
    [
        (Rule("tech_end_by", tech="A", end="15:00"), Rule("tech_end_by", tech="A", end="16:00")),
        (Rule("tech_start_after", tech="B", start="13:00"), Rule("tech_start_after", tech="B", start="14:00")),
        (Rule("site_window", site="S01", start="10:00", end="12:00"), Rule("site_window", site="S01", start="13:00", end="15:00")),
    ],
)
def test_two_different_values_for_the_same_thing_are_a_conflict(first, second):
    result = check_rules([second], TECHS, SITES, existing=[first])
    assert result.rules == [] and "conflicts" in result.rejected[0][1]


def test_same_rule_type_on_different_subjects_is_fine():
    result = check_rules([Rule("tech_end_by", tech="B", end="15:00")], TECHS, SITES, existing=[Rule("tech_end_by", tech="A", end="15:00")])
    assert len(result.rules) == 1


class FakeClient:
    """Stands in for the API, so these tests need no key and cost nothing."""

    def __init__(self, payload=None, stop_reason="end_turn", error=None):
        self.error = error
        self.sent = None
        response = SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=payload)])
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: self._create(kw, response)))

    def _create(self, kwargs, response):
        self.sent = kwargs
        if self.error:
            raise self.error
        return response


def rule_json(**fields):
    return {"type": fields["type"], "tech": fields.get("tech"), "site": fields.get("site"), "start": fields.get("start"), "end": fields.get("end"), "source": "note"}


def test_read_notes_keeps_good_rules_and_rejects_invented_ones():
    payload = json.dumps(
        {"rules": [rule_json(type="tech_unavailable", tech="C"), rule_json(type="site_skip", site="S99")], "unparsed": ["call the landlord"]}
    )
    result = read_notes("notes", TECHS, SITES, client=FakeClient(payload))
    assert [r.tech for r in result.rules] == ["C"]
    assert "no site" in result.rejected[0][1]
    assert result.unparsed == ["call the landlord"]


def test_only_notes_and_ids_are_sent():
    client = FakeClient(json.dumps({"rules": [], "unparsed": []}))
    read_notes("Tech C is out", TECHS, SITES, client=client)
    sent = client.sent["messages"][0]["content"]
    assert "Tech C is out" in sent
    assert "stock" not in sent and "shift" not in sent


@pytest.mark.parametrize("payload, stop", [("not json", "end_turn"), ("{}", "end_turn"), ("{}", "refusal"), ("{}", "max_tokens")])
def test_bad_model_answers_raise_rather_than_change_a_route(payload, stop):
    with pytest.raises(NoteReaderUnavailable):
        read_notes("notes", TECHS, SITES, client=FakeClient(payload, stop_reason=stop))


def test_spending_stops_before_the_limit_can_be_crossed(tmp_path):
    path = tmp_path / "spend.json"
    assert budget.can_spend(path, limit=5.0)
    path.write_text(json.dumps({"usd": 5.0 - budget.WORST_CASE_CALL_USD / 2}))
    assert not budget.can_spend(path, limit=5.0)


def test_spend_adds_up_across_calls(tmp_path):
    path = tmp_path / "spend.json"
    usage = SimpleNamespace(input_tokens=1000, output_tokens=1000)
    budget.record(usage, path)
    budget.record(usage, path)
    assert budget.spent(path) == pytest.approx(0.048)


def test_damaged_spend_record_stops_spending(tmp_path):
    path = tmp_path / "spend.json"
    path.write_text("not json")
    assert not budget.can_spend(path)


def test_no_call_is_made_once_the_limit_is_reached(monkeypatch):
    monkeypatch.setattr(budget, "can_spend", lambda: False)
    client = FakeClient(json.dumps({"rules": [], "unparsed": []}))
    with pytest.raises(NoteReaderUnavailable, match="spending limit"):
        read_notes("notes", TECHS, SITES, client=client)
    assert client.sent is None


def test_very_long_notes_are_refused_without_a_call():
    client = FakeClient(json.dumps({"rules": [], "unparsed": []}))
    with pytest.raises(NoteReaderUnavailable, match="characters"):
        read_notes("x" * (budget.MAX_NOTE_CHARS + 1), TECHS, SITES, client=client)
    assert client.sent is None


def test_decision_log_summary(tmp_path):
    path = tmp_path / "log.csv"
    plan, problem = plan_with()
    baseline = nearest_neighbor(problem)
    log_decision(plan, baseline, 60, 0, path)
    log_decision(plan, baseline, 120, 2, path)
    summary = summarize(path)
    assert summary["plans"] == 2
    assert summary["accepted_unchanged_pct"] == 50
