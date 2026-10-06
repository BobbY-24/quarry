# Durable GT collection verification — 6.6.0

Recorded on 2026-10-06 on macOS with Python 3.12.14. Verification uses the
reviewed Seatbelt launcher, an empty credential environment, denied networking
and unrelated personal-file reads, and finite CPU/file/wall limits. Scheduler,
provider and server-process test doubles are explicit synthetic fixtures.
No GT allocation, model download, actual vLLM process, external agent call or
paid extraction request is part of these checks.

The release keeps the existing agent as its interface. Its Slurm controller
freezes the approved study and resource request, persists a receipt before
submission, reserves worst-case resources, and reconciles uncertain outcomes
explicitly. Workers use node-local active state and consistent durable backups;
reconnecting does not submit a replacement. Result import protects later local
annotations and keeps failures and partial work visible.

## Verification results

| Check | Result |
| --- | --- |
| Fresh installed-wheel suite | **373 tests passed** in 36.053 seconds |
| Cluster lifecycle and recovery | 36 tests passed within the full suite |
| Token admission, runtime and cache identity | 15 tests passed within the full suite |
| Agent/CLI execution and storage gates | 14 tests passed within the full suite |
| Fixed serving lifecycle with fake processes | 12 tests passed within the full suite |
| Three starter recipes × Broad/Specialists | Six acceptance projects passed |
| Durable GT demo, both modes on the same fixtures | Cancellation, checkpoint/reconnect/resume, exact evidence, caps, failures, annotation reversal and identical exports passed |
| Independent installation | 49 package files match reviewed source bytes; no source import or sibling dependency |
| Live Slurm, real model/GPU processes, paid calls | Zero |

The wheel was built in a fresh builder with pinned setuptools 84.0.0, wheel
0.48.0 and packaging 26.0, then installed in another fresh environment with
pypdf 6.19.0 and pyarrow 25.0.1. All dependency wheels were local and networking
was denied. Earlier environments, failed-build receipts, projects and outputs
were retained. Earlier [6.5 results](COMPUTE_VERIFIED.md) remain historical records.

Verified wheel SHA-256:

```text
6a4df6e1e26d81722c9b3de694b49a324e692975b5cc874f706015d604d789d6
```

Local ignored receipts include `verification/cluster-wheel-final.json`,
`cluster-build-release-sandbox.json`, `cluster-final-installed-suite-sandbox.json`,
`cluster-final-install-sandbox.json`, and `cluster-final-recipes-sandbox.json`.
The six-recipe demonstration reports exact evidence, separate senses,
single-extractor retention, PDF pages, interruption/resume, reversible annotations,
visible failures/budget stops and byte-identical saved exports in every format.
The GT receipt is `verification/gt-demo-fixed2-sandbox.json`, with its synthetic
acceptance report under `verification/gt-demo-fixed2/`. Broad makes two fake
requests; Specialists makes four. Both retain the same four expected term/sense
records, including discoveries exclusive to each extractor. Those fixture counts
are test expectations, not research quotas or recall measurements.

Before publication, the staged repository and locally reachable history receive
a bounded credential-pattern check. It reports only classifications/paths/line
numbers, never matched values, and does not read personal credential files.
Patterns cannot prove absence of arbitrary unrecognized secrets. Local runtime,
model weights, profiles containing personal configuration, research datasets,
environments and receipts remain excluded from the commit.

## What the checks establish

Tests exercise changed-profile approval invalidation, disabled execution/storage
gates, uncertain submissions, early worker/submission races, cumulative allocation
caps, cancellation, periodic backups, checkpoint recovery, partial import/resume,
interrupted import, runtime/artifact integrity, bounded token admission, Unicode
offsets, model-specific cache invalidation, resource accounting, exact paged
resource inspection and reproducible exports.

The fixed vLLM adapter checks complete pre-staged file hashes and the exact
installed package version, uses SafeTensors, disables remote model code and
plugin autoload, preserves one warm process across windows, and applies bounded
readiness/cancellation/cleanup. Offline tests inspect its fixed command and
environment through fake processes; they do not establish real GPU compatibility
or model quality. Loopback and offline download settings require site-provided
network/container isolation.

## Reproduce and hand off

Use a fresh installed environment and the reviewed OS isolation in
[VERIFICATION.md](VERIFICATION.md). Omit `--source` when testing the wheel.
Inside that isolation, run:

```sh
python -m unittest discover -s tests -q
python examples/offline_demo.py --out verification/fresh-all-recipes
python examples/gt-compute/offline_demo.py --out verification/fresh-gt-demo
```

Use new output paths: demonstrations refuse to overwrite earlier work. Local
receipts, wheels, environments and synthetic result databases remain ignored.
See [the student and site procedure](GT_COMPUTE.md) and
[CLI/notebook examples](../examples/gt-compute/README.md). Ordinary students
describe their study in their own agent; that agent manages saved IDs and inputs.

## Remaining authorized pilot work

Live Linux Slurm, GT authentication/filesystem behavior, real vLLM/GPU execution,
allocation charges, privacy policy, throughput and extraction quality remain
unverified. The operator supplies actual approved site settings, immutable model
artifacts and compatible pinned runtime. Dependency provenance and OS isolation
remain part of that site review; a Python-binary hash is not complete runtime
attestation. Gateway model/hardware metadata are operator declarations.

The first separately authorized pilot should exercise a real queue, disconnect,
walltime checkpoint, resume and result import on a small permitted corpus, then
compare extraction with independent annotations of complete held-out sources.
Report precision, recall and false negatives by domain/language using grouped
splits. Software tests, candidate counts and model agreement do not measure
research recall. Frozen exports replay stored records; new model inference can
vary across hardware/runtime versions.
