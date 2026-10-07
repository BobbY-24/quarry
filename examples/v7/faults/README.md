# Offline request-keyed recovery protocol

This directory contains the inert protocol for the real-engine recovery suite.
The runner creates its own synthetic corpus and writes actual request hashes,
dispatch receipts, database state, frozen exports and measured comparisons into a
new output directory. No external experiment or provider call is authorized here.

```bash
quarry-study faults --out results/recovery --concurrency 2
```

Read [V7_RECOVERY.md](../../../docs/V7_RECOVERY.md) for the hypotheses, intervention
boundaries, metrics and limits. The [schedule](schedule.json) records the named
conditions before outcomes are observed. It contains no executable instructions.
