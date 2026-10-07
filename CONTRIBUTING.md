# Contributing to Quarry

Use Python 3.11–3.13 with the [required SQLite patch](docs/reliability/compatibility.md).
Install into a fresh environment; keep researcher studies and credentials out of
the checkout. The package has no dependency on another Quarry version directory.

```sh
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-build.txt
python -m pip install --no-build-isolation .
```

Read the [architecture](docs/reference/architecture.md) and
[reliability contract](docs/reliability/contract.md) before changing collection
or persistence. Keep exact observed evidence, singleton discoveries, distinct
senses, unresolved attempts and saved dataset versions. Model agreement is not
a recall measurement; semantic correctness needs separate human evaluation.

Run the [bounded offline reproduction procedure](docs/development/reproduce.md)
for the affected behavior. It uses fake providers and OS isolation, a wheel
installed into a separate environment, and frozen-export checks. CI never needs
real API credentials, participant data, paid collection or a GT allocation.

Keep source in `src/termfinder`, regression tests and synthetic fixtures in
`tests`, working researcher examples in `examples`, and maintained verification
tools in `tools`. Follow the [documentation index](docs/README.md) when adding a
guide. Generated runtimes, wheels, logs and study data are ignored; do not commit
them. Historical build diaries and superseded scripts belong in Git history,
not the active documentation tree.

Describe the problem, resulting behavior, validation and remaining limits in
the pull request. Changes to packaged prompts, profiles, recipes, skills or
processing semantics need explicit version/compatibility review. Never include
credentials, raw provider payloads or unrelated research data in issue reports.
