# Customizing a research recipe

The default browser workflow turns a plain-language brief into a request for your
own AI agent, then validates the returned plan. See
[the agent workflow](browser-agent-workflow.md). This page documents advanced manual
customization; ordinary setup does not require editing JSON yourself.

Use a packaged starter as a base and save the resulting JSON in your project.
The engine validates version 1 recipes before queuing work. Unknown keys and
invalid types fail early. Change the recipe `version` whenever policy changes;
policy-affecting recipe fields enter the cache contract, and the complete recipe
and its content hash are recorded for each run.

```python
import json
from pathlib import Path
from termfinder.config import starter_recipe, load_recipe

recipe = starter_recipe("cultural")
recipe["id"] = "local-cultural-study"
recipe["version"] = "1.0.0"
recipe["research_question"] = "Which celebration names occur in our consented sources?"
recipe["communities"] = ["consented-community"]
recipe["languages"] = ["zh", "ja", "en"]
recipe["source_scope"]["domains"] = ["your-authorized-domain.example"]
recipe["dates"] = {"start": "2025-01-01", "end": "2026-12-31", "unknown": "include"}
recipe["mode"] = "specialists"
for lens in recipe["specialist_lenses"]:
    lens["communities"] = ["consented-community"]
load_recipe(recipe)
Path("recipe.json").write_text(json.dumps(recipe, ensure_ascii=False, indent=2), encoding="utf-8")
```

The three starters serve different policies:

| Starter | Includes | Excludes by default |
| --- | --- | --- |
| `neologisms` | New forms and shifted community senses | Entities used only as names; ordinary vocabulary |
| `cultural` | Established cultural vocabulary and contextualized entities | Generic words with no contextual cultural association |
| `jargon` | Established and emerging scientific/medical terms | General vocabulary; bibliography names used only as metadata |

Every starter supplies positive, negative, and boundary examples. These are
prompt demonstrations, not a spelling whitelist or a labeled quality benchmark.
Replace them with examples appropriate to your domain and retain boundary cases
that would otherwise confuse the research definition.

## Scope and metadata

`languages` and `communities` are literal metadata policy values. Community is
researcher-supplied source metadata, not inferred demographic identity. Domain
allowlists constrain URL retrieval and redirects; `source_scope.local` controls
local file ingestion. Dates use available publication dates. Unknown publication
dates follow `dates.unknown`; retrieval time is not publication time.

For a new project, start discovery disabled. Enable it only after setting finite
`max_sources`, `max_hops`, `max_requests`, costs, domains, and explicit queries.
Static search manifests work offline. A live connector's billed request rates
must be configured separately; a zero rate is an explicit assumption rather than
a guarantee that a third-party service is free. Source links and search results
can suggest URLs within this fixed policy. Extractor replies cannot invoke tools,
change recipes, or expand that policy.

## Fields, senses, and provenance

`data_type` is `term` by default for existing recipes, or `idea`, `opinion`, or
`sentence`. For nonlexical types, `expression` must quote an exact contiguous
source passage; `sense` is only a generated interpretation. Adapt few-shots and
specialist lenses to this unit. Agent setup supplies synthetic unit examples as
a starting point, not a substantive annotation rubric. Freeze the rubric and
independent full-source labels before reporting detection quality. Exact grounding
does not establish sentence completeness, correct semantic type, speaker identity,
or factual truth.

`output.required_fields` selects supported core fields. A required field key does
not require inventing its value: absent meaning is `null` with an unavailable
reason. `output.attributes` defines permitted project-specific fields and their
types. Required attributes that the model omits remain visibly unresolved instead
of causing a grounded term to disappear. A model-proposed sense or translation
remains generated text even when the expression is grounded. A quoted definition
becomes source evidence only after exact grounding; that check still does not
prove the interpretation is correct.

`output.translations` enables an optional suggestion field in extraction replies.
It does not add a separate translation provider call. If a project needs reviewed
translations, annotate them explicitly and retain the originals.

Normalization preserves original spelling and uses Unicode-aware conservative
identity. Literal proposed senses remain separate. Human alias and semantic-merge
relations are reversible links; they do not destructively delete evidence.

## Models, mode, and limits

`model_profile` is a named packaged profile or a separately loaded profile. Broad
runs the profile's general extractors. Specialists adds the lenses whose community
routes match a source; the broad passes still run. The lens `model` refers to a
profile model alias, so a researcher can change providers without rewriting engine
code. A Gemini profile remains a separate explicit choice. To use Specialists
with a custom/Gemini profile, define lenses referencing model aliases in that
profile; do not keep `glm` or `deepseek` routes if those aliases do not exist.

`execution` bounds money, calls, concurrency, retries, timeout, deadline, passage
size, overlap, recovery depth, and response size. These limits constrain work;
they do not impose a number of terms per source. Budget or recovery exhaustion
leaves jobs pending/partial, and the manifest records the resulting coverage.
Raising limits is a researcher decision for a separately authorized collection.

`exports` selects CSV, JSONL, Parquet, and the annotation-friendly bundle. Keep the
full grounded inventory even if a reviewer-approved subset is useful downstream.
Check source-use constraints before sharing any exported original contexts.
