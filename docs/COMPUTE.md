# Choose your own API, local model, or institutional compute

**Each researcher chooses the models and account that Quarry uses. Installing
Quarry does not connect to the developer's account, and cloning the repository
does not provide an API key.** The default connection is offline-gated;
rehearsals use the scripted fixture provider. Real extraction uses the study's explicitly configured endpoint and
only the named credential supplied by the operator's environment.

Two model layers are independent:

| Layer | What it does | Whose resources it uses |
| --- | --- | --- |
| Your Codex, Claude Code, or other agent | Turns your idea into a plan; operates Quarry tools | The account or compute configured in that harness |
| Quarry's extractors | Read bounded source passages and propose grounded records | The API account, local server, or institutional endpoint you configure for this study |

A ChatGPT/Claude subscription does not automatically supply Quarry's extractor
API access. Quarry does not read your harness's keys or inherit a developer key.
Harness spending, local electricity, model downloads, and scheduler/GPU charges
are outside its per-token extraction ledger.

## Configure through your agent

After connecting Quarry, paste this before preparing your first real study:

```text
Set up my Quarry extraction compute for this study. Keep my planning-agent
account separate. Present these choices: my own API, my local model, or my
institutional compute. Tell me the effective endpoint, model and version,
credential environment variable name if required, routing, costs and limits.

Use configure_compute only for the backend I choose, recording this instruction
as the configuration reference. Never ask me to paste a key into chat, put a key
in a profile, or reuse someone else's key. Confirm the saved choice with
inspect_compute. Do not download a model, launch compute, probe a provider,
or collect until those actions are explicitly authorized.
```

You supply a backend and, for a custom server, its model identifier and reviewed
endpoint. Your agent writes the validated settings; you do not write JSON. A
missing credential is reported by presence and variable name, never by value.
The read-only compute inspection makes no network request. Open or create the
study first; the choice belongs to that saved study and persists across sessions.

Compute configuration is an operator decision, separate from agent-generated
research inputs. A plan cannot change the endpoint or supply credentials. After
configuring compute, prepare the study with `model_profile="configured"` so the
plan uses that saved choice. Changing compute invalidates an earlier plan review:
prepare and review again. After extraction jobs exist, use a new study for a
different compute profile so results remain attributable to their actual models.

The default connected server is offline only. The compatibility flag
`--allow-paid` enables **real model requests**, including requests to local
servers with no per-token fee; its name does not mean every request is paid.
Connecting with that flag and approving the complete finite collection plan are
separate actions. An MCP tool cannot enable the launch gate. Follow
[agent connection instructions](AGENT_NATIVE.md#real-provider-authorization)
and preserve an existing offline connection when creating a real one.

## Option A: use your own API account

The preserved presets are:

| Preset | Transport/account | Required environment name |
| --- | --- | --- |
| `glm-deepseek` | Fireworks; GLM and DeepSeek are independently routed extractors | `FIREWORKS_API_KEY` |
| `gemini` | Google's Gemini API; separate profile | `GEMINI_API_KEY` |

These are model/routing configurations, not bundled accounts. Their recorded
identifiers and rates came from V5; verify availability, prices, and adapter
compatibility before authorizing a pilot. The account that issued the key receives
any provider bill. A lab-funded account is appropriate only when its owner has
authorized your use; prefer a researcher-specific credential and provider-side
limits over sharing a personal key.

Ask your agent to configure the preset, or use the installed CLI:

```sh
termfinder --project /path/to/study configure-compute \
  --backend api --preset glm-deepseek \
  --configuration-reference "Researcher selected their Fireworks account"
termfinder --project /path/to/study compute
```

Supply the credential through the approved secret/environment mechanism of the
process that launches the Quarry MCP server or CLI. A variable available in one
terminal is not necessarily inherited by a desktop agent application. Restart
the connection after changing its environment when the host requires it. Store
only the variable **name** in configuration; keep the value out of chat, command
arguments, notebooks, source files, host JSON/TOML, screenshots, Git, and exports.
Quarry does not load arbitrary `.env` files automatically. Use a dedicated
uppercase credential variable ending in `_KEY`, `_TOKEN` or `_SECRET`; interpreter,
loader and TLS-control environment names are rejected rather than inherited.

A custom API uses the OpenAI-compatible **chat completions** transport. For
example, the following placeholder values must be replaced with the exact
reviewed model, endpoint, and current rates:

```sh
termfinder --project /path/to/study configure-compute \
  --backend api --base-url https://your-approved-provider.example/v1 \
  --model YOUR_SERVED_MODEL --model-version YOUR_REVIEWED_VERSION \
  --credential-env QUARRY_PROVIDER_KEY \
  --input-per-million YOUR_VERIFIED_INPUT_RATE \
  --output-per-million YOUR_VERIFIED_OUTPUT_RATE \
  --context-limit-tokens 32768 --max-output-tokens 8192 \
  --response-format json_object \
  --configuration-reference "Researcher reviewed this provider and pricing"
```

Custom API rates must be explicit. Token limits are examples: use the server's
actual supported context/output limits and include prompt overhead. Choose
`--response-format none` only when the server does not accept the JSON response
format option; Quarry still requires valid structured extraction replies and
performs deterministic grounding. Arbitrary native APIs, including an endpoint
that only supports Anthropic Messages, are not supported by this adapter.

In a notebook, the same operator decision uses the Python API:

```python
from termfinder import Project

study = Project("my-study")
study.configure_compute(
    backend="api", preset="glm-deepseek",
    configuration_reference="Researcher selected their own Fireworks account",
)
study.compute()  # Names/presence only; no key values or provider request.
setup = study.prepare_agent_setup({
    "research_question": "Which new expressions occur in my permitted sources?",
    "starter_recipe": "neologisms", "budget_usd": 10, "max_sources": 30,
})  # Inert planning inputs; prepare/review permitted sources before collection.
```

This example writes configuration and planning state only. A custom endpoint
uses the same named parameters as the CLI. A custom single-model configuration
has one general pass; specialist mode adds the recipe's lenses using that model.
The GLM + DeepSeek preset retains two independent general extractors and their
grounded union. Advanced multi-model profiles remain supported by
`Project.configure(recipe, profile)` in a separate, unconfigured project;
the ordinary compute picker does not assemble multiple custom endpoints.

## Option B: use an already installed local model

Quarry can connect to a reviewed OpenAI-compatible server on numeric loopback,
for example `http://127.0.0.1:11434/v1` for local Ollama or
`http://127.0.0.1:8000/v1` for local vLLM. Credential-free mode is permitted only
on a loopback endpoint. HTTP elsewhere and unauthenticated remote endpoints are
rejected. `localhost` in this document means the same machine and network
namespace as the Quarry process; the validated examples use `127.0.0.1`.

Ollama documents local `/v1/chat/completions` and distinguishes local serving
from its cloud service. Its default bind is loopback. A cloud-backed model
selected through Ollama is still cloud inference; use locally installed weights
when your requirement is that extraction text stays on your machine.
[Ollama compatibility](https://docs.ollama.com/api/openai-compatibility),
[Ollama FAQ](https://docs.ollama.com/faq).

For an installed, reviewed Ollama runtime, you can start a foreground server:

```sh
OLLAMA_HOST=127.0.0.1:11434 ollama serve
```

Reuse an existing approved server instead of starting a second one. Choose the
exact installed model; do not treat an example model name as a recommendation
that it fits your hardware or meets your study's quality requirements. Record
the model's artifact digest/checkpoint revision and quantization in the version
and configuration reference. Freeze or retain those artifacts; a mutable tag
alone cannot identify the weights used in a published experiment.

```sh
termfinder --project /path/to/study configure-compute \
  --backend local --base-url http://127.0.0.1:11434/v1 \
  --model YOUR_INSTALLED_MODEL --model-version YOUR_ARTIFACT_DIGEST \
  --context-limit-tokens 32768 --max-output-tokens 8192 \
  --response-format json_object \
  --configuration-reference "Researcher selected reviewed local weights"
termfinder --project /path/to/study compute
```

No fake API key is necessary for this credential-free transport. The extractor
receives the same bounded prompt and is subject to the same audit, budget,
schema, grounding, recovery, and resume rules. A small model may produce malformed
replies or miss records; audit queues and independent source-level evaluation
are still necessary. Deterministic validation does not make model generation
deterministic or establish recall.

Ollama/vLLM installations and model weights are separate, optional dependencies.
Quarry neither installs them nor downloads model code through compute setup.
Review and pin them using your machine or institution's approved workflow. Keep
services within the authorized session and stop a server you started when the
session ends. Do not create startup hooks just to use Quarry.

## Option C: use Georgia Tech or another institution's compute

There is no universal Georgia Tech API key or assumed NLPx allocation. PACE
describes Phoenix as research compute where faculty can add their research group
to an account, and ICE as instructional compute for teaching. Use only the
cluster/account and workload that your faculty sponsor and administrators have
authorized. Student status or course access does not establish permission for an
unrelated research collection.
[PACE participation](https://pace.gatech.edu/participation/),
[Phoenix](https://pace.gatech.edu/phoenix-cluster/),
[ICE](https://pace.gatech.edu/ice-cluster/).

Two deployment patterns work:

1. **Quarry and the model server inside your assigned allocation.** Obtain an
   approved interactive or batch allocation, use its reviewed runtime/container
   and model weights, and bind the server to loopback. Run Quarry on the same
   allocated machine/network namespace against that endpoint. Run inference on
   allocated compute resources rather than a shared login node. Phoenix uses
   Slurm; follow the institution's current submission procedure and limits.
   [Phoenix](https://pace.gatech.edu/phoenix-cluster/),
   [PACE guidance on resource-intensive work](https://pace.gatech.edu/posts/?m=202304).
2. **An institution-operated authenticated inference gateway.** Obtain the
   administrator's verified HTTPS endpoint, supported served-model identifier,
   context limits, billing assumptions, and your own access credential. Save
   only the credential environment name in Quarry. TLS verification stays
   enabled. This is an explicit server connection, not a built-in PACE connector
   or an automatic allocation request.

For pattern 1, after the approved runtime and weights are already available,
this foreground vLLM server command illustrates the application layer only:

```sh
vllm serve /path/to/reviewed-local-model \
  --host 127.0.0.1 --port 8000 --served-model-name quarry-model
```

The model must support chat completions and a suitable chat template. Record
the exact runtime, weights revision, tokenizer/chat template, quantization, and
server configuration in the study's reproducibility notes. Follow the reviewed
runtime's isolation procedure; do not enable model-supplied remote code or
automatic tools just because a model repository suggests them.
[vLLM OpenAI-compatible server](https://docs.vllm.ai/en/stable/serving/online_serving/openai_compatible_server/).

Configure the study's client endpoint without submitting any scheduler job:

```sh
termfinder --project /path/to/study configure-compute \
  --backend institutional --base-url http://127.0.0.1:8000/v1 \
  --model quarry-model --model-version YOUR_REVIEWED_CHECKPOINT_REVISION \
  --context-limit-tokens 32768 --max-output-tokens 8192 \
  --response-format json_object \
  --configuration-reference "Authorized allocation; reviewed runtime and weights"
```

A permitted SSH tunnel can also present an approved remote server as local
loopback, with SSH identity verification intact. Administrators must provide the
actual host, allocation, permitted forwarding path, and authentication rules;
Quarry does not create tunnels or invent cluster addresses. Loopback protects
against direct remote connections, but does not authenticate other users or
processes on a shared host. Use the allocation's approved process/network
isolation, or an authenticated gateway. Do not expose raw vLLM to a campus-wide
or public network; its own documentation explains why an API key alone does not
protect every server endpoint.
[vLLM security](https://docs.vllm.ai/en/stable/usage/security/).

For pattern 2, use the institutional backend with the verified HTTPS base URL
and `--credential-env YOUR_ASSIGNED_TOKEN_ENV`. Set documented per-token service
rates explicitly when present. A gateway requiring SSO, mTLS, or a nonstandard
auth protocol needs an administrator-provided compatible gateway or an adapter
extension; Quarry's existing client sends a bearer credential on its OpenAI
transport and does not bypass institutional authentication.

Your sponsor/administrator must resolve the following site-specific details:
account and allocation access, permitted research workload/data, scheduler
partition/QOS/GPU/memory/time request, software/container availability, outbound
network access, model download/licensing policy, checkpoint storage, endpoint
access, data retention, and resource accounting. These cannot be inferred from
being a Georgia Tech PhD student. No GPU type, module name, job duration, billing
account, or cluster hostname is prescribed by this guide.

Stop collection before the allocation expires when possible; retain the study
on approved durable storage and use Quarry's consistent backup command. After an
interruption, obtain a new authorized allocation, restart the same reviewed
server, and resume the unchanged approved study. Keep one active writer per
study. Do not copy a live SQLite file without its WAL; use the supported backup
workflow. See [long runs and backup](LONG_RUNS.md).

## Costs and the publication record

Use `compute`/`inspect_compute` to verify the effective configuration before the
plan review. The API route records token rates and model versions; local and
institutional default zero rates mean **no assumed per-token service fee**, not
free computing. Quarry cannot derive GPU-hour charges or an allocation balance
from token usage. Report those separately using the scheduler/provider's records,
and retain the account's own limits. Calls, concurrency, timeouts, recovery,
source/window limits, and deadlines remain finite even when token fees are zero.

For a paper, retain the reviewed nonsecret compute configuration, source and
prompt hashes, exact model/artifact versions, extraction provenance, failures,
coverage, and independently annotated held-out sources. Preserve the observed
contexts and distinguish generated suggestions from human annotations. Changing
hardware or models is an experimental change; do not call a cached or repeated
source collection a new independent sample. A frozen dataset version re-exports
the same stored records without contacting any model.

Read [publication protocol](PUBLICATION_PROTOCOL.md) and
[source-level evaluation](EVALUATION.md) for the complete procedure. This build
implements configuration and offline transport verification. It does not certify
a live provider's compatibility, deploy a Georgia Tech service, establish lab
access, or measure the research quality of a local model. Those checks belong to
an explicitly authorized, bounded pilot.
