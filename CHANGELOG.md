# Release notes

## 6.7.1

- Organize researcher guides, reference, research protocols, reliability and
  development documentation behind one index.
- Remove obsolete upload scripts, version-specific demos and development
  reports from the active tree; preserve historical revisions in Git.
- Update notebook and packaged agent-skill links to the current layout.
- Keep the extraction engine, study schemas, recipes and model profiles unchanged.

The package patch version changes because the distributed skill references
changed. Existing projects and frozen datasets retain the V6.7 compatibility
contract. Existing reviewed cluster bundles still require their pinned runtime;
review a new bundle when upgrading the package. See
[reproduction](docs/development/reproduce.md).

## 6.7.0

Add scoped failures, durable response and dispatch receipts, bounded process
deadlines, same-host quotas, durable controller operations, indexed recovery,
atomic exports and private diagnostics. See the
[reliability design](docs/reliability/design.md),
[compatibility rules](docs/reliability/compatibility.md) and
[measured offline envelope](docs/reliability/results-v6.7.md).

Earlier releases remain available through Git history. Their synthetic checks
do not establish extraction quality, participant usability or GT performance.
