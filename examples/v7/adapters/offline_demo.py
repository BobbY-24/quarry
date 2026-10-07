"""Synthetic adapter-shaped demonstration; imports no third-party baselines."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from termfinder.adapters import RecordedBackend, adapter_config, run_adapter
from termfinder.experiments import compare_experiments
from termfinder.exports import canonical_json


def demonstrate(out):
    root = Path(out).resolve()
    root.mkdir(parents=True, exist_ok=False)
    texts = {"repeated": "zorb zorb", "filtered": "An eligible moonstep.", "negative": "Ordinary water."}
    corpus = {"schema_version": "1", "corpus_id": "synthetic-adapter-boundaries", "data_type": "term", "sources": [
        {"source_id": sid, "text": text, "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
         "domain": "synthetic", "language": "en", "family_id": sid} for sid, text in texts.items()]}
    # Independent hand-authored complete-source fixture labels, fixed first.
    labels = {"repeated": [{"expression": "zorb", "language": "en", "sense": None, "occurrences": [{"start": 0, "end": 4}, {"start": 5, "end": 9}]}],
              "filtered": [{"expression": "moonstep", "language": "en", "sense": None, "occurrences": [{"start": 12, "end": 20}]}], "negative": []}
    gold = [{"source_id": s["source_id"], "text_sha256": s["text_sha256"], "complete": True, "terms": labels[s["source_id"]]} for s in corpus["sources"]]
    def reply(raw):
        return {"raw_reply": raw, "usage": {"input_tokens": 20, "output_tokens": 10}, "cost_usd": 0, "cost_basis": "simulated", "missing_reason": None}
    lx = {"repeated": {"calls": [reply('{"extractions":[{"term":"zorb"},{"term":"zorbs"}]}')], "proposals": [
        {"observed_text": "zorb", "language": "en", "native_start": 0, "native_end": 4, "retained": True},
        {"observed_text": "zorbs", "language": "en", "native_start": 5, "native_end": 9, "native_alignment": "match_fuzzy", "retained": True}]},
        "filtered": {"calls": [reply("malformed {")], "proposals": [], "status": "failed", "reason": "synthetic_parse_failure"},
        "negative": {"calls": [reply('{"extractions":[]}')], "proposals": []}}
    delm = {"repeated": {"calls": [reply('{"terms":[{"observed_text":"zorb","language":"en"}]}')],
        "proposals": [{"observed_text": "zorb", "language": "en", "retained": True}]},
        "filtered": {"calls": [], "proposals": [], "decisions": [{"stage": "relevance_filter", "retained": False}], "reason": "all_chunks_filtered_by_native_relevance_policy"},
        "negative": {"calls": [reply('{"terms":[]}')], "proposals": []}}
    packets = [run_adapter(corpus, adapter_config("langextract", track="native", settings={"enable_fuzzy_alignment": True}), RecordedBackend(lx), run_id="langextract-native-shaped"),
               run_adapter(corpus, adapter_config("delm", track="native", settings={"keywords": ["zorb"]}), RecordedBackend(delm), run_id="delm-native-shaped")]
    report = compare_experiments(corpus, gold, [p["run"] for p in packets])
    for name, value in (("corpus.json", corpus), ("gold.json", gold), ("packets.json", packets), ("comparison.json", report)):
        (root / name).write_text(canonical_json(value) + "\n", encoding="utf-8")
    assert report == compare_experiments(corpus, gold, [p["run"] for p in packets])
    return {"offline": True, "paid_requests": 0, "verification_kind": "synthetic_library_shaped_fixture",
            "real_library_execution": False, "source_count": 3, "report": str(root / "comparison.json"),
            "claim_limit": "Boundary accounting, alignment and scoring mechanics only"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    print(json.dumps(demonstrate(parser.parse_args().out), sort_keys=True, indent=2))
