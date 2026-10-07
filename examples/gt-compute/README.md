# GT collection examples

These examples keep your existing Claude Code/Codex harness as the interface and
run extraction in an authorized GT allocation. Start with
[the complete GT procedure](../../docs/guides/gt-compute.md). Installing/configuring is
separate from approving a concrete source plan and cluster resource request.
No example grants an allocation. A real fixed server launch requires an approved
same-job vLLM profile and concrete resource approval; offline examples launch none.

## Student request to the existing agent

```text
Create a Quarry study for medical terminology in my permitted text-bearing PDFs.
Use the jargon starter recipe, retain established terminology and preserve page
locations. Keep my current agent as the interface and use our reviewed GT model
and cluster profiles for extraction. Handle structured inputs for me.

Capture the sources before requesting GPUs. Show every source, failures, models,
mode, estimated token usage, GPU-hour reservation, remaining cumulative caps and
runtime declarations. Do not submit until I approve the concrete collection and
cluster review. Keep raw source contexts out of external tool responses unless
their disclosure is authorized.
```

Use the same procedure for neologisms or cultural vocabulary. Changing the
recipe's inclusion rules changes the research policy; changing a deployment
profile changes where/how the fixed collection runs.

## Site profile template

`site-profile.template.json` is an inert CPU-collector schema example for an
existing institutional gateway. `vllm-site-profile.template.json` illustrates
same-job GPU serving. Their identifiers, paths, hashes and resources are
placeholders, not actual PACE settings. An
administrator/researcher replaces them with an approved site profile; students
select that profile through their agent. No secret values belong in this file.

The template assumes one custom extraction model alias, `researcher`, matching
`configure_compute`. A GLM/DeepSeek or other multi-model profile needs one
`model_artifacts` entry for every actual model alias. Check `inspect_compute`
before filling them. Model digests are declared provenance, not proof of the
weights a remote server actually loaded. The Python executable hash is checked
on the worker node; it must match the preinstalled runtime used by the fixed
worker command.

The CPU template requests four hours, at most two submissions, zero collector
GPUs and zero collector GPU-hours; the gateway's serving allocation remains
separate. The vLLM template requests four hours on one GPU, at most two submissions
and eight cumulative GPU-hours. Each submission reserves its **full requested
allocation**. A quickly completed job does not silently replenish that cap.
Shutdown grace must be at least the recipe's model-request timeout plus 30
seconds and smaller than the allocation walltime. `scratch_env` must identify
site-approved node-local scratch, not shared storage merely named `TMPDIR`.
Walltime uses whole minutes so the reservation matches the scheduler request.
`durable_root` is a pre-existing approved directory visible to the control host
and worker node. The control study's live SQLite database stays on a private local
filesystem; only the frozen bundle, consistent backups, receipts and results go
under the durable directory. The worker also uses separate node-local scratch.

## CLI procedure on the approved Slurm-side control host

These commands refer to a saved, source-captured study. Your agent normally
operates them and remembers IDs; they are provided for reproducible handoff.
Use actual selected profiles and saved IDs in place of capitalized placeholders.
The CLI does not acquire SSH/PACE access. Run these through your approved existing
connection where Slurm commands are available.

Configure before preparing the collection review:

```sh
termfinder --project studies/medical-pilot configure-compute \
  --backend institutional --base-url https://assigned-gateway.example/v1 \
  --model YOUR_SERVED_MODEL --model-version YOUR_REVIEWED_MODEL_REVISION \
  --credential-env GT_INFERENCE_TOKEN \
  --context-limit-tokens 32768 --max-output-tokens 8192 \
  --runtime-manifest reviewed-runtime.json \
  --configuration-reference "Actual researcher-selected approved GT endpoint"
termfinder --project studies/medical-pilot configure-cluster reviewed-site-profile.json
termfinder --project studies/medical-pilot tune-cluster --concurrency 4 --model-concurrency 4
```

The `.example` URL is a nonworking placeholder. Replace it with the administrator's
verified endpoint and token/context contract. `GT_INFERENCE_TOKEN` is a variable
name; supply its value only through the approved environment/secret mechanism,
never these commands or files. The administrator-reviewed runtime declaration
can start from `runtime-manifest.template.json`; replace every placeholder/hash
with verified metadata or null when unavailable.
The all-zero checkpoint hash in the template is a synthetic marker, not a real
artifact digest. A declared `decode` object describes operator metadata; it does
not override the transport's actual request parameters. Quarry records actual
request decoding separately.

For the reviewed same-job vLLM profile, configure
`--backend institutional --base-url http://127.0.0.1:8000/v1` without
`--credential-env`, and select the completed vLLM site profile. Its port and
served model must match this extractor configuration. Ordinary compute
configuration does not launch vLLM; approved cluster submission starts the fixed
server inside that allocation. Shared-host loopback needs site isolation.
Do not expect a server from a previous node to follow a new allocation.

The vLLM template's `artifact_files` must be replaced with the **complete actual
safe file inventory**, each with its verified SHA-256. The small template list is
illustrative; sharded checkpoints need every shard and all required safe config/
tokenizer files. The directory must be pre-staged and visible on the worker node.
The runtime must already contain the reviewed pinned vLLM package. Model
downloads, executable model files, pickle weights and remote-code loading are
excluded. Only the fixed supported launcher is accepted, with bounded startup,
loopback serving and cleanup. This release serves one reviewed model per worker;
it does not pretend that its specialist passes are independent models.
The startup deadline includes artifact hashing and model loading and must fit
inside walltime before the shutdown grace. Keep files immutable after verification.
Loopback/minimal environment/hash checks do not create OS isolation; use the
institution's approved container/job policy.

For this profile, `model_artifacts[0].sha256` is the canonical SHA-256 of the
complete `server.artifact_files` mapping, **not one weight-file hash**. Your agent
can compute that nonsecret inventory binding with:

```python
from termfinder.store import digest
reviewed_profile["model_artifacts"][0]["sha256"] = digest(
    reviewed_profile["server"]["artifact_files"]
)
```

Each individual entry still carries the corresponding file's actual SHA-256.
The all-zero template hashes and placeholder package version cannot establish
model identity or run a real server; replace them with reviewed values.

The concurrency values are starting points for a bounded pilot, not benchmark
results. Tuning preserves research scope and budget; prepare a fresh review.
Inspect/approve the ordinary collection review first. Then prepare and inspect
its cluster review:

```sh
termfinder --project studies/medical-pilot cluster-review COLLECTION_REVIEW_ID
termfinder --project studies/medical-pilot cluster-status
```

Only after the researcher approves that concrete cluster review:

```sh
termfinder --project studies/medical-pilot cluster-submit CLUSTER_REVIEW_ID \
  --researcher-approved --approval-reference "Actual approval message/reference" \
  --allow-cluster --allow-paid
```

`--allow-cluster` permits scheduler execution. `--allow-paid` permits real
extractor requests even when GT inference has zero per-token fees. A fake
rehearsal omits `--allow-paid`; a real run does not. No command line accepts a key.

Reconnect to inspect the saved job:

```sh
termfinder --project studies/medical-pilot cluster-status --job-id CLUSTER_JOB_ID
termfinder --project studies/medical-pilot cluster-status --job-id CLUSTER_JOB_ID \
  --refresh-scheduler --allow-cluster
```

Cancellation and explicit bounded resume use saved job/review IDs:

```sh
termfinder --project studies/medical-pilot cluster-cancel CLUSTER_JOB_ID --allow-cluster
termfinder --project studies/medical-pilot cluster-resume CLUSTER_REVIEW_ID \
  --researcher-approved --approval-reference "Actual bounded resume approval" \
  --allow-cluster --allow-paid
```

Do not submit a replacement merely because the agent disconnected. Inspect the
same job first. If submission timed out, keep its reservation and reconcile the
actual scheduler outcome before replacement. After checking the site's scheduler
history by the recorded Quarry job name, use one of the explicit declarations:

```sh
termfinder --project studies/medical-pilot cluster-resolve CLUSTER_JOB_ID \
  --scheduler-job-id VERIFIED_SLURM_JOB_ID \
  --reconciliation-reference "Reference to actual scheduler history check"
```

Or, only when absence was actually verified:

```sh
termfinder --project studies/medical-pilot cluster-resolve CLUSTER_JOB_ID \
  --verified-absent \
  --reconciliation-reference "Reference to actual verified-absence check"
```

The declaration is an audit event, not authentication of human identity. Do not
blindly retry `sbatch`, erase reservations or invent a history check.

After importing the verified checkpoint/result, use normal evidence inspection,
reversible annotations and release:

```sh
termfinder --project studies/medical-pilot cluster-import --job-id CLUSTER_JOB_ID
termfinder --project studies/medical-pilot status
termfinder --project studies/medical-pilot release gt-pilot-v1
```

The saved release can be re-exported without model calls. A scheduler success
does not establish complete extraction, semantic correctness or recall.
Complete the intended bounded resumes before importing/annotating the control
inventory. Import refuses changed origin bindings instead of overwriting edits.

## Notebook/API procedure

Your coding agent prepares recipes and site settings. A notebook can inspect the
same study and operate the controller. None of the following configuration or
review calls submits a scheduler job:

```python
import json
from pathlib import Path
from termfinder import Project

project = Project("studies/medical-pilot")
site = json.loads(Path("reviewed-site-profile.json").read_text())
project.configure_cluster(site)
project.configure_cluster_throughput(concurrency=4, model_concurrency=4)

# Prepare and approve a fresh ordinary collection review with the existing
# workflow API first. Its actual saved ID is supplied here.
controller = project.cluster()
cluster_review = controller.prepare(collection_review_id)
cluster_review["resources"]
```

After inspecting the concrete review and receiving the actual researcher
decision, the operator can submit through the API's trusted execution gate:

```python
job = controller.submit(
    cluster_review["cluster_review_id"],
    human_approved=True,
    approval_reference=actual_resource_approval_reference,
    allow_execution=True,
    allow_paid=True,  # real institutional extractor, not a billing assertion
)
job["job_id"]
```

Construction and default status read saved state. Explicit scheduler refresh
uses the site's reviewed Slurm commands:

```python
from termfinder.cluster import SlurmScheduler

saved = controller.status(job["job_id"])
refreshed = controller.status(job["job_id"], scheduler=SlurmScheduler())
# Once stopped and a verified checkpoint is available:
imported = controller.import_result(job["job_id"])
project.page_inventory(limit=20)
```

Keep outputs bounded and omit raw sensitive source text from external harness
responses. Cancel/resume through `controller.cancel(...)` and
`controller.resume(...)` with the same concrete approval/gates as submission.
The controller retains allocation history and caps independently of a notebook.

## Trusted token counting and runtime provenance

Operator model configuration may carry `runtime` provenance. The CLI accepts
`configure-compute --runtime-manifest reviewed-runtime.json`; the Python API
accepts `Project.configure_compute(..., runtime=runtime_declaration)`. Record
reviewed hashes and available runtime/hardware settings. Missing values remain
null with reasons; runtime declarations do not automatically inspect a server.

Advanced trusted Python integrations can register a preinstalled tokenizer:

```python
from termfinder import PromptTokenizer

tokenizer = PromptTokenizer(
    identifier="reviewed-tokenizer-revision",
    version="reviewed-chat-template-revision",
    count_prompt=count_full_server_rendered_prompt,
    tokenizer_sha256=reviewed_tokenizer_sha256,
    chat_template_sha256=reviewed_chat_template_sha256,
)
# Callback is trusted installed Python, never agent/source/extraction JSON.
# It includes chat-template and special-token overhead, not just passage text.
result = project.collect(
    allow_paid=True, tokenizers={"researcher": tokenizer}
)
```

This last snippet is a direct Python collection integration. The fixed Slurm
worker does not load arbitrary tokenizer code from a profile. Without a trusted
registration, token admission uses the explicitly recorded UTF-8-byte estimate
and template reserve, splitting windows while retaining original codepoint
offsets. The fallback is conservative for common byte-based tokenizers, not an
exact guarantee for every tokenizer or server template.

## Verification and the first real pilot

After reviewing `offline_demo.py`, run it in the finite OS isolation described
below with a fresh output directory. It rehearses both Broad and Specialists on
the same synthetic jargon/Unicode and invalid-PDF fixtures:

```sh
python examples/gt-compute/offline_demo.py --out verification/gt-first-demo
```

Select one mode with `--mode broad` or `--mode specialists`. The output includes
`acceptance_report.json`, frozen complete-source blank annotation packets,
consistent checkpoints and CSV/JSONL/Parquet/annotation exports. The fake
scheduler never invokes Slurm; the fake provider never accesses network or keys.
The demo verifies cancellation, a partial one-request checkpoint, reconnect and
resume, exact source offsets, reversible annotations, visible parsing failure,
finite allocation caps and repeated frozen exports. Blank packets are not gold
annotations and synthetic counts are not recall measurements.

Offline verification uses synthetic sources, fake responses and a fake scheduler;
it does not launch a real Slurm job, call an external agent or measure local-model
quality. Follow [verification isolation](../../docs/development/reproduce.md) before
executing reviewed scripts/tests. A real GT pilot needs explicit authorization,
site settings and representative complete-source annotations. Measure resource
use and false negatives before changing models, quantization or scale.
