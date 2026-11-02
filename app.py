"""Field route planner: a person types notes, the solver builds routes, the person approves."""
import time

import altair as alt
import pandas as pd
import streamlit as st

from planner import budget
from planner.baseline import nearest_neighbor
from planner.data import load
from planner.metrics import compare, log_decision, summarize
from planner.models import RULE_TYPES, URGENT_BELOW_STOCK_PCT, Rule, to_hhmm
from planner.notes import NoteReaderUnavailable, check_rules, read_notes
from planner.problem import build_problem, check_plan
from planner.solver import solve

SAMPLE_NOTES = """Tech B can't start until 1 PM today.
Tech C is out.
S07 only takes deliveries between 10 and noon.
Please make sure S12 gets done today.
Skip S03, the building is closed."""

RULE_LABELS = {
    "tech_unavailable": "Technician is out",
    "tech_start_after": "Technician starts late",
    "tech_end_by": "Technician finishes early",
    "site_skip": "Skip a site",
    "site_must_visit": "Site must be visited",
    "site_assign": "Send a site to one technician",
    "site_window": "Site only open during a window",
}

st.set_page_config(page_title="Field Route Planner", layout="wide")
st.title("Field Route Planner")
st.caption("All sites, technicians and results on this page come from made-up data.")

sites, techs = load()
site_ids = [s.id for s in sites]
tech_ids = [t.id for t in techs]

state = st.session_state
state.setdefault("rules", [])
state.setdefault("result", None)
state.setdefault("changes", 0)
state.setdefault("approved", None)


def build_plan(count_as_change: bool = False) -> None:
    problem = build_problem(sites, techs, state.rules)
    plan = solve(problem)
    baseline = nearest_neighbor(problem)
    state.result = {
        "problem": problem,
        "plan": plan,
        "baseline": baseline,
        "errors": check_plan(plan, problem),
        "rules": list(state.rules),
        "shown_at": state.result["shown_at"] if state.result and count_as_change else time.time(),
    }
    # Moves from review stay in the rules across rebuilds, so they keep counting as changes.
    state.changes = state.changes + 1 if count_as_change else sum(r.source == "changed in review" for r in state.rules)
    state.approved = None


# 1. Notes
st.header("1. Today's notes")
left, right = st.columns(2)

with left:
    notes = st.text_area("Type notes the way you would tell a colleague", SAMPLE_NOTES, height=150)
    if st.button("Read notes"):
        try:
            parsed = read_notes(notes, techs, sites, existing=state.rules)
        except NoteReaderUnavailable as e:
            st.warning(f"The note reader isn't available ({e}). Add rules by hand instead; planning still works.")
        else:
            state.rules += parsed.rules
            state.last_parse = parsed

    st.caption(f"Note reader spend in this app: ${budget.spent():.2f} of ${budget.LIMIT_USD:.2f}")

    parsed = state.get("last_parse")
    if parsed:
        for rule, reason in parsed.rejected:
            st.error(f"Not used: \"{rule.source or rule.describe()}\" ({reason})")
        for text in parsed.unparsed:
            st.warning(f"Couldn't turn this into a rule: \"{text}\"")

with right:
    with st.expander("Add a rule by hand", expanded=False):
        rule_type = st.selectbox("Rule", list(RULE_LABELS), format_func=RULE_LABELS.get)
        needed = RULE_TYPES[rule_type]
        tech = st.selectbox("Technician", tech_ids) if "tech" in needed else None
        site = st.selectbox("Site", site_ids) if "site" in needed else None
        start = st.text_input("From (HH:MM)", "10:00") if "start" in needed else None
        end = st.text_input("Until (HH:MM)", "12:00") if "end" in needed else None
        if st.button("Add rule"):
            checked = check_rules([Rule(rule_type, tech, site, start, end, "added by hand")], techs, sites, state.rules)
            state.rules += checked.rules
            for rule, reason in checked.rejected:
                st.error(f"Not added: {reason}")

    st.subheader("Rules in use")
    if not state.rules:
        st.write("None yet.")
    for i, rule in enumerate(list(state.rules)):
        text_col, remove_col = st.columns([5, 1])
        text_col.write(rule.describe())
        if rule.source and rule.source != "added by hand":
            text_col.caption(f"From: \"{rule.source}\"")
        if remove_col.button("Remove", key=f"remove_{i}"):
            state.rules.pop(i)
            st.rerun()

# 2. Plan
st.header("2. Plan")
if st.button("Build plan", type="primary"):
    with st.spinner("Building routes..."):
        build_plan()

result = state.result
if result:
    plan, baseline, problem = result["plan"], result["baseline"], result["problem"]

    stale = result["rules"] != state.rules
    if stale:
        st.warning("The rules changed after this plan was built. Build the plan again before approving.")

    if result["errors"]:
        st.error("This plan failed its checks and should not be used: " + "; ".join(result["errors"]))

    st.subheader("Against the simple baseline (nearest stop next)")
    c = compare(plan, baseline)
    cols = st.columns(4)
    cols[0].metric("Stops served", c["stops"][0], c["stops"][0] - c["stops"][1])
    cols[1].metric("Drive miles", f"{c['miles'][0]:.0f}", f"{c['miles'][0] - c['miles'][1]:.0f}", delta_color="inverse")
    cols[2].metric("Drive minutes", c["drive_min"][0], c["drive_min"][0] - c["drive_min"][1], delta_color="inverse")
    cols[3].metric("Miles per stop", f"{c['miles_per_stop'][0]:.1f}", f"{c['miles_per_stop'][0] - c['miles_per_stop'][1]:.1f}", delta_color="inverse")
    st.caption(f"Solver time: {plan.solve_seconds:.1f} seconds. {len(problem.sites)} of {len(sites)} sites were due today.")

    by_id = {s.id: s for s in problem.sites}
    tech_by_id = {t.id: t for t in problem.techs}

    points = []
    for route in plan.routes:
        tech_row = tech_by_id[route.tech]
        path = [("Home", tech_row.x, tech_row.y)] + [(st_.site, by_id[st_.site].x, by_id[st_.site].y) for st_ in route.stops]
        if route.stops:
            path.append(("Home", tech_row.x, tech_row.y))
        for order, (label, x, y) in enumerate(path):
            points.append({"Tech": f"Tech {route.tech}", "order": order, "label": label, "x": x, "y": y})

    frame = pd.DataFrame(points)
    axis_x, axis_y = alt.X("x:Q", title="Miles east", scale=alt.Scale(domain=[0, 50])), alt.Y("y:Q", title="Miles north", scale=alt.Scale(domain=[0, 40]))
    lines = alt.Chart(frame).mark_line().encode(x=axis_x, y=axis_y, color="Tech:N", order="order:Q", detail="Tech:N")
    dots = alt.Chart(frame).mark_circle(size=70).encode(x=axis_x, y=axis_y, color="Tech:N", tooltip=["Tech", "label"])
    st.altair_chart(lines + dots, width="stretch")

    route_cols = st.columns(max(len(plan.routes), 1))
    for col, route in zip(route_cols, plan.routes):
        with col:
            finish = f", home by {to_hhmm(route.finish)}" if route.finish else ""
            st.markdown(f"**Tech {route.tech}**: {len(route.stops)} stops, {route.miles:.0f} miles{finish}")
            if route.stops:
                st.dataframe(
                    pd.DataFrame(
                        [{"Site": s.site, "Arrive": to_hhmm(s.arrive), "Leave": to_hhmm(s.depart), "Stock %": by_id[s.site].stock_pct} for s in route.stops]
                    ),
                    hide_index=True,
                    width="stretch",
                )

    if plan.dropped:
        urgent = [s for s in plan.dropped if by_id[s].stock_pct < URGENT_BELOW_STOCK_PCT]
        message = f"Not served today: {', '.join(plan.dropped)}."
        if urgent:
            st.error(message + f" Urgent, under {URGENT_BELOW_STOCK_PCT}% stock: {', '.join(urgent)}.")
        else:
            st.warning(message)

    # 3. Review
    st.header("3. Review and approve")
    st.write("Nothing is final until you approve it. A change here re-plans and counts against the \"accepted unchanged\" measure.")

    move_site, move_tech, move_button = st.columns([2, 2, 1])
    site_choice = move_site.selectbox("Move site", [s.id for s in problem.sites])
    tech_choice = move_tech.selectbox("To technician", [t.id for t in problem.techs] or ["-"])
    move_button.write("")
    if move_button.button("Move and re-plan"):
        candidate = Rule("site_assign", tech_choice, site_choice, source="changed in review")
        state.rules = [r for r in state.rules if not (r.type == "site_assign" and r.site == site_choice)]
        checked = check_rules([candidate], techs, sites, state.rules)
        state.rules += checked.rules
        for rule, reason in checked.rejected:
            st.error(f"Not moved: {reason}")
        if checked.rules:
            build_plan(count_as_change=True)
            st.rerun()

    if state.approved is None:
        if st.button("Approve plan", type="primary", disabled=bool(result["errors"]) or stale):
            review_seconds = time.time() - result["shown_at"]
            state.approved = log_decision(plan, baseline, review_seconds, state.changes)
            st.rerun()
    else:
        st.success(f"Approved after {state.approved.review_seconds:.0f} seconds of review, with {state.approved.changes_made} change(s).")

# 4. Measures
st.header("4. How it's doing")
summary = summarize()
if summary is None:
    st.write("No plans approved yet.")
else:
    cols = st.columns(3)
    cols[0].metric("Plans approved", summary["plans"])
    cols[1].metric("Accepted unchanged", f"{summary['accepted_unchanged_pct']}%")
    cols[2].metric("Median minutes to approve", summary["median_minutes_to_approve"])
