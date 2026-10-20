# Quarry name and compatibility

The standalone repository is now [`BobbY-24/quarry`](https://github.com/BobbY-24/quarry).
Quarry is the product name; V6.4.0 remains the collector engine version.
The public README, diagrams, browser labels and package description use Quarry.
No collection policy, provider route, prompt version, schema, model rate, budget,
evidence rule or stored record identity changes as part of this rename.

The distribution and the Python package are both `quarry` (renamed from `nlpx-termfinder` and
`termfinder` on 2026-10-20). It installs `quarry` and `quarry-mcp` commands; `termfinder` and
`termfinder-mcp` remain as aliases. Re-run `quarry connect` once so an existing agent registration
points at `quarry-mcp`. Unchanged identifiers: `v6-collect-research` (skill), `v6`
(MCP registration), `v6-studies` and the existing connection lock/settings paths.
No PyPI package was published and no personal agent settings were migrated.
An upgraded packaged skill has new bytes: use a fresh workspace or the deliberate
V6-only migration procedure in [AGENT_NATIVE.md](AGENT_NATIVE.md). The installer
continues to refuse conflicting or customized replacement.

The [standalone import manifest](STANDALONE_REPOSITORY_MANIFEST.json) describes
the original 149-file publication before this rename. Its former repository URL
and file hashes are historical provenance, not rolling checksums. The
[earlier upload manifest](SOURCE_UPLOAD_MANIFEST.json) belongs to the original
collector repository. Both remain unchanged. Current branding and diagrams are
recorded by this repository's Git history.

The original collector repository and historical V6 verification receipts retain
their names and hashes. New source installation creates a new local wheel; the
old recorded wheel hash does not identify this branding revision.

The Quarry revision passed all 277 source-level offline tests in 21.263 seconds
on macOS. Publication checks resolved 196 local documentation links and anchors,
matched all four README diagrams to the diagram guide, and parsed both static SVG
assets. The changed skill and workflow reference were re-audited: after product
name normalization, their original security and authorization rules are unchanged;
the added compatibility note explicitly forbids overwriting customized connections.
These checks used a clean environment and finite macOS Seatbelt isolation with
network and unrelated file reads denied. They do not establish live provider
accuracy, Linux execution, or usability in a real coding-agent host.
