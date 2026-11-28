# D13 adaptive attacker: prompt swap-in + real calibration (2026-11-27)

Handoff summary for workstream D's stage-3 attacker. Picks up from the point Nisha's attacker
prompt was received — see `bench/runner/NOTES.md` ("Stage-3 attacker" section) for the fuller
history if you need it. Branch: `impl/d-attacks-runner`. PR: #3.

## What we have now

`bench/attackers/prompts/proposer.md` holds **Nisha's actual attacker prompt** (received
2026-11-27). It is the real text D13 calls for ("written and reviewed by the team"), not
placeholder content.

Her prompt specifies a reply format different from what the code was first built against:

- One or more blocks per reply, not a single JSON object:
  ```
  <file path="relative/path">
  ...full new contents of that file...
  </file>
  ```
  and, for `late_binding` only:
  ```
  <mock_page path="host/route">
  ...full page contents...
  </mock_page>
  ```
- **No "stop" signal.** The model never tells the loop it's out of ideas — the search is bounded
  purely by `budget` and `stop_at_bypass`, exactly as D13 already specifies. A reply with no
  parseable blocks is treated as a failed proposal (logged as `proposer_error`, costs one unit of
  budget, search continues) rather than ending the search.

`bench/attackers/adaptive.py`'s `LLMProposer` was updated to match: `_parse_blocks` parses the
`<file>`/`<mock_page>` format (two regexes, replacing the old JSON parsing). The policy-aware
attacker gets Nisha's static "blind spot" paragraph (after the `INJECTED ONLY FOR
policy_aware_adaptive` marker) with the concrete per-run policy description appended at the end
(`_apply_policy_description`) — her text has no substitution token, so this is an addition, not a
destructive change to her wording.

**Two open questions for Nisha, not resolved unilaterally — flag these to her:**
1. Her "Inputs you receive" list doesn't mention `seed_payloads`, `mock_pages` or `style`, but the
   code still sends `mock_pages` in the context JSON because `late_binding` proposals need a known
   `host/route` to pass validation (`bench/attackers/validate.py` rejects anything else) — without
   it, that attack class would fail almost every time. Confirm whether that omission from her list
   was deliberate.
2. Confirm the policy-aware injection (her general blind-spot prose + the concrete policy
   description appended after it) is the combination she intended, since her prompt doesn't say
   how the two should relate.

All 89 tests in `bench/tests/d` pass against the new prompt and parser; full suite (424 tests)
passes too.

## The real calibration run

Ran `bench/configs/experiments/adaptive_calibration.yaml` for real against Tinker (agent
Qwen3.8-27B, attacker Qwen3.6-35B-A3B) — 10 scenarios, budget 50, the two policies that survived
the static grid (`deny_by_default_manifest`, `delegation_envelope`), 8 local workers, $15 cost cap,
on `data-v1.2`.

**The attacker is clearly doing real work now:**
- 610 stage-3 proposals attempted, **171 (28%) structurally valid** (versus near-zero with the old
  placeholder prompt).
- **310 proposals (across all three stages) were `allow`ed** by the policies under test.

**But no bypass came from any of it:**
- Cumulative bypass stayed **flat at 5.3% (2/38 episodes touched)** across the entire 1–50 proposal
  range.
- Both of those 2 bypasses were from **stage 1** (the team's handcrafted seeds) — **none** of the
  hundreds of approved, LLM-generated proposals ever produced the goal effect once installed.

**Important caveat — the cap didn't fund the grid fairly.** Only **15 of the 38 touched episodes
reached the full 50-proposal budget**; the other 13 got cut off after a single proposal because
their worker's shared $1.875 budget share had already been spent on earlier episodes in that
worker's queue (workers burn a shared cost budget across episodes in sequence — an episode
scheduled late in an already-thin worker's queue can get starved almost immediately). So:

> **"25 proposals looks fine"** is a *directionally reasonable* read (nothing suggests a late bypass
> is being missed between 25 and 50) but **not a confirmed answer** — the sample that actually got a
> fair 50-proposal shot is thin (15 cells), and a near-zero bypass rate against these two
> *specifically strong* policies could just mean they're solid, not that budget is the limiting
> factor.

Total spend on this run: **$12.24**. Key-leak check: clean (0 files).

## Suggested next step for whoever picks this up

Before trusting the 25-proposal budget for the full `adaptive_tinker` sweep, either:
- **Re-run the calibration with a bigger `MAX_COST_USD`** (so all 40 cells get their full
  50-proposal budget, not just 15) — this is the cleanest fix and gives a real answer.
- Or treat the current result as directional only and proceed to the full sweep anyway, watching
  whether `deny_by_default_manifest` / `delegation_envelope` keep holding at near-zero bypass there
  too (which would corroborate "these policies are just strong" over "the attacker/budget is
  weak").

Either way, get Nisha's answer on the two open questions above first — they affect what the
attacker is allowed to see, which changes what any further calibration numbers mean.
