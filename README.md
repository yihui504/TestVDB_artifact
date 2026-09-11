# TestVDB — Replication Artifact

This archive accompanies the paper *Detecting Logic Bugs in Vector Database Management Systems
via LLM-Derived Behavioral Specifications*. It contains the pipeline definition, the per-version
documentation knowledge bases and extracted specifications, all generated test scripts with their
raw HTTP execution logs, the evidence chains, the submission ledger, and — for the
re-adjudication study — the frozen candidate packages and the per-case judge outputs for every
arm and run.

The archive is anonymized for double-blind review: machine paths, account names, and repository
identities have been rewritten to placeholders.

---

## Layout

```
pipeline/     The multi-agent pipeline: agent role definitions, command definitions, contracts,
              the strategy registry, Docker templates, and skills.
rq1/          RQ1 — detection effectiveness
  ledger/       Submission ledger: the 81 adjudicated submissions and their maintainer outcomes.
  runs/         Full RQ1 pipeline runs, per target version. Each run directory holds the crawled
                knowledge base, the extracted specifications, the generated test scripts, the raw
                HTTP request/response logs, and one evidence chain per candidate.
  raw-intel/    Mined issue/PR intelligence and the developer-cognition corpus per target.
rq2/          RQ2 — false-positive interception
  materials/    The 81 frozen candidate packages (observed transcript + documented contract).
  dispatches/   The exact judge dispatch text sent for each arm.
  verdicts/     Per-case judge verdicts for every arm and run, plus the aggregation scripts.
  pool/         Candidate-pool assembly: how the 81 packages were built from pipeline output.
  analyses/     Scripts that compute every rate, interval, and paired test reported in the paper.
rq3/          RQ3 — comparison with the crash-oracle baseline
  runs/         Baseline run outputs, per run: the run report and the per-template logs recording
                every request and every oracle decision.
  analyses/     Baseline source files needed to interpret the oracle, our probe, and the run report.
```

## RQ2 verdict files

Each line of a `verdicts_*.jsonl` file is one case judged once:

```json
{"defect_id": "...", "verdict": "CONFIRMED|FALSE_POSITIVE", "confidence": 0.0-1.0,
 "perspectives": {"A": "...", "B": "...", "C": "...", "D": "..."},
 "d_evidence": "<file:line>", "rationale": "..."}
```

| Arm | Directories |
|---|---|
| contract core (contract assertion only) | `run1`, `run2`, `run3` |
| full stage (contract + cognition + source, priority rule) | `run_full1`, `run_full2`, `run_full3` |
| source-only arm, run as an independent configuration | `run_donly1`, `run_donly2`, `run_donly3` |
| flat single-prompt judge (same inputs as the source-only arm; no perspectives, chain, or rule) | `run_flat1`, `run_flat2`, `run_flat3` |
| re-adjudication after the cognition-corpus leakage audit | `run_fullc1`, `run_fullc2`, `run_fullc3` |
| source-only arm replicated on a second model backbone (same packages and rule; backbone co-varies with the dispatching session) | `run_donlyq1`, `run_donlyq2`, `run_donlyq3` |
| unsubmitted-stream anchor: the 32 candidates registered by the reported run that never entered the 81-pool, adjudicated with the full-stage protocol minus the cognition perspective (its corpus could hold maintainer verdicts for these candidates' families), three runs | `analyses/unsubmitted-anchor/` |
| runs voided during the study, retained for process transparency | `*_voided_*` |

`analyses/` recomputes every number in the paper from these files: the confusion matrices, the
Wilson intervals, the exact McNemar tests over the paired cases, and the stratified recall.

## RQ3 baseline configuration

The baseline is VDBFuzz at revision `7a41449`, run with its released Qdrant template set
(205 templates). Runs included here, with the request and mutation volume recorded in each run's
own logs:

| Directory | Logged HTTP requests | Mutation iterations |
|---|---|---|
| `full-coverage-v3` | 23,258 | 22,540 |
| `qdrant_h2h_official` | 161,046 | 160,772 |
| `qdrant_h2h_depth_partial` | 57,712 | — |
| `qdrant_h2h_v2` | 30,239 | — |
| `qdrant_h2h_breadth` | 5,365 | — |

Large logs are stored gzip-compressed (`.log.gz`). Request counts above were recovered by decoding
each log and counting response-status lines.

Two properties of the released baseline matter for interpreting its reports, and both are
checkable in `analyses/`:

1. **The run-level summary counters are not diagnostic.** The runner classifies a template as a
   success whenever its process exits zero, and neither failure marker it looks for can fire:
   one is emitted by no code path, and the connectivity message the templates actually emit is not
   the string the marker matches. Pointing the runner at a port with no server yields exit code 0
   and a reported 100% success rate. Per-template oracle decisions, not the summary, are the
   usable signal.
2. **The per-template oracle is a liveness check.** Each template passes a `GET /`-returns-200
   check into its mutation loop and records an anomaly once it stops holding. The mutation
   vocabulary is bounded well below the values some crash classes need: the integer boundary set
   tops out at 65,536 (`analyses/keywords_boundary_values.py`) and the dimension candidates at
   10,000 (`analyses/mutator.py`).

## What is deliberately not included

- Third-party papers (the literature cache) — copyright.
- Internal review documents and process notes.
- Author-side environment details: machine paths, session directories, and account names are
  scrubbed; the pipeline's configuration templates are included with placeholders.

## Provenance

- The submission ledger is a snapshot re-verified as of September 2026. Adjudication is treated as
  revisable in the paper, and one candidate (#9149) is reclassified from fixed to disproved; the
  ledger records the post-reclassification state.
- The RQ2 judge outputs were written by the judging agents as each run's output, not reconstructed
  afterwards. The `run_fullc*` directories hold the re-adjudication performed after the
  cognition-corpus leakage audit described in the paper.
- The `run_donlyq*` directories are the second-backbone replication of the source-only arm; the
  `run_task2` directories are the unsubmitted-stream anchor. Packs for `run_task2` were rebuilt
  from the run's own evidence chains (the 81-pool packs do not cover these candidates), and their
  dispatch files state the no-cognition constraint.
