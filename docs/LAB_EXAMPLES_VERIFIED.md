# Offline verification of the named NLPx examples

Checked October 5, 2026. This supplements the engine's existing
[verification record](VERIFIED.md); it does not replace it or claim extraction
accuracy on the named research datasets.

The [student guide](NLPX_STUDENT_GUIDE.md) and [shared procedure](LAB_PROTOCOL.md)
were reviewed against the implemented CLI/API. Public faculty rosters and
primary papers were checked for student names, authorship and task descriptions.
The proposed workflows do not assert PI requests, student assignments or adoption.

`tools/check_lab_examples.py` exercised **11 recipes × 2 modes = 22 workflows**
using the independently installed V6 package, local synthetic text and a provider
stub that must never dispatch. All passed:

- Strict recipe validation, labeled literal few-shots and matching batch metadata.
- Two Broad extraction routes and four Specialists routes on identical source
  evidence, with community labels matching each lens.
- Actual CLI project setup, local ingestion, estimates, snapshots and exports.
- Retained content-origin metadata and null publication dates with reasons.
- Blind full-source annotation packets created before any extraction attempt.
- Visible spending-budget stops and pending jobs that survive reopen/resume.
- Zero provider calls and no cost ledger charges.
- Byte-identical re-exports in CSV, JSONL, Parquet and annotation formats after
  later run records were added: 36 export files per workflow, 792 comparisons.

The macOS Seatbelt verification environment denied network and unrelated file
reads, had an empty credential environment and finite CPU/wall/file limits. The
sandbox probes passed. No research datasets were downloaded, paid collection was
launched, data was published or anyone was contacted for these examples.

The `../verification/lab-examples-report.json` (local artifact) records each
student/mode, route counts, pending jobs and hashes of reviewed guide inputs.
The `../verification/lab-examples-sandbox.json` (local artifact) records isolation,
resource limits, installed-runtime invocation and reviewed file hashes.

On the reviewed macOS setup, reproduce with the supported installed interpreter
and explicit runtime root:

```sh
/usr/bin/env -i PATH=/usr/bin:/bin .venv/bin/python -I -S tools/verify_offline.py \
  --python .venv/bin/python --runtime-root REVIEWED_PYTHON_RUNTIME_ROOT \
  --report verification/lab-examples-sandbox.json \
  -- tools/check_lab_examples.py
```

Replace the runtime placeholder deliberately. Do not grant a filesystem root or
home directory as the runtime. For Linux, use the network-disabled isolated
container procedure in [verification documentation](VERIFICATION.md) and run the
same checked script with the installed package.

These checks establish that students can prepare and hand off each configured
workflow. Measuring research performance requires an explicitly authorized
corpus/budget pilot and independent complete-source human gold, as described in
the shared procedure. The synthetic texts and tiny estimates in the machine
report are workflow probes, not representative workload costs or findings.
