# Sources and bounded discovery

Local documents and URLs use the same frozen source representation. The raw file
hash and parsed-text hash are separate. Offsets refer to parsed Unicode text;
locations identify heading/block/page when available. Original files are not
byte-offset addressable through the occurrence schema.

PDF parsing uses a shipped reviewed worker with isolated Python startup and a
minimal environment. It bounds CPU (20 seconds), open files (32), output files
(90 MB), parent wall time (30 seconds), pages (2,000), and extracted text
(20 million code points). Linux uses a hard 1 GiB address-space limit; macOS
samples the worker's own resident memory every 0.05 seconds and exits above
1 GiB, so brief overshoot is possible. `parser_info.memory_limit_kind` records
the actual mechanism. Its stderr is discarded and parser logging suppressed
to keep source bytes out of logs. These are resource bounds, not an operating
system filesystem/network sandbox. Use the macOS Seatbelt or Linux container
workflow in `docs/VERIFICATION.md` for untrusted/high-risk PDFs. Scanned PDFs are
marked as needing OCR; no external OCR service is invoked.

```sh
termfinder --project my-study ingest paper.pdf notes.md page.html \
  --metadata source-metadata.json
termfinder --project my-study ingest --url-list urls.txt \
  --metadata source-metadata.json
```

`urls.txt` has one HTTP(S) URL per line; blanks and `#` comment lines are ignored.
Fetching occurs when explicitly invoking URL ingestion. The recipe domain scope
must permit every URL and redirect. The fetcher restricts dangerous schemes,
private/loopback addresses, credential-bearing URLs, redirects, time, and bytes,
keeps TLS verification enabled, and does not execute scripts. A source's content
cannot turn off these limits.

Source metadata can include `language`, `community`, `domain`,
`publication_date`, and `constraints`. A source parser may recover publication
metadata from HTML, but unknown dates remain null with a reason. Choose
`dates.unknown: include` or `exclude` deliberately. Supply community metadata
that matches the recipe's literal routes to enable specialist passes.

## Implemented discovery connectors

* `StaticSearchAdapter` / `StaticManifestSearch` reads explicit JSON search results
  from a local manifest. Each result is exactly one `path` or `url` plus optional
  `title` and `metadata`. Paths resolve relative to the manifest directory, and
  must stay inside its directory unless a researcher explicitly supplies a local
  root. Symlinks cannot expand that root, and credential paths are rejected.
* `HTTPJSONSearch` uses an explicitly configured public HTTPS GET endpoint returning
  `{"results": [{"url": "https://...", "title": "..."}]}`. It supports query and
  limit parameters. Authentication is deliberately unsupported; secret-bearing
  commercial APIs need a reviewed connector.
* `SafeFetcher` retrieves in-scope HTTP(S) sources with bounded bytes, timeout,
  safe addresses, TLS checks, and redirect limits.

Search endpoint scope and source scope are separate. Neither a search result
nor a document link can widen the source allowlist. No extraction proposal is
passed to the discovery coordinator.

The recipe sets explicit queries, source count, hop count, request count, and
discovery prices. Decisions record searches, queued/rejected URLs, duplicates,
retrieval, parse/date failures, lineage, and stop reasons. Pending work remains
visible when a finite limit is reached. `discover --resume` resumes the saved
campaign while preserving cumulative scope/request/source/spending limits.
Request prices are researcher-configured
assumptions; all third-party bills must be checked against actual invoices.

## Working offline discovery example

Create a separately versioned recipe with discovery enabled and no link hops:

```python
import json
from pathlib import Path
from quarry.config import starter_recipe, load_recipe

recipe = starter_recipe("neologisms")
recipe["version"] = "1.0.1"
recipe["discovery"]["enabled"] = True
recipe["discovery"]["max_hops"] = 0
recipe["discovery"]["max_sources"] = 3
recipe["discovery"]["max_requests"] = 3
load_recipe(recipe)
Path("discovery-recipe.json").write_text(json.dumps(recipe, indent=2), encoding="utf-8")
```

```sh
quarry init offline-discovery --recipe discovery-recipe.json --profile fake
termfinder --project offline-discovery discover --manifest examples/discovery.json --local-root .
termfinder --project offline-discovery status
termfinder --project offline-discovery collect --offline
```

The manifest contains a local HTML source, a deliberately malformed PDF, and an
out-of-scope result. Zero hops rejects HTML follow-up links without retrieving
them. The source limit and parse failure remain inspectable. The complete offline
acceptance demo also checks finite discovery behavior using a fake fetch adapter.

## Extensions

Authenticated repositories/social platforms, proprietary search SDKs, JavaScript
rendering, robots/publisher policy integration, and OCR services are not included.
Provide local exports under the appropriate source-use permissions or implement
a reviewed adapter with the same fixed scope, budgets, lineage, and failure
semantics. Table text and recognizable conversation turns are preserved when
available; full structured table records and conversation dataset construction
remain later releases.
