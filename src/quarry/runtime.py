"""Operator-declared inference provenance; never imports code or inspects credentials."""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import math
import re
from typing import Callable

FIELDS = ("checkpoint_sha256", "tokenizer_sha256", "chat_template_sha256", "container_digest",
          "model_revision", "tokenizer_revision", "chat_template_revision", "runtime_name",
          "runtime_version", "quantization", "gpu_model", "gpu_count", "driver_version", "cuda_version", "decode")
DECODE_FIELDS = {"temperature", "top_p", "top_k", "seed", "max_batch_tokens"}


def validate_runtime(value):
    """Normalize a bounded declaration, recording unavailable fields explicitly.

    Hashes and hardware descriptions are declarations, not independent evidence
    that an endpoint actually loaded those artifacts or used that hardware.
    """
    if not isinstance(value, dict) or set(value) - set(FIELDS) - {"schema_version", "origin", "unavailable_reasons"}:
        raise ValueError("runtime contains unsupported fields")
    if type(value.get("schema_version", 1)) is not int or value.get("schema_version", 1) != 1:
        raise ValueError("unsupported runtime schema")
    if value.get("origin", "operator_declared") != "operator_declared":
        raise ValueError("runtime declarations must identify their operator origin")
    result = {"schema_version": 1, "origin": "operator_declared"}
    missing = {}
    for field in FIELDS:
        item = value.get(field)
        if item is None:
            missing[field] = "not_declared_by_operator"
        elif field.endswith("_sha256"):
            if not isinstance(item, str) or not re.fullmatch(r"[a-f0-9]{64}", item):
                raise ValueError("runtime artifact hashes must be lowercase SHA256")
        elif field == "container_digest":
            if not isinstance(item, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", item):
                raise ValueError("runtime container digest must be immutable SHA256")
        elif field == "gpu_count":
            if type(item) is not int or not 0 <= item <= 1024:
                raise ValueError("runtime GPU count must be bounded")
        elif field == "decode":
            if not isinstance(item, dict) or set(item) - DECODE_FIELDS:
                raise ValueError("runtime decoding contains unsupported fields")
            for key, setting in item.items():
                if type(setting) not in (int, float) or not math.isfinite(setting):
                    raise ValueError("runtime decoding requires finite numbers")
                if key in {"top_k", "seed", "max_batch_tokens"} and type(setting) is not int:
                    raise ValueError("runtime integer decoding parameter required")
                lower, upper = ((0, 2) if key == "temperature" else (0, 1) if key == "top_p"
                                else (-1, 2147483647) if key == "seed" else (0, 10000000))
                if not lower <= setting <= upper:
                    raise ValueError("runtime decoding parameter outside bounds")
        elif (not isinstance(item, str) or not item.strip() or len(item) > 512
              or any(ord(c) < 32 for c in item)):
            raise ValueError("runtime requires bounded single-line descriptions")
        result[field] = deepcopy(item)
    # Recompute reasons instead of trusting arbitrary caller-supplied prose.
    result["unavailable_reasons"] = missing
    from .agent_setup import _credential_free
    _credential_free(result)
    return result


def runtime_manifest(model):
    return validate_runtime(model.get("runtime", {}))


@dataclass(frozen=True)
class PromptTokenizer:
    """Trusted Python registration counting the complete server-rendered prompt.

    The callback must include the server's chat template and special tokens.
    Registration never comes from research JSON, source text or model output.
    A library/site integration owns reviewing and installing the tokenizer.
    """
    identifier: str
    version: str
    count_prompt: Callable[[str], int]
    tokenizer_sha256: str | None = None
    chat_template_sha256: str | None = None

    def __post_init__(self):
        for value in (self.identifier, self.version):
            if not isinstance(value, str) or not value.strip() or len(value) > 256 or any(ord(c) < 32 for c in value):
                raise ValueError("trusted tokenizer requires bounded identity and version")
        if not callable(self.count_prompt):
            raise ValueError("trusted tokenizer requires a prompt-count callback")
        validate_runtime({"tokenizer_sha256": self.tokenizer_sha256,
                          "chat_template_sha256": self.chat_template_sha256,
                          "tokenizer_revision": self.identifier, "chat_template_revision": self.version})

    def manifest(self):
        return {"identifier": self.identifier, "version": self.version,
                "tokenizer_sha256": self.tokenizer_sha256,
                "chat_template_sha256": self.chat_template_sha256,
                "template_contract": "callback_counts_full_server_rendered_prompt"}

    def count(self, prompt):
        result = self.count_prompt(prompt)
        if type(result) is not int or not 0 <= result <= 100000000:
            raise ValueError("trusted tokenizer returned an invalid token count")
        return result
