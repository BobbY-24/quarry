# Quarry — workflow and components

Quarry is the product name for the V6.4 collector at
[`BobbY-24/quarry`](https://github.com/BobbY-24/quarry). These diagrams describe
the implemented architecture. The existing `termfinder` commands, Python API and
`v6-collect-research` skill identifier remain compatible.

## 1. Researcher workflow

```mermaid
---
config:
  theme: base
  themeVariables:
    primaryColor: "#f6ede4"
    primaryTextColor: "#3a2c24"
    textColor: "#3a2c24"
    lineColor: "#95745e"
    edgeLabelBackground: "#fffcf7"
    clusterBkg: "#fff7ef"
    clusterBorder: "#d6bfae"
---
flowchart TD
    Q["Researcher describes the study<br/>Data type, question, corpus and limits"] --> A["Own coding agent drafts the inputs<br/>Recipe, examples, sources and fields"]
    A --> P["Quarry validates the proposed plan<br/>Schema, source scope and finite budget"]
    P --> S["Capture permitted sources<br/>Parse, hash and freeze evidence"]
    S --> R["Researcher reviews the complete plan<br/>Sources, failures, mode and cost estimate"]
    R -->|"Approve the concrete plan"| C["Collect with Broad or Specialists<br/>Configured models propose discoveries"]
    C --> G["Quarry checks exact source spans<br/>Keep the grounded union and distinct senses"]
    G --> I["Inspect the complete inventory<br/>Optional reversible human annotations"]
    I --> E["Save a dataset version and export<br/>CSV, JSONL, Parquet and annotation files"]
    C -->|"Interrupted, capped or unresolved"| J["Saved progress and unfinished work<br/>Pending, partial, failed or uncertain"]
    J -->|"Resume eligible work<br/>Under saved recovery policy"| C
    classDef default fill:#f6ede4,stroke:#d6bfae,color:#3a2c24,stroke-width:1.5px;
    classDef human fill:#fff0cf,stroke:#cda463,color:#3a2c24;
    classDef collector fill:#f8e6d8,stroke:#c98966,color:#3a2c24;
    class Q,R,I human;
    class P,C,G collector;
    linkStyle default stroke:#95745e,color:#705444,stroke-width:1.5px;
```

The connection starts with a synthetic fake-provider gate. Real collection needs
an explicitly authorized provider connection and the reviewed finite plan.
Preparing inputs or viewing a plan does not dispatch extraction. Human relays
are recorded declarations, not authenticated signatures.
Exhausted budgets, disabled models and uncertain outcomes can require an explicit
resolution or a newly reviewed plan. Unknown reservations persist; retries of
uncertain requests may incur duplicate charges.

## 2. Components and responsibilities

```mermaid
---
config:
  theme: base
  themeVariables:
    primaryColor: "#f6ede4"
    primaryTextColor: "#3a2c24"
    textColor: "#3a2c24"
    lineColor: "#95745e"
    edgeLabelBackground: "#fffcf7"
    clusterBkg: "#fff7ef"
    clusterBorder: "#d6bfae"
---
flowchart TD
    subgraph U["Researcher interfaces"]
        A["Own coding agent<br/>Project skill + local MCP"]
        B["Optional interfaces<br/>CLI, notebook API and local browser"]
    end
    subgraph K["Quarry collector"]
        P["Shared Project and workflow API<br/>Prepare, review, approve, inspect and release"]
        V["Versioned recipes and profiles<br/>Schema, scope and approval checks"]
        S["Scoped source ingestion<br/>HTML, text and PDF; advanced bounded discovery"]
        J["Persistent execution engine<br/>Jobs, cache, budgets, retries and cancellation"]
        G["Deterministic evidence checks<br/>Exact spans, conservative deduplication and audit"]
        D[("SQLite project state<br/>Sources, inventory, jobs, costs and review history")]
        X["Frozen dataset versions and exports<br/>Manifests, schemas, coverage and file hashes"]
    end
    F["Permitted local documents<br/>and scoped source URLs"]
    M["Configured model providers<br/>GLM + DeepSeek; separate Gemini profile"]
    A --> P
    B --> P
    P --> V
    P --> S
    F --> S
    V --> J
    S --> D
    D --> J
    J -->|"Bounded extraction requests"| M
    M -->|"Inert candidate proposals"| G
    G --> D
    J --> D
    P --> X
    D --> X
    classDef default fill:#f6ede4,stroke:#d6bfae,color:#3a2c24,stroke-width:1.5px;
    classDef human fill:#fff0cf,stroke:#cda463,color:#3a2c24;
    classDef collector fill:#f8e6d8,stroke:#c98966,color:#3a2c24;
    class A,B human;
    class P,V,J,G collector;
    style U fill:#fffcf7,stroke:#d6bfae,color:#3a2c24;
    style K fill:#fff7ef,stroke:#d6bfae,color:#3a2c24;
    linkStyle default stroke:#95745e,color:#705444,stroke-width:1.5px;
```

Agent planning and model generation remain nondeterministic. The collector
owns deterministic admission, evidence checks and stored-record export.
An extraction response cannot invoke tools or enlarge source scope. The model
profile, recipe and prompt versions are configuration inputs, not hardcoded
choices spread through the engine.
The guided agent workflow uses its reviewed finite source list and keeps
discovery disabled. Explicit bounded discovery is an advanced engine capability.

## 3. Evidence and reproducibility

```mermaid
---
config:
  theme: base
  themeVariables:
    primaryColor: "#f6ede4"
    primaryTextColor: "#3a2c24"
    textColor: "#3a2c24"
    lineColor: "#95745e"
    edgeLabelBackground: "#fffcf7"
    clusterBkg: "#fff7ef"
    clusterBorder: "#d6bfae"
---
flowchart TD
    T["Collected record<br/>Term or sense, idea, opinion or sentence"] --> O["Occurrence or evidence record<br/>Original spelling, exact context and source span"]
    O --> S["Frozen parsed source<br/>Unicode offsets, available PDF page and text hash"]
    S --> L["Source provenance<br/>Locator, retrieval date, available publication date and raw hash"]
    T --> M["Extraction provenance<br/>Run, job, window, prompt and model configuration"]
    T --> N["Generated interpretation<br/>Proposed meaning or translation, labeled separately"]
    T --> H["Optional human annotation<br/>Decision, note and reversible history"]
    T --> V["Immutable dataset version"]
    O --> V
    S --> V
    L --> V
    M --> V
    N --> V
    H --> V
    V --> E["Reproducible export<br/>Saved records, manifests, costs, failures and coverage"]
    E -->|"Same saved version; no model calls"| E2["Same exported dataset records"]
    classDef default fill:#f6ede4,stroke:#d6bfae,color:#3a2c24,stroke-width:1.5px;
    classDef human fill:#fff0cf,stroke:#cda463,color:#3a2c24;
    classDef collector fill:#f8e6d8,stroke:#c98966,color:#3a2c24;
    class H human;
    class V,E,E2 collector;
    linkStyle default stroke:#95745e,color:#705444,stroke-width:1.5px;
```

Offsets refer to frozen parsed text, not byte positions in the original PDF or
HTML. Original bytes need a separate lawful archive for parser replay.
Unavailable metadata uses null with a reason. Grounding proves occurrence,
not correctness of a proposed meaning, truth, novelty or recall.

## 4. Source-level evaluation

```mermaid
---
config:
  theme: base
  themeVariables:
    primaryColor: "#f6ede4"
    primaryTextColor: "#3a2c24"
    textColor: "#3a2c24"
    lineColor: "#95745e"
    edgeLabelBackground: "#fffcf7"
    clusterBkg: "#fff7ef"
    clusterBorder: "#d6bfae"
---
flowchart LR
    S["Held-out complete sources<br/>Group related sources in the same split"] --> H["Independent human annotation<br/>Label every eligible occurrence"]
    S --> Q["Quarry extraction<br/>Frozen policy and model profile"]
    H --> C["Compare exact evidence and labels"]
    Q --> C
    C --> P["Precision<br/>Which extracted spans match the human gold rubric?"]
    C --> R["Recall and false negatives<br/>Which eligible records were missed?"]
    P --> D["Report by domain and language"]
    R --> D
    classDef default fill:#f6ede4,stroke:#d6bfae,color:#3a2c24,stroke-width:1.5px;
    classDef human fill:#fff0cf,stroke:#cda463,color:#3a2c24;
    classDef collector fill:#f8e6d8,stroke:#c98966,color:#3a2c24;
    class H human;
    class Q,C collector;
    linkStyle default stroke:#95745e,color:#705444,stroke-width:1.5px;
```

Reviewing extracted candidates alone cannot measure missed records. Candidate
counts and model agreement are not recall measurements.
Default metrics compare exact spans and language. Interpretation or sense matching
is optional and does not establish factual correctness.
