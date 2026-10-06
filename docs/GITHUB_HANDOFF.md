# Quarry GitHub source handoff

Quarry, powered by the V6 engine, lives at the root of the private
[`BobbY-24/quarry`](https://github.com/BobbY-24/quarry)
repository. Clone it, install the independent package, and connect it to your own
coding-agent workspace. The earlier collector and nested V6 copy remain in the
separate [`community-term-collector`](https://github.com/BobbY-24/community-term-collector)
repository. Creating this repository did not modify that repository or the local
V3, V4, V5, study data, outputs or ongoing integration work.

## Install from the default branch

Use GitHub's normal authenticated HTTPS/SSH workflow; never put a token in a URL.
With an authenticated GitHub CLI and an installed Python 3.11–3.13:

```sh
gh repo clone BobbY-24/quarry
cd quarry
python3.13 -m venv .venv-6.5
. .venv-6.5/bin/activate
python -m pip install -r requirements-build.txt
python -m pip install --no-build-isolation .
mkdir -p research-workspace
termfinder connect --host claude --workspace "$PWD/research-workspace"
```

Use `--host codex` or `--host generic` as appropriate. Follow the host's normal
trust/reload steps and verify an actual `list_studies` call. The default connection
is offline only. [Own-agent setup](AGENT_NATIVE.md) explains connection, review,
resume and the separately authorized real-provider gate.
Choose each study's own API/local/institutional extraction backend using
[compute setup](COMPUTE.md); the repository supplies no developer credential or
Georgia Tech allocation. [6.5 verification](COMPUTE_VERIFIED.md) records the new
installed-wheel tests and credential-audit scope.

## Publication scope and provenance

This is a source-only import of `V6-community-term-finder/` from the original
repository's published commit `4e9b32922d08fdea2b668f96e7dab16bc2a98526`.
At import, the package, recipes, profiles, prompts, skill, tests and synthetic
fixtures retained their bytes. Documentation adapted the repository URL and root
installation path. Later Quarry naming, documentation and diagram updates are
recorded in this repository's Git history; the import manifests describe the
original snapshots rather than the current branding.

The [standalone preparation manifest](STANDALONE_REPOSITORY_MANIFEST.json) records
the exact upstream repository/commit/subdirectory and copied-file hashes. It
excludes its own bytes to avoid a self-hash. Subsequent changes are recorded in
this repository's Git history.

The [historical upload manifest](SOURCE_UPLOAD_MANIFEST.json) refers to commit
`76228401e2d14cab6ed859e32d1141bad8294572` in the **original repository**, not this
repository's independent Git history. Its hashes describe that earlier snapshot.
`tools/prepare_github_upload.py` is retained historical tooling for that nested
layout; it is not used to install or operate this standalone package.

Environments, wheels, raw verification workspaces/reports, study databases,
collected datasets, credentials, generated host configuration and the unfinished
legacy integration are excluded. Existing studies are not supplied by this repo.

[HARNESS_VERIFIED.md](HARNESS_VERIFIED.md) records the earlier verified macOS V6.4
build with 277 installed-package tests and synthetic stdio/API/notebook workflows.
Its wheel hash and local evidence paths identify that build; they do not identify
a newly built standalone wheel. Source installation produces its own local wheel.
The standalone layout is checked separately using the same six recipe/mode demo
workflows and exact upstream file hashes, with fake providers and network denied.
These are software checks, not field accuracy or a live host usability pilot.

Follow [VERIFICATION.md](VERIFICATION.md) for reviewed finite OS isolation and
target-machine checks. [PILOT.md](PILOT.md) retains the known Linux, live-host,
provider quality/rates, rights and publication limitations. No paid collection,
external-agent session, public visibility change or research-data publication
was part of this import.
