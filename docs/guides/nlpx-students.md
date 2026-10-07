# NLPx student walkthroughs for Quarry

These are **proposed uses of Quarry informed by public research**, not claims that students or PIs requested the tool, adopted it, or assigned these projects. The public [Wei Xu roster](https://cocoxu.github.io/#students) and [Alan Ritter roster](https://aritter.github.io/index.html), checked on October 5, 2026, list 11 unique current PhD students. Wei Xu's page lists Chao Jiang and Yao Dou as alumni; their work appears below as additional lab precedents. Public listings can lag changes.

**Install and connect Quarry once in your own coding-agent workspace, using the [simple workflow](student-workflow.md) and [packaged skill/MCP tools](agent-setup.md).** Tell the agent your question and permitted sources; it creates the study, presents the complete source and cost review, collects after your decision, shows evidence, and exports in the same conversation. You do not need to write or transport JSON or open a browser. The browser is an optional visual view; a chat without local tools retains the file handoff. Read the [publication protocol](../research/publication-protocol.md) before collecting so the source sample, blind annotation, provenance, and evaluation can withstand review. The [shared procedure](../research/collection-protocol.md) retains detailed installation, CLI, API, and manual-policy references.

Quarry retains its `termfinder` commands, Python namespace
and `v6-collect-research` skill identifier. Existing recipes and study records
keep their original version and provenance identifiers.

The same procedure applies to every student below: **ask your agent → approve the concrete Plan → inspect Evidence → save Dataset.** Preparation automatically validates inputs, captures the approved sources, freezes blank whole-source annotation packets, and estimates costs before collection. Each student still owns the corpus, hypotheses, sampling choices, and human annotation rubric. The personal agent drafts inputs; it does not approve research claims or invent authorization.

## Start in ordinary language

These are proposed starting requests adapted from the verified research questions and sources cited in the profiles below. Tell your agent the actual permitted documents, languages, dates, source limits, and finite budget. A profile's recipe and metadata files are optional **references for your agent**; it adapts and submits the structured inputs through Quarry. Keeping most of these studies as **Term** preserves their original vocabulary questions. Choosing another unit requires an explicit new inclusion rubric rather than relabeling a term dataset.

| Student | Proposed choice | Starting request to their own agent |
| --- | --- | --- |
| [Jonathan Zheng](#1-jonathan-zheng) | **Term** | “Help me find new expressions and changed senses in my dated English community documents. Exclude names used only as names, retain one-off uses, and keep the original context for each sense.” |
| [Tarek Naous](#2-tarek-naous) | **Term** | “Collect culturally situated entities and expressions from my permitted unmasked multilingual passages. Include established names and preserve original scripts; leave cultural association unknown unless the context supports it.” |
| [Geyang Guo](#3-geyang-guo) | **Opinion**, or **Term** for the original vocabulary study | “Collect passages that explicitly express assessments or preferences about the cultural practices I specify. Preserve attribution, qualifiers, original language, and human or generated source origin; do not infer the speaker's identity or turn passages into preference rankings.” For vocabulary coverage instead: “Collect culture-specific expressions and contextual senses in my Chinese, Arabic, Japanese, and comparison English explanations.” |
| [Duong Minh Le](#4-duong-minh-le) | **Term** | “Find entities and domain expressions on both sides of my parallel-document corpus. Ground every expression in its own language version and flag span or sense differences for bilingual review.” |
| [Jiayi (Ivy) He](#5-jiayi-ivy-he) | **Term** | “Find technical expressions, units, and ambiguous senses in my paired English and Chinese reasoning prompts. Preserve problem-family identities and leave cross-language equivalence to bilingual review.” |
| [Junmo Kang](#6-junmo-kang) | **Term** | “Build an evidence-backed vocabulary of dataset names, metrics, assay properties, and methods from my selected papers. Keep established terms, source-supported expansions, and units for later human schema design.” |
| [Jungsoo Park](#7-jungsoo-park) | **Term** | “Track prompting and evaluation terminology across my dated LLM paper corpus. Preserve different operational meanings and paper versions so I can compare frozen vocabulary releases.” |
| [Hyungjoo Chae](#8-hyungjoo-chae) | **Term** | “Find interface labels and domain expressions in my permitted website text exports. Preserve action and state contexts and flag labels with different meanings across environments.” |
| [Ruohao Guo](#9-ruohao-guo) | **Term** | “Collect lexical cues and contextual senses from my selected questions and style examples. Preserve benign and potentially misleading contexts separately; do not decide factual truth from a phrase's occurrence.” |
| [Ethan Mendes](#10-ethan-mendes) | **Term** | “Find technical concepts in my permitted expert solutions and separately identified generated traces. Keep exact source passages and problem families; do not treat a mentioned concept as proof of valid reasoning.” |
| [Nghia (Max) Le](#11-nghia-max-le) | **Term** | “Collect materials, operations, and technical noun phrases from my chemical protocols. Keep step and page context, and flag unresolved references for separate human anaphora annotation.” |

For **Sentence** and **Idea** starting requests, the [agent workflow](browser-agent-workflow.md#five-realistic-starting-conversations) also provides medical-readability and legal-coverage examples grounded in the lab precedents discussed at the end of this guide. Those choices collect exact sentence or passage spans; readability judgments and semantic coverage remain separate research tasks.

## Advanced research references

The profiles, recipes, and metadata below preserve the detailed vocabulary studies. They explain decisions your agent should encode and your research team should review; they are not a requirement to maintain JSON manually. All 11 profiles use the shared simple agent workflow above.

All example JSONs are versioned and editable, with local-first source scope, disabled discovery, and zero total/stage spending. The reserved `local-only.invalid` host restricts accidental URL ingestion. Before a live study, deliberately select permitted domains, available publication dates, exact community routes, reviewed provider profile and finite budgets. Zero-dollar examples can configure, ingest local files and estimate; they do not enable paid extraction.

**Every few-shot sentence shipped with these examples is a synthetic illustration.** Some expressions are discussed in the cited papers, but the surrounding guide sentences are not paper quotations, original posts or research observations. Real evidence must come from the declared sources. `FakeProvider` is a shipped-fixture demonstration, not a general extractor for these custom recipe IDs.

### Research anchors and original vocabulary recipes

| Student | Existing research anchor | Quarry collection output | Recipe |
| --- | --- | --- | --- |
| Jonathan Zheng | [Published research](https://arxiv.org/html/2402.12261v4) | A dated, evidence-backed inventory of expression/sense candidates for later definition, robustness or translation experiments. | [jonathan-zheng.json](../../examples/lab_recipes/jonathan-zheng.json) |
| Tarek Naous | [Published research](https://arxiv.org/abs/2510.05291) | A native-reviewed entity/term inventory with original-script context, proposed translations and explicit cultural association decisions. | [tarek-naous.json](../../examples/lab_recipes/tarek-naous.json) |
| Geyang Guo | [Published research](https://arxiv.org/abs/2504.05154) | A cultural-vocabulary coverage audit that can be joined to independently maintained question IDs and preference data. | [geyang-guo.json](../../examples/lab_recipes/geyang-guo.json) |
| Duong Minh Le | [Published research](https://arxiv.org/abs/2402.03131) | A bilingual span inventory for diagnostics before an external label-projection or decoding experiment. | [duong-minh-le.json](../../examples/lab_recipes/duong-minh-le.json) |
| Jiayi (Ivy) He | [Published research](https://arxiv.org/abs/2606.26466) | A lexical diagnostic dataset for stratifying reasoning prompts by ambiguity, technical concepts and units. | [jiayi-ivy-he.json](../../examples/lab_recipes/jiayi-ivy-he.json) |
| Junmo Kang | [Published research](https://arxiv.org/html/2305.14336v5) | A domain vocabulary and alias inventory supporting human-authored extraction schemas or external specialization datasets. | [junmo-kang.json](../../examples/lab_recipes/junmo-kang.json) |
| Jungsoo Park | [Published research](https://arxiv.org/html/2502.18791v3) | Dated terminology versions for method naming, experimental-setting definitions and literature navigation. | [jungsoo-park.json](../../examples/lab_recipes/jungsoo-park.json) |
| Hyungjoo Chae | [Published research](https://arxiv.org/abs/2603.10505) | An interface-language inventory for task-authoring review and ambiguity analysis in controlled environments. | [hyungjoo-chae.json](../../examples/lab_recipes/hyungjoo-chae.json) |
| Ruohao Guo | [Published research](https://arxiv.org/abs/2503.09598) | A contextual lexical-cue inventory for a separately adjudicated factuality or style study. | [ruohao-guo.json](../../examples/lab_recipes/ruohao-guo.json) |
| Ethan Mendes | [Published research](https://arxiv.org/abs/2602.02405) | A technical-concept inventory for comparing vocabulary in expert/community solutions and separately labeled generated traces. | [ethan-mendes.json](../../examples/lab_recipes/ethan-mendes.json) |
| Nghia (Max) Le | [Published research](https://arxiv.org/html/2210.03690v2) | A protocol vocabulary inventory with exact step/page contexts for external reference-resolution analysis. | [nghia-max-le.json](../../examples/lab_recipes/nghia-max-le.json) |

### Advanced manual preparation reference

Researchers who prefer to maintain configuration files directly can use the following alternative. Ordinary onboarding uses the connected coding-agent conversation; the agent manages the bundle and the browser is optional. This example prepares Tarek's study and ingests **a researcher-supplied file**; it does not fetch a dataset or call a model:

```sh
cp examples/lab_recipes/tarek-naous.json tarek-recipe.json
cp examples/lab_recipes/tarek-naous.metadata.json tarek-metadata.json
# Edit the copies to match the corpus and permissions you actually have.
termfinder init studies/tarek-naous --recipe tarek-recipe.json --profile glm-deepseek --mode broad
termfinder --project studies/tarek-naous ingest corpus/urdu-source-001.md --metadata tarek-metadata.json
termfinder --project studies/tarek-naous estimate
termfinder --project studies/tarek-naous snapshot corpus-v1
```

Substitute a student slug below. The corpus file path is a user-supplied input, not a file downloaded by this build. One metadata object applies to one homogeneous batch. Preserve external record IDs and content origin under retained `constraints` or a separate source map. Arbitrary top-level metadata keys are not automatically retained. Review candidate meanings separately from whether their exact expression occurs. A manual snapshot does not establish blind review by itself; for the ordinary approved-agent-plan path, use **Prepare blind source review** before any extraction jobs are prepared, as described in the publication protocol.

## 1. Jonathan Zheng

NEO-BENCH studies English neologisms and temporal language drift; Jonathan Zheng is an author with Alan Ritter and Wei Xu. [Primary source](https://arxiv.org/html/2402.12261v4)

**Suggested research question:** Which new expressions and shifted senses occur in a specified English community corpus during the declared collection period?

**Advanced references for your agent:** [recipe](../../examples/lab_recipes/jonathan-zheng.json) and [metadata](../../examples/lab_recipes/jonathan-zheng.metadata.json). Starter policy: `neologisms`. Community routing label: `ev-community-vocabulary`. Proposed fields: `innovation_type`, `novelty_evidence_note`.

1. Specify one collection question, for example whether electric-vehicle discussions use familiar spellings with new senses. Choose the community sample and publication-date interval before looking at candidates. The template includes lexical, morphological and semantic candidates and excludes entity-only names.

2. Prepare permitted full discussion threads and explanatory articles as HTML, Markdown or text. Ingest distinct communities/dates in separate batches using ev-community-vocabulary or your replacement label in the recipe, metadata and lenses. Keep an external thread-family map. An observed article quoting an older post does not establish the post's original date.

3. Use ice in its charging-space sense as a positive policy illustration, frozen water as a negative, and doomscrolling as a chronology boundary. The few-shot sentences in the JSON are synthetic. Real claims require exact occurrences in the newly selected sources and separate historical evidence.

4. Freeze the source corpus and blind held-out packets, then start Broad after the cost/budget review. Inspect terms that only GLM or only DeepSeek found. If source-level labels reveal omissions in compounds or familiar-form shifts on the development split, revise attention lenses/version and add Specialists under a reviewed budget.

5. For each candidate, separately annotate whether the expression occurs, whether the proposed sense fits, and whether there is independent evidence of novelty. Preserve distinct senses of ice. Rejection stays in the full inventory. Store novelty notes as human attributes; first_observed_in_corpus and retrieval dates are not coinage dates.

6. Evaluate complete held-out threads by occurrence and source-term unit, inspect false negatives, and freeze the full inventory plus the approved subset. Export source evidence for later task construction. Cloze questions, substitution sentences, translation tests and Google Trends checks remain separate research work.

**Deliverable:** A dated, evidence-backed inventory of expression/sense candidates for later definition, robustness or translation experiments.

## 2. Tarek Naous

Camellia, with Tarek Naous as first author, examines entity-centric cultural biases across Asian languages. [Primary source](https://arxiv.org/abs/2510.05291)

**Suggested research question:** Which culturally situated entities appear in unmasked multilingual source passages, and what contextual evidence supports their local association?

**Advanced references for your agent:** [recipe](../../examples/lab_recipes/tarek-naous.json) and [metadata](../../examples/lab_recipes/tarek-naous.metadata.json). Starter policy: `cultural`. Community routing label: `camellia-cultural-entities`. Proposed fields: `entity_category`, `cultural_association`, `transliteration`.

1. Start with one language/topic scope, such as Urdu food descriptions, before expanding to the paper's nine-language setting. The recipe includes established entities: food, beverages, authors, names, locations and sports clubs. Keep named entities eligible even though a neologism policy excludes entity-only names.

2. Choose permitted unmasked natural passages. Ingest Urdu and English comparison sources separately, with appropriate language, community, domain and rights metadata. Replace the template's project label if using narrower source communities and update every specialist route. JSON datasets require a reviewed conversion preserving original contexts and record IDs in constraints.

3. Use a dish such as Nihari as an illustration of an entity that requires contextual association. A person name such as 지우 is a boundary case: the name may qualify, while its cultural association remains null without evidence. These are recipe examples, not new research observations.

4. Freeze held-out original sources before candidate review. Run Broad across the fixed corpus, then optional entity/spelling and cultural-sense specialist lenses. Examine missed original-script spans and multiword dishes; do not replace originals with Latin transliterations or English text.

5. Have qualified native reviewers judge entity category, source-supported association and contextual meaning. Record reviewer notes and validated transliterations/translation corrections as human attributes. Link spelling/transliteration variants with reversible aliases only after inspecting both pieces of evidence.

6. Evaluate complete held-out sources by language/domain. Quarry reports those breakdowns directly; category-specific analysis requires external grouping of human category labels. Export the full inventory and approved subset for subsequent cultural tasks. A masked-out entity cannot be grounded; masking and benchmark generation happen after original evidence collection.

**Deliverable:** A native-reviewed entity/term inventory with original-script context, proposed translations and explicit cultural association decisions.

## 3. Geyang Guo

CARE, led by Geyang Guo with Tarek Naous and collaborators, studies multilingual native human preferences for culturally situated questions and responses. [Primary source](https://arxiv.org/abs/2504.05154)

The original **Term** case below remains valid for cultural-vocabulary coverage. The newer **Opinion** path in the [agent workflow](browser-agent-workflow.md#geyang-expressed-cultural-opinions) is an alternative for collecting explicitly expressed assessments or preferences as exact passages. It needs its own inclusion and attribution rubric and independent human judgments. These are different collection units, not two labels for the same dataset; neither path constructs native preference rankings, response pairs, or DPO training data.

**Suggested research question:** Which culture-specific expressions appear in human-authored Chinese, Arabic, Japanese and comparison English explanatory sources, and where are vocabulary coverage gaps?

**Advanced references for the Term study:** [recipe](../../examples/lab_recipes/geyang-guo.json) and [metadata](../../examples/lab_recipes/geyang-guo.metadata.json). Starter policy: `cultural`. Community routing label: `care-cultural-questions`. Proposed fields: `cultural_category`, `associated_culture`, `geographic_scope`.

1. Define a narrower question about expressions in cultural explanations or social norms, for instance where Chinese, Arabic or Japanese sources provide concepts missing from English explanations. Retain culture-specific and established vocabulary; do not impose a novelty requirement.

2. Separate human-authored source questions, explanatory material and model-generated responses. The template is intended for a human-authored corpus. If analyzing generated responses, create a separately labeled project/corpus and set constraints.content_origin explicitly; text observed in an input file is not automatically a human community observation.

3. Use 老外/laowai as a context-sensitive illustration. The recipe requests suggested cultural_category, associated_culture and geographic_scope. Positive and boundary examples should show that one term can have different conversational readings; they must not encode a universal negative sentiment or identity inference.

4. Ingest native-language and English comparison material in metadata-homogeneous batches, preserving original question/document IDs in constraints or an external source map. Keep related questions and translations together in source-family splits. Freeze blind complete-source packets before extraction.

5. Run Broad, then optional lenses focused on norms and regional senses after reviewing costs. Native reviewers inspect exact contexts, proposed meanings and unavailable fields. Human category/association judgments remain distinct from model suggestions; preferences are collected in the separate CARE-style annotation process.

6. Measure held-out term recall and false negatives by language and domain, then export a frozen vocabulary inventory for an external join with existing preference data. Quarry does not construct question-response pairs, native preference rankings, DPO datasets or multilingual policy training.

**Deliverable:** A cultural-vocabulary coverage audit that can be joined to independently maintained question IDs and preference data.

## 4. Duong Minh Le

Constrained Decoding for Cross-lingual Label Projection studies span-label transfer across translated text. [Primary source](https://arxiv.org/abs/2402.03131)

**Suggested research question:** Which entities and domain expressions occur in each side of a declared parallel-document corpus, and what span or sense differences need bilingual review?

**Advanced references for your agent:** [recipe](../../examples/lab_recipes/duong-minh-le.json) and [metadata](../../examples/lab_recipes/duong-minh-le.metadata.json). Starter policy: `cultural`. Community routing label: `parallel-document-terminology`. Proposed fields: `label_family`, `domain_category`, `alignment_note`.

1. Declare the actual downstream label inventory first: entities, event-related expressions, domain phrases, or a selected combination. The supplied en/es choice is an illustrative pilot scope to edit, not a claim about the paper's complete language coverage. This recipe adapts the cultural starter but does not require cultural association.

2. Ingest each original and translated document as its own source. Set language accurately, retain the original record ID and translation origin in constraints, and keep an external parallel-document family map. Do not put paper_id into an unsupported top-level metadata field and assume it survives.

3. Replace the Banco Central positive example with appropriate entity/span cases from the development corpus. Keep an ambiguity case such as bank/banco. One document's mention does not ground its counterpart in another document; each expression needs its own source span.

4. Freeze entire parallel-document families into one split. Run Broad separately on both language versions, inspect boundaries and singleton discoveries, and add configured entity-boundary/morphology lenses only if useful on development sources.

5. Ask bilingual reviewers to adjudicate exact span boundaries, local meaning and intended label family. Store alignment judgments externally and use reversible alias relations only for validated lexical equivalence. An alias is not the projected label or a guarantee of token alignment.

6. Evaluate whole held-out documents for expression recall by language. Export Unicode spans, original spelling and contexts to the external constrained-decoding pipeline, which must separately assess label projection quality and translation quality.

**Deliverable:** A bilingual span inventory for diagnostics before an external label-projection or decoding experiment.

## 5. Jiayi (Ivy) He

Soft Token Alignment for Cross-Lingual Reasoning (SOLAR), by Jiayi He and collaborators, studies multilingual reasoning representations. [Primary source](https://arxiv.org/abs/2606.26466)

**Suggested research question:** Which technical or ambiguous expressions could affect interpretation of paired English and Chinese reasoning prompts?

**Advanced references for your agent:** [recipe](../../examples/lab_recipes/jiayi-ivy-he.json) and [metadata](../../examples/lab_recipes/jiayi-ivy-he.metadata.json). Starter policy: `jargon`. Community routing label: `multilingual-reasoning-prompts`. Proposed fields: `reasoning_domain`, `ambiguity_note`, `unit_or_quantity`.

1. Choose one domain and a paired-language pilot; the template's English/Chinese pair is illustrative. Target technical expressions, units and ambiguous senses that could change interpretation of equivalent prompts. Do not collect arbitrary reasoning fragments as terms.

2. Ingest each prompt language version separately, label translation/generated origins accurately, and retain an external problem-family identifier. Keep all translations, variants and solutions of a problem together when forming held-out splits.

3. Use mathematical mean versus its everyday sense as a boundary design. The positive few-shot is synthetic; real data needs exact source context. Request reasoning_domain, ambiguity_note and unit_or_quantity as suggestions, with null when unavailable.

4. Freeze blind sources, run Broad and inspect context-specific uses. Optional specialist lenses attend to units/technical expressions and ordinary forms with mathematical senses; their added candidates remain alongside broad discoveries.

5. Have bilingual/domain annotators decide whether meanings and quantities are equivalent across language versions. Inspect translations as proposals rather than evidence. Record lexical mismatches with source IDs/spans instead of claiming that a missing translation explains the model's answer.

6. Evaluate whole held-out problem families for term recall, then export lexical strata for a separate comparison of multilingual reasoning accuracy. Quarry does not compute soft-token representations, SOLAR losses, supervised fine-tuning or reasoning correctness.

**Deliverable:** A lexical diagnostic dataset for stratifying reasoning prompts by ambiguity, technical concepts and units.

## 6. Junmo Kang

Junmo Kang co-authored [schema-driven information extraction](https://arxiv.org/html/2305.14336v5) and [LLMEvalDB](https://arxiv.org/html/2502.18791v3), and studies [model specialization](https://aclanthology.org/2024.findings-acl.157/).

**Suggested research question:** Which dataset names, metrics, assay properties and methods occur in a declared paper corpus and should inform downstream extraction schemas or specialization data?

**Advanced references for your agent:** [recipe](../../examples/lab_recipes/junmo-kang.json) and [metadata](../../examples/lab_recipes/junmo-kang.metadata.json). Starter policy: `jargon`. Community routing label: `schema-domain-vocabulary`. Proposed fields: `term_category`, `source_expansion`, `unit`.

1. Select a domain corpus such as ML evaluation papers, chemistry assay papers, or a deliberately stratified set. Include established dataset names, metrics and properties; new-word-only criteria would discard needed vocabulary. Specify term_category, source_expansion and unit suggestions.

2. Ingest full permitted papers as text-bearing PDFs/HTML, preserving page and table-text blocks. Use distinct metadata batches for domains and document dates. Store paper IDs in constraints and join a source-ID family map for preprint/published versions.

3. Use IC₅₀, F₁ and related expressions as policy examples. Preserve exact subscripts and original forms; do not silently normalize them into other spellings. A term occurrence in table text supplies lexical evidence, not a complete experimental record.

4. Freeze whole-paper held-out packets and run Broad first. Add metric/dataset and assay/property lenses under Specialists if relevant. To compare modes scientifically, use two clean projects with identical source content, metadata, recipe and held-out rubric; Specialists mode is extraction routing rather than learned model specialization.

5. Review abbreviation expansions and unit/sense distinctions against actual context. Link aliases reversibly. Inspect high-value terms missed by either extractor on development sources, and retain grounded single-extractor discoveries.

6. Evaluate held-out entire papers, export the full and approved glossaries, then use them to design an external table schema or training corpus. Numeric table-row reconstruction, InstrucTE reproduction, Self-Specialization and expert-model training are outside Quarry.

**Deliverable:** A domain vocabulary and alias inventory supporting human-authored extraction schemas or external specialization datasets.

## 7. Jungsoo Park

LLMEvalDB, led by Jungsoo Park with Junmo Kang and collaborators, structures information from an evolving LLM literature corpus. [Primary source](https://arxiv.org/html/2502.18791v3)

**Suggested research question:** How does prompting and evaluation terminology change across a versioned inventory of LLM research papers?

**Advanced references for your agent:** [recipe](../../examples/lab_recipes/jungsoo-park.json) and [metadata](../../examples/lab_recipes/jungsoo-park.metadata.json). Starter policy: `jargon`. Community routing label: `llm-evaluation-literature`. Proposed fields: `term_category`, `operational_definition`, `abbreviation_expansion`.

1. Define which paper vocabulary matters: prompting strategies, benchmarks, model names, metrics and experimental settings. Explicitly include established terms. The research question concerns terminology, not score trend reconstruction.

2. Ingest a fixed first paper batch as HTML/PDF, recording available publication dates and external paper IDs. Keep versions of one paper in one family. For later batches, retain the same project inventory while preserving every frozen release.

3. Use Chain-of-Thought, in-context learning and zero-shot/few-shot as illustrations. Request an operational_definition tied to the local source and an abbreviation expansion only if present. Do not merge different operational senses because their expression spelling matches.

4. Freeze blind held-out paper families. Run Broad, inspect different meanings of zero-shot across papers, and add method/acronym and experimental-setting lenses after an estimate review. Do not use an extraction candidate count as literature coverage.

5. Review source quotations, method/category suggestions and aliases. Resolve source-supported expansions manually. Reversible links can connect CoT with Chain-of-Thought while retaining both original spellings and model provenance.

6. Evaluate complete held-out papers and export a dated vocabulary version. Later ingest newly permitted papers, resume remaining work, and freeze v2. Join terminology externally to LLMEvalDB records; Quarry does not reconstruct result tuples or calculate numerical benchmark trends.

**Deliverable:** Dated terminology versions for method naming, experimental-setting definitions and literature navigation.

## 8. Hyungjoo Chae

VeriEnv studies safe web-agent learning through recreated websites and programmatically verifiable environments. [Primary source](https://arxiv.org/abs/2603.10505)

**Suggested research question:** Which interface labels and domain expressions in permitted website text could create ambiguity for web-agent tasks?

**Advanced references for your agent:** [recipe](../../examples/lab_recipes/hyungjoo-chae.json) and [metadata](../../examples/lab_recipes/hyungjoo-chae.metadata.json). Starter policy: `jargon`. Community routing label: `web-agent-ui-vocabulary`. Proposed fields: `ui_term_type`, `action_sense`, `ambiguity_note`.

1. Choose text exports from permitted recreated environments and define relevant interface vocabulary: action labels, state labels and domain objects. Established everyday words qualify when they carry a meaningful interface sense.

2. Export visible UI text or documentation to supported HTML/Markdown/text. Keep environment identifiers and generation/original origins in constraints, with an external family map. Quarry's HTML parser does not render JavaScript; a text export may be necessary.

3. Use Archive as a fictional action-label example, contrasting a noun archive in documentation. Request ui_term_type, action_sense and ambiguity_note. Policy examples illustrate the task; they do not authorize or execute any interface action.

4. Freeze environment/task families before tuning. Run Broad on identical exports and add action/state or ambiguous-label specialist lenses if needed. Scope any explicitly authorized fetching to permitted hosts; extractor replies cannot extend discovery.

5. Review contexts where identical labels have different meanings. Confirm whether an action_sense is explicitly supported by documentation. Retain separate senses across environments and undo aliases that hide meaningful differences.

6. Annotate whole held-out UI-text sources for omitted labels and terms, export the frozen lexicon, and use it in separate task-authoring or agent-error analysis. Quarry does not create a website replica, operate a web agent or verify rewards.

**Deliverable:** An interface-language inventory for task-authoring review and ambiguity analysis in controlled environments.

## 9. Ruohao Guo

Ruohao Guo's work includes [implicit misinformation (EchoMist)](https://arxiv.org/abs/2503.09598) and [lexical knowledge for language style understanding](https://arxiv.org/abs/2305.14592).

**Suggested research question:** Which lexical expressions and contextual senses appear in questions with potentially misleading presuppositions or distinct language styles?

**Advanced references for your agent:** [recipe](../../examples/lab_recipes/ruohao-guo.json) and [metadata](../../examples/lab_recipes/ruohao-guo.metadata.json). Starter policy: `neologisms`. Community routing label: `implicit-premise-language`. Proposed fields: `cue_function`, `topic`, `interpretation_note`.

1. Specify whether the study targets topic expressions, presupposition cues, euphemisms or style-specific senses. The supplied recipe uses the neologism starter but explicitly permits established expressions; it is not a novelty study.

2. Use permitted human-authored questions or appropriately identified released material. Preserve source origin and record IDs. Analyze model responses in a separately labeled corpus so generated language is not counted as a new community observation.

3. Use 5G radiation as a topic-expression illustration and include a neutral technical context as a boundary. The phrase itself does not determine misinformation. Few-shots are synthetic and do not assert a medical conclusion or a person's intent.

4. Freeze entire question/source families and blind held-out packets. Run Broad and inspect proposed cue_function, topic and interpretation_note fields. Add community-expression or sense/presupposition lenses only after development evidence supports the need.

5. Have reviewers apply a separate rubric for factual premises, interpretation and harm/style labels. Store those decisions as human annotations, preserve benign and misleading contexts separately, and never substitute occurrence grounding for fact verification.

6. Evaluate held-out lexical occurrence recall, including missed cues, and export source-linked expressions for a separate response-safety/style analysis. Quarry does not reproduce EchoMist evaluation, decide factual truth or train Self-Alert.

**Deliverable:** A contextual lexical-cue inventory for a separately adjudicated factuality or style study.

## 10. Ethan Mendes

Making Expert Reasoning Learnable with Self-Distillation (DAIL) studies learning from expert solutions; Ethan Mendes is a co-author. [Primary source](https://arxiv.org/abs/2602.02405)

**Suggested research question:** Which technical concepts appear in permitted expert solutions, and how do source-grounded vocabularies differ from separately identified generated reasoning traces?

**Advanced references for your agent:** [recipe](../../examples/lab_recipes/ethan-mendes.json) and [metadata](../../examples/lab_recipes/ethan-mendes.metadata.json). Starter policy: `jargon`. Community routing label: `expert-solution-vocabulary`. Proposed fields: `concept_domain`, `concept_role`, `source_definition_note`.

1. Choose a task domain and collection unit such as a complete mathematical solution. Include technical concepts and full domain expressions; ordinary answer words and entire derivation fragments are outside the glossary unless explicitly added to the policy.

2. Distinguish community-created solutions, expert material used with permission, and model-generated traces in source constraints. Do not label every input an official exam solution. Put all solutions/variants of one problem in an external family map.

3. Use invariant or another domain concept as a synthetic example. Request concept_domain, concept_role and source_definition_note. Include solution as a boundary because mathematical and chemical uses need different communities/senses.

4. Freeze held-out problem families, run Broad and inspect source-supported definitions. Optional lenses attend to technical concepts and local definitions, retaining all grounded candidates from either extractor.

5. Ask domain reviewers to adjudicate meanings and aliases. Separately assess reasoning validity outside the extraction tool; a grounded lemma name can occur in an invalid argument. Keep proposed difficulty or explanatory usefulness separate from source facts.

6. Evaluate complete held-out solutions for terminology recall and export lexical strata for an external DAIL or reasoning experiment. Quarry does not create aligned imitation traces, train self-distillation/contrastive objectives or validate proofs.

**Deliverable:** A technical-concept inventory for comparing vocabulary in expert/community solutions and separately labeled generated traces.

## 11. Nghia (Max) Le

MICE studies few-shot anaphora resolution in chemical synthesis protocols; Nghia/Max Le is an author. [Primary source](https://arxiv.org/html/2210.03690v2)

**Suggested research question:** Which materials, operations and technical noun phrases occur in a declared chemical-protocol corpus, and which contextual references need separate anaphora annotation?

**Advanced references for your agent:** [recipe](../../examples/lab_recipes/nghia-max-le.json) and [metadata](../../examples/lab_recipes/nghia-max-le.metadata.json). Starter policy: `jargon`. Community routing label: `chemical-protocol-vocabulary`. Proposed fields: `protocol_term_type`, `step_role`, `reference_note`.

1. Declare whether the study collects materials, instruments, operations or reference expressions. A reagent glossary and an anaphora dataset have different inclusion policies. The example targets technical terms and treats generic anaphors as boundary cases.

2. Ingest full permitted protocols or chemical-patent procedure text, retaining step structure and PDF pages. Record protocol/patent families externally. In the paper, synthetic procedures refers to chemical synthesis; do not assume the text was generated by a model.

3. Use Bromoacetyl bromide or 2,2,6,6-tetramethylpiperidine as material-name illustrations. Contrast the mixture, whose exact occurrence is observable while its components are unresolved. Do not invent antecedents or reaction results.

4. Freeze complete protocol families into splits. Run Broad, then optional material/operation and contextual-reference lenses after reviewing costs. Review the text around long names and window boundaries; partial recovery should remain visible.

5. Have domain annotators verify technical boundaries and meanings. Keep coreference chains and antecedent annotations in an external dataset. A reversible lexical alias does not establish coreference of a particular occurrence.

6. Evaluate entire held-out protocols for missed terms, export exact contexts/pages and IDs, and join them to the separate MICE-style reference-resolution experiment. Quarry does not resolve anaphora or produce experimental protocols.

**Deliverable:** A protocol vocabulary inventory with exact step/page contexts for external reference-resolution analysis.

## Additional existing NLPx research that a student or RA can adapt

### MedReadMe: medical-jargon and readability evidence

Chao Jiang and Wei Xu's [MedReadMe](https://arxiv.org/abs/2405.02144) studies medical sentence readability and complex spans. Chao is listed as an alumnus, so this is a lab precedent rather than a current-student assignment.

1. Copy the shipped `jargon` starter and define an intended readership and corpus, such as permitted professional/plain-language medical articles. Keep established medical expressions eligible.
2. Add optional suggestions for `reader_difficulty`, `abbreviation_expansion` and `difficulty_category`. The paper's examples include Schistosoma mansoni and distributive binding mechanism; do not treat the names alone as a calibrated difficulty judgment.
3. Ingest full articles or text PDFs with language, article identity, available dates, rights and paired-document family mapping. Freeze whole article pairs into one split before inspecting candidates.
4. Run Broad and inspect exact spans, sentence context, page locations and supported definitions. Add domain attention lenses only if useful on development sources and within a reviewed budget.
5. Have target readers/domain annotators label every relevant span on complete held-out articles and separately judge difficulty. Candidate review cannot identify missed jargon. Model difficulty suggestions remain hypotheses.
6. Export term/occurrence evidence and human judgments for an external readability study. Quarry does not reproduce MedReadMe's rating protocol or provide a calibrated readability score or clinical guidance.

### GAVEL: legal vocabulary and omission analysis

Yao Dou, Benjamin Mamut and Wei Xu's [GAVEL](https://arxiv.org/html/2601.04424v4) evaluates coverage in legal summarization. Yao is listed as an alumnus; this example is available to a current student or RA with suitable legal-text research goals.

1. Adapt `jargon` for terms such as consent decree and settlement, declaring what counts as legal vocabulary and what exact source collection is permitted.
2. Ingest complete case documents with PDF pages, filing identity/date and case-family mapping. Multiple filings from one case belong in the same split.
3. Preserve different contextual senses and source-defined distinctions. Do not equate a court order with a negotiated agreement merely because they appear in related documents.
4. Run bounded Broad and optional specialist passes; inspect truncation, failed sources and pending windows as processing gaps rather than hiding them.
5. Independently annotate whole held-out filings for missing terms, evaluate recall and false negatives, and inspect document-length/domain strata externally where needed.
6. Freeze and export the terminology inventory for a separate legal-summary coverage study. Term extraction recall is not summary factual coverage. Quarry does not implement GAVEL's checklist creation or evaluation agents.

## What each student should hand to a collaborator

A complete handoff includes the immutable dataset version and export manifest; the researcher's brief, original agent bundle, and checked-plan lineage; exact recipe/profile/prompt versions; source inventory, hashes, collection dates and supplied use constraints; full typed records and evidence (terms/senses and occurrences for Term studies); optional approved subset and reversible annotation/alias history; processing failures and pending/partial coverage; estimated/provider-reported costs and unknown reserves; frozen family split and complete-source gold; and a precision/recall/false-negative report with sampling and annotation notes. Follow the [publication protocol](../research/publication-protocol.md) to explain which decisions came from the researcher, the personal agent, deterministic Quarry checks, extraction models, and human annotators.

Maintain separate measures: **occurrence grounding**, **meaning/association judgments**, **historical novelty**, and **downstream model performance** answer different questions. Counts and agreement between GLM and DeepSeek do not measure recall. Adding Specialists does not by itself prove better research accuracy. Re-exporting a saved dataset version can reproduce the records without another provider call.

The browser is intended for one trusted local researcher and can poll slowly on large corpora. Use the CLI/API for larger collections. The personal-agent handoff is supported; directly executing that agent inside Quarry remains an extension. OCR, authenticated dataset connectors, full table records, conversation/preference construction, and benchmark generation remain extensions or downstream work.
