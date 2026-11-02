# Field Route Planner

A small tool for a dispatcher who has to send technicians to service sites each day. You type your notes in plain English, a solver builds the routes, and nothing is final until you approve the plan.

This is a sanitized reconstruction of a dispatch system I built and run at my current job. It is new code on made-up data, with no code, data or site names from that company. In production, that system took route planning from 2 hours to 10 minutes. Every number below comes from the made-up data in this repo, not from production.

I decided what this tool does and what it leaves out. Claude Code wrote most of the code.

## How it works

1. **Input:** 40 made-up sites with stock levels, opening hours and visit lengths, and 4 technicians with shifts. A site is due when its stock is under 60%.
2. **Notes to rules:** a dispatcher types something like "Tech B can't start until 1 PM". An LLM turns it into a rule, and code checks that rule before it is used.
3. **Routes:** OR-Tools builds the plan within technician shifts and site hours.
4. **Check:** separate code recomputes every plan from scratch. A plan with a broken constraint can't be approved.
5. **Approval:** the dispatcher accepts the plan or moves a stop, which re-plans.
6. **Measures:** the app compares each plan to a simple baseline and logs every approval.

## Decisions

**A solver does the routing, not an LLM.** Routes have to respect shifts and site hours every time, and the same input should not produce a plan that breaks a limit. A solver guarantees that and costs nothing per run. The LLM only handles the one part a solver can't: messy human text.

**The LLM proposes, code decides.** Every rule is checked against the real technician and site lists. An invented site, a bad time or two rules that conflict get rejected and shown to the person. Anything the model can't express goes into an "unparsed" list. A bad parse should never silently change a route.

**The tool works without the LLM.** With no API key, or if the API is down, the dispatcher adds the same rules by hand from a form. The LLM saves typing; it isn't a dependency.

**A person approves everything.** A wrong route costs a technician's day and can leave a site empty, so the tool proposes and a person decides. Changes made in review are counted, because a high change rate means the tool isn't trusted yet.

**Spending has a hard stop.** Each note-reader call is capped in size, and the app refuses a call that could take its running total past $5, set by `ROUTE_PLANNER_BUDGET_USD`. The total covers this app only, so a workspace limit in the Anthropic Console is still the real cap on a key.

**Only the note text and id lists go to the API.** Stock levels, locations and shifts stay local. Notes are treated as data, and the check above limits what a malicious or confused note can do.

## Results on the made-up data

The baseline is simple: each technician in turn drives to the nearest stop that fits. From one run with a 3-second solver limit:

| Scenario | Measure | Solver | Baseline |
|---|---|---|---|
| Normal day | Stops served | 22 | 22 |
| | Drive miles | 126 | 167 |
| | Drive minutes | 251 | 332 |
| Short-staffed day (one tech out, one starting late, plus three site rules) | Stops served | 19 | 16 |
| | Sites not served | 3 | 6 |
| | Must-visit site served | Yes | No |
| | Drive miles | 169 | 135 |

On the short-staffed day the solver drives more miles because it serves more stops and sends a technician to the must-visit site, which the baseline drops. Miles alone would have made the baseline look better, which is why the tool reports stops served beside them.

These numbers show how the method behaves on one made-up map. They don't predict savings anywhere else.

The app also tracks plans approved, the share accepted unchanged, and median minutes to approve. Those only mean something with real dispatchers, so no results are claimed here.

## Known limits

- It minimizes driving and doesn't balance work. On the normal day above, one technician gets no stops.
- Distances are straight lines times a road factor of 1.3, at an assumed 30 mph.
- A site's urgency is only its stock level.
- A plan is for one day, with no carryover.

## What I'd do next

- Real road distances and traffic
- A workload-balance setting
- Live machine and stock data
- Sending approved routes to technicians
- Logins for multiple dispatchers
- A labeled set of real notes to measure how often the LLM gets the rule right

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

To use the note reader, set `ANTHROPIC_API_KEY` first. Everything else works without it.

```bash
.venv/bin/python -m pytest              # no API key needed; the API is faked
.venv/bin/python -m planner.data        # regenerate the made-up data
```
