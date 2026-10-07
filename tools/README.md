# Maintained verification tools

These tools support release review and reproduction; they are not part of the
installed collector. Review them and use the finite OS isolation procedure in
[reproduce](../docs/development/reproduce.md). They require no service credentials.

| Tool | Purpose |
| --- | --- |
| `check_repository.py` | Local Markdown/notebook links, with no network or example execution |
| `ci_offline.py` | macOS/Linux isolation, resource bounds and source-drift receipts |
| `ci_sqlite.py` | Pinned source acquisition, isolated native build and actual SQLite runtime health |
| `ci_linux_isolation.py` | Reviewed hosted Ubuntu sandbox prerequisite and safe audit categories |
| `ci_smoke.py` | Fresh installed wheel, CLI/API/MCP, artifact and frozen-export checks |
| `smoke_installed.py` | Installed CLI workflow and all code cells in the researcher notebook |
| `check_lab_examples.py` | Validate researcher-editable recipes and their source metadata |
| `reliability_load.py` | Bounded short-source interruption/resume/export rehearsal |
| `reliability_mixed.py` | Multilingual HTML/text/PDF studies sharing a quota under keyed faults |
| `soak_resilience.py` | Larger finite resilience rehearsal for selected limits |
| `make_legacy_fixture.py` | Rebuild compatibility evidence using a separately supplied old revision |
| `verify_offline.py`, `offline.sb` | Reviewed macOS isolation launcher and policy |

Run only the checks appropriate to a change. Synthetic timing and inventories
are engineering evidence; source-level recall and semantic quality need the
[research evaluation protocol](../docs/research/evaluation.md).
