# Offline reliability CI

The workflow in `.github/workflows/offline-reliability.yml` prepares Linux/macOS
and Python 3.11/3.12/3.13 checks. It uses `contents: read`, no repository secrets,
no paid providers, no Slurm, no deployment and no privileged pull-request event.
Checkout does not persist credentials. Dependency acquisition is a separate
networked step; application tests, wheel build, installation and smoke checks
execute with an empty credential environment. macOS denies all networking;
Linux uses a separate network namespace with no host/external connectivity
(private loopback is permitted).

`tools/ci_offline.py` requires macOS Seatbelt or Linux bubblewrap. It probes
network and unrelated-file denial before executing code and fails closed if
isolation is unavailable. Linux also verifies the namespace differs from its
parent. Each invocation has wall, CPU, file-size and open-file
bounds. Linux adds a per-process address-space bound. Wall timeout terminates
the process group; escaped/daemonized processes are outside the supported
adapter contract. Logs are capped at 8 MiB; reaching that cap fails the check.
This launcher grants reviewed repository/runtime reads and repository/private
temporary writes, rather than arbitrary home data access.

```bash
env -i PATH=/usr/bin:/bin /path/to/python -I -S tools/ci_offline.py \
  --python "$PWD/.ci/build-runtime/bin/python" \
  --runtime-root "$PWD/.ci/build-runtime" \
  --base-runtime-root /path/to/reviewed/base-python \
  --source --report verification/ci/unit.json --timeout 600 \
  -- -m unittest discover -s tests -q
```

The routine matrix exercises fault/regression tests and real bounded local
quota contention. `tools/check_repository.py` checks local
Markdown/notebook links without fetching URLs or executing examples. A fresh
installed wheel exercises CLI, Python API, stdio MCP,
packaged fixtures/assets, synthetic credential rejection and frozen byte-equal
CSV/JSONL/Parquet/annotation exports. Dependency wheels and the built wheel get
SHA256 receipts; package payloads are compared with reviewed source/assets.
Direct build/runtime versions are pinned. Downloaded wheel hashes identify
acquired artifacts; they are not independently verified upstream signatures or
a committed cross-platform dependency hash lock.

Manual dispatch adds one larger synthetic rehearsal on Linux/Python 3.12:

```bash
# Run with the same isolation launcher, with --timeout 900 --cpu-seconds 900.
python tools/reliability_load.py --sources 1000 --report verification/ci/load.json
```

The load report records source count, interruption/resume/cache behavior,
frozen export hashes, database/page sizes, peak RSS and timings. Synthetic
software checks cannot establish real API/GPU throughput, availability, billing
or extraction precision/recall. Source-level research evaluation remains separate.

Action pins were checked against the maintainers' release and commit pages:

| Action | Release | Verified immutable commit |
|---|---|---|
| checkout | v4.2.2 | [11bd71901bbe5b1630ceea73d27597364c9af683](https://github.com/actions/checkout/commit/11bd71901bbe5b1630ceea73d27597364c9af683) |
| setup-python | v5.6.0 | [a26af69be951a213d495a4c3e4e4022e16d87065](https://github.com/actions/setup-python/commit/a26af69be951a213d495a4c3e4e4022e16d87065) |
| upload-artifact | v4.6.2 | [ea165f8d65b6e75b540449e92b4886f43607fa02](https://github.com/actions/upload-artifact/commit/ea165f8d65b6e75b540449e92b4886f43607fa02) |

Receipts include actual commands, platform/runtime, isolation probes, bounds,
exit status, elapsed time and source hashes. Source hashes are captured before
execution and checked afterward; source drift fails a successful invocation.
A reviewable tree is required. CI uploads only bounded
synthetic receipts and the wheel for 14 days. Published workflow results identify
actual remote outcomes; local receipts and historical reports do not establish
that a hosted matrix passed.

The project store requires a SQLite runtime containing the WAL-reset fix
(3.51.3 or later, or the 3.50.7/3.44.6 maintenance fixes). A matrix interpreter
with an older unpatched SQLite stops before project writes or inference; its
job needs a reviewed patched runtime. Do not disable the gate to obtain green
CI. Same-host quota registries use DELETE journaling rather than live WAL.

Hosted runner labels and `setup-python` versions do not guarantee either a
patched SQLite library or working namespace isolation. Verify both prerequisites
on the selected runner image. A non-JSON Linux probe failure means the sandbox
or interpreter did not start successfully; its conservative false flags are not
evidence that application code escaped isolation. Application execution remains
blocked. Fix the reviewed runtime or runner prerequisite rather than disabling
the SQLite gate, running application tests unsandboxed, or granting broad
filesystem access. Python builds without search-only directory flags also need
compatibility review under the narrow macOS filesystem policy.
