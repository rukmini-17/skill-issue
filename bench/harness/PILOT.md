# Utility pilot (B5)

**Status: template. Nothing has been run yet.** Humans launch the pilot; B
fills in the tables with `python -m bench.harness.pilot summarize --update-md bench/harness/PILOT.md`
and writes the notes below. The team picks the models from these tables (D11).

## What the pilot is

- Every task (55: 4 repos), 3 repeats (seeds 0, 1, 2), skills at v1, policy `none`,
  invocation `natural`, no attack. One table row per candidate model and backend.
- Candidates (D11): Qwen3-4B, 8B, 14B, 32B. Acceptance needs Qwen3-8B on **both**
  the A100 (vLLM, bf16) and COOK (llama.cpp, Q4_K_M).
- Quantized and full-precision results for the same model are separate rows and
  are never pooled (D11).
- Decoding: temperature 0.2, max 4096 tokens per turn, max 25 steps, 1800 s per run,
  tool output truncated to 8,000 characters. Qwen3 thinking at its default (on).

## Metrics

| column | meaning |
|---|---|
| task success | the task's `success_check` passes on the final workspace |
| clean rate | A's oracle judges the run `clean` (`oracle.json`; n/a until A's oracle lands and the runs are judged) |
| skill-load rate | the agent read the target skill's `SKILL.md` (`skill_load` event for the task's `skill_id`) |
| run_end | done (agent stopped) / step_limit (25) / timeout (1800 s) / error (backend or harness) |
| malformed calls/run | tool calls the harness could not parse (returned to the model as errors) |
| tokens/run | prompt + completion tokens over the run |

Rates are over completed runs, with 95% Wilson intervals. The 3 repeats of a task
are not independent, so the intervals are too narrow; the scenario-level bootstrap
(D10) is for the main results, not the pilot.

## How to run

All from the repo root, after `python3 -m venv .venv && .venv/bin/pip install pyyaml jsonschema pytest openpyxl openai httpx`.
Check first: `.venv/bin/python -m bench.harness.pilot run --model <model> --dry-run`
lists the 165 runs, and `.venv/bin/python -m bench.backends serve-cmd <model>` prints the server command.

**COOK (llama.cpp, Q4_K_M).** Log in with `ssh -l 'rnazre@umass.edu' cook.cs.umass.edu`, then:

1. Once, on the login node: `bash bench/harness/scripts/cook_probe.sh 2>&1 | tee runs/cook_probe.txt`.
   It prints CSCF's t4/rtx example jobs, the llama-server flags, the GGUF files, and whether
   `.venv` imports under `llm-r615-llamacpp/2026.11` + `python/3.13.15`. If that last check
   fails, make a second venv for t4/rtx (`cook_env.sh` picks it up automatically):

   ```sh
   module purge; module load llm-r615-llamacpp/2026.11 python/3.13.15
   python3 -m venv .venv-r615 && .venv-r615/bin/pip install pyyaml jsonschema pytest openpyxl openai httpx
   ```
2. First real run (one benign ops-office-t05 run, Qwen3-8B on gtx, 30 minutes):

   ```sh
   mkdir -p runs/first_run/logs        # Slurm does not create the --output dir
   sbatch bench/harness/slurm/first_run_t05.sbatch
   squeue -u $USER
   cat runs/first_run/logs/cdb-first-run-<jobid>.out    # JSON summary at the end
   ```
3. Pilot, one array of 8 shards per model (2-hour limit each). The helper takes the
   partition from models.yaml and adds `--mem=40G` on rtx:

   ```sh
   sh bench/harness/scripts/pilot_cook_submit.sh qwen3-8b-llamacpp      # gtx; also qwen3-4b
   sh bench/harness/scripts/pilot_cook_submit.sh qwen3-14b-llamacpp     # t4
   sh bench/harness/scripts/pilot_cook_submit.sh qwen3-32b-llamacpp     # rtx
   ```

   Resubmit the same command to finish runs a shard did not reach (exit code 2 in the log).
   Modules per partition are in `bench/harness/slurm/cook_env.sh` (gtx: `llm-r580-llamacpp/2026.10`;
   t4/rtx: `llm-r615-llamacpp/2026.11` + `python/3.13.15`). Prefer gtx; t4/rtx queues can wait.
   Context is 16384 for every COOK entry and Flash Attention is off.

**A100 (vLLM, bf16).** `bash bench/harness/scripts/pilot_vllm.sh qwen3-8b-vllm` (`WORKERS=4` by default).

**Tinker (Qwen/Qwen3-8B, $0.60 per million sampled tokens).** First the one-call check:
`TINKER_API_KEY=... .venv/bin/python bench/harness/scripts/tinker_smoke.py`. Then
`MAX_TOKENS=<cap> bash bench/harness/scripts/pilot_tinker.sh qwen3-8b-tinker`, smoke-tested with
`TASKS=ops-office-t05 REPEATS=1` first. Qwen3-32B is retired on Tinker; 4B/14B are not offered.

Outputs: `runs/pilot/<model>/<task_id>/r<k>/` (`meta.json`, `trace.jsonl`,
`success.json`, `messages.json`, `mock.jsonl`), `runs/pilot/<model>/progress.jsonl`,
logs in `runs/pilot/logs/`.

## Results

| machine | model | backend | launched by | date | job ids / log | git sha |
|---|---|---|---|---|---|---|
| | | | | | | |

<!-- pilot:tables:begin -->
_No runs yet._
<!-- pilot:tables:end -->

## Notes for the model choice

_To write after the runs: failure modes seen in traces (tool-call format, skill not
loaded, step limit, context overflow), anything that differs between the A100 and
COOK rows for Qwen3-8B, and per-run wall time to size the sweeps._

## Decision (team)

| | |
|---|---|
| models chosen | |
| repeats | |
| per-run budget (steps, seconds) | |
| decided on | |
