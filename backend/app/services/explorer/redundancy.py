"""Pure, offline redundancy (near-duplicate symbol) detection.

This module is deliberately free of any I/O or database access so it can be
exercised by a fast, repeatable harness against a labeled fixture corpus. The
production entry point narrows candidates via ``search_symbols`` and then calls
the pure scorer here to decide.

Design priority is PRECISION, not recall: it is acceptable to miss a real
duplicate, but flagging a non-duplicate creates misinformed refactor tasks
(the failure mode that got ``schema_tasks`` / ``architecture_tasks`` disabled).

Every knob lives in :class:`SimilarityConfig` so heuristic variants can be tuned
without touching the corpus or harness. In particular, confidence requirements
are expressed as a *per-kind policy* (:class:`KindPolicy`): module-level
``function``/``class`` names are nearly unique by design, while class members
(``method`` ...) recur across unrelated classes by design (polymorphism), so the
latter must clear a substantially higher corroboration bar.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

# Path fragments that mark a symbol as not-our-code. A duplicate inside vendored
# deps or generated trees is never an actionable refactor for us.
_NON_FIRST_PARTY_FRAGMENTS: tuple[str, ...] = (
    ".dev-tools/",
    "node_modules/",
    ".venv/",
    "site-packages/",
    "dist/",
    "build/",
    ".next/",
    "__pycache__/",
    "/migrations/",
    "/alembic/versions/",
)

# Test code legitimately repeats names (``test_*``, fixtures); excluding it
# removes a huge class of false positives.
_TEST_PATH_FRAGMENTS: tuple[str, ...] = (
    "/tests/",
    "tests/",
    "/test/",
    ".test.",
    ".spec.",
    "_test.",
    "conftest.py",
)

# Architectural layers that form a *delegation stack*: a request/work flows
# api -> services -> storage (and tasks -> services/storage). A function with the
# same name appearing in two DIFFERENT layers here is almost always the layered
# call relationship (an API handler named ``create_rule`` delegating to a storage
# ``create_rule``), NOT a duplicate to consolidate. Verified against the live
# index, where this was the single largest false-positive class. Leaf locations
# (utils, clients, transport, cli/lib, ...) are deliberately NOT in this set, so a
# helper genuinely copied between, say, a util and a service is still caught.
_DELEGATION_LAYER_SEGMENTS: dict[str, str] = {
    "/api/": "api",
    "/services/": "services",
    "/storage/": "storage",
    "/tasks/": "tasks",
}

# Names that carry no design intent and collide constantly across files.
_NOISE_NAMES: frozenset[str] = frozenset(
    {
        "__init__",
        "__repr__",
        "__str__",
        "__eq__",
        "__hash__",
        "__enter__",
        "__exit__",
        "__call__",
        "main",
        "run",
        "setup",
        "teardown",
        "handler",
        "wrapper",
        "inner",
        "parse_args",  # argparse entrypoint boilerplate, like ``main``
        "props",  # ubiquitous React local prop-type name (``type Props``)
        "state",  # ubiquitous local state-type name
    }
)

# Next.js route-handler exports: every ``route.ts`` exports the HTTP verb it
# serves. Matched case-sensitively (uppercase) so a Python ``get``/``delete`` is
# untouched. These recur across every route by framework convention.
_HTTP_VERB_NAMES: frozenset[str] = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
)

# React/JS component-local callbacks follow the ``handleX`` / ``onX`` convention
# and are defined inside a component, not exported as shared surface. They recur
# across unrelated components by design (the frontend analog of method
# polymorphism), so a matching name is not evidence of duplication. Components
# themselves (PascalCase, e.g. ``CollapsibleSection``) are NOT matched and stay
# in scope, so a genuinely copy-pasted component is still caught.
_LOCAL_HANDLER_RE = re.compile(r"^(handle|on)[A-Z]\w*$")

# Tokens that mark a name as a versioned or copied variant rather than a real
# discriminating concept. They carry no design intent: ``parse_config`` and
# ``parse_config_v2`` are the same operation, one is just a later copy. We strip
# these everywhere a name is tokenized so the two collapse to the same token set
# (a copy, not a *specialization* that adds a meaningful domain token). Kept
# deliberately small and to obviously-generic versioning/lifecycle markers only.
_VERSION_COPY_TOKENS: frozenset[str] = frozenset(
    {
        "new",
        "old",
        "copy",
        "legacy",
        "deprecated",
        "orig",
        "original",
        "bak",
        "backup",
        "temp",
        "tmp",
    }
)

# Version markers once the tokenizer has split them: ``v2`` may arrive whole or
# as ``v`` + ``2``. A lone ``v`` and any pure-digit token are version noise; so
# is a combined ``v\d+``. (A standalone numeral never expresses design intent in
# an identifier — it is an ordinal/version, e.g. handler2, step3.)
_VERSION_TAG = re.compile(r"^(v\d+|v|\d+)$")

# Generic conversion/serialization vocabulary. When two methods share only a
# name and these "operation" words, that overlap echoes the method name itself
# and is not independent evidence of duplication (it is the hallmark of
# polymorphism: every class has a ``to_dict``/``serialize`` that mentions
# "dict"/"serialize"). Used only to discount corroboration for same-named
# class members, never to flag anything on its own.
_CONVERSION_VOCAB: frozenset[str] = frozenset(
    {
        "to",
        "from",
        "dict",
        "json",
        "serialize",
        "serialized",
        "serialization",
        "deserialize",
        "validate",
        "validated",
        "validation",
        "repr",
        "str",
        "string",
        "parse",
        "format",
        "convert",
        "encode",
        "decode",
        "dump",
        "load",
        "save",
        "get",
        "set",
        "update",
        "value",
        "values",
        "key",
        "keys",
        "field",
        "fields",
        "data",
    }
)

# Symbol kinds that are *class-scoped* (members of a type). Names here recur
# across unrelated classes by design — polymorphism / shared protocols — so they
# are governed by the stricter ``method`` policy bucket, not the module-level
# default. Anything else (function, class, type, constant, ...) is module-level
# design surface where a near-identical name is much stronger evidence.
_CLASS_SCOPED_KINDS: frozenset[str] = frozenset(
    {
        "method",
        "property",
        "getter",
        "setter",
        "staticmethod",
        "classmethod",
        "member",
        "field",
    }
)

# Base-class / framework / primitive-type vocabulary that recurs across every
# schema or model declaration by convention (``class X(BaseModel)`` ->
# ``basemodel``; ``response``/``request``/``schema`` suffixes; primitive field
# types). Like the conversion vocab for methods, these echo the *kind* of symbol
# rather than its domain, so they must not count as independent corroboration
# when judging whether two same-named CLASSES are a real duplicate. Without this,
# two unrelated API wire-models (``ClientListResponse`` in different domains)
# share only their name + framework boilerplate and would score the detector's
# max — the single largest live false-positive class for class/type kinds.
_SCHEMA_FRAMEWORK_VOCAB: frozenset[str] = frozenset(
    {
        "basemodel", "base", "model", "models", "schema", "schemas",
        "response", "request", "dto", "config", "settings", "mixin",
        "dataclass", "dataclasses", "enum", "intenum", "strenum", "typeddict",
        "namedtuple", "pydantic", "typing", "optional", "field", "fields",
        "str", "int", "float", "bool", "bytes", "dict", "list", "tuple",
        "set", "object", "any", "none", "type", "class",
    }
)

# English stopwords that appear constantly in docstrings/summaries. They are
# not design intent, so they must not count as *domain* corroboration when
# deciding whether a same-named class member is a real duplicate vs polymorphism.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "with",
        "into", "from", "as", "by", "at", "is", "are", "be", "this", "that",
        "it", "its", "their", "given", "return", "returns",
    }
)

# Generic descriptor vocabulary: filler adjectives/nouns that pepper docstrings
# but carry no *domain identity* (a ``HealthResponse`` summarised as "Basic health
# check response" shares ``check`` with another ``HealthResponse`` without that
# being evidence of a real duplicate). Stripped from domain corroboration so that
# two same-named schema classes must share a CONCRETE domain word (``backoff``,
# ``hmac``) — not boilerplate — to qualify. Deliberately limited to clearly-
# generic words, not domain nouns.
_GENERIC_DESCRIPTOR_VOCAB: frozenset[str] = frozenset(
    {
        "basic", "simple", "single", "multiple", "aggregated", "combined",
        "default", "generic", "common", "shared", "full", "partial", "raw",
        "main", "optional", "required", "current", "check", "checks", "value",
        "item", "items", "entry", "entries", "detail", "details", "info",
        "body", "content", "contents", "wrapper", "helper", "internal",
        "result", "results", "summary", "listing",
    }
)


def _stem(token: str) -> str:
    """Crude suffix-stripping stem so morphological variants collapse.

    ``clients`` -> ``client``, ``listing`` -> ``list``, ``metrics`` ->
    ``metric``. Used only to recognise that a candidate corroboration token is
    really a restatement of a *name* token (``ClientListResponse`` summarised as
    "listing clients"), never to alter scoring. Intentionally conservative — it
    only trims a short suffix when the stem stays a reasonable length.
    """
    for suffix, repl in (("ies", "y"), ("ing", ""), ("es", ""), ("ed", ""), ("s", "")):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: len(token) - len(suffix)] + repl
    return token

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_SPLIT_NONWORD = re.compile(r"[^A-Za-z0-9]+")
_DIGIT_RUN = re.compile(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])")


@dataclass(frozen=True)
class KindPolicy:
    """Per-symbol-kind confidence policy.

    Different symbol kinds carry different base rates of *legitimate* name
    reuse. Module-level ``function``/``class`` names are largely unique by
    design, so a near-identical name is strong evidence of duplication. Class
    members (``method`` ...) recur across unrelated classes by design
    (polymorphism: every model has ``to_dict``/``save``), so a matching name
    there is weak evidence and must clear a much higher bar.

    Fields left ``None`` inherit the corresponding global default on
    :class:`SimilarityConfig`. A pair's policy is resolved from its (shared)
    ``kind`` via :meth:`SimilarityConfig.policy_for`.
    """

    # Name jaccard above which the name alone may qualify a pair.
    name_only_threshold: float | None = None
    # Name jaccard that qualifies only when a second signal corroborates.
    corroborated_name_threshold: float | None = None
    # Final blended score required to report a pair of this kind.
    decision_threshold: float | None = None
    # Require BOTH a keyword/summary signal AND a signature signal (not just one).
    require_strong_corroboration: bool = False
    # Minimum independent (non-name) signal — the count of shared *domain*
    # corroboration tokens (keyword/summary tokens that are neither part of the
    # name nor generic conversion vocabulary). Guards same-named class members:
    # a real cross-class duplicate shares concrete domain words; mere
    # polymorphism does not.
    min_domain_corroboration: int = 0
    # If False, symbols of this kind never participate in detection at all.
    enabled: bool = True


@dataclass(frozen=True)
class ResolvedPolicy:
    """A :class:`KindPolicy` with every ``None`` filled from global defaults.

    Returned by :meth:`SimilarityConfig.policy_for`; thresholds are concrete
    floats so scoring comparisons are unambiguous.
    """

    name_only_threshold: float
    corroborated_name_threshold: float
    decision_threshold: float
    require_strong_corroboration: bool
    min_domain_corroboration: int
    enabled: bool


@dataclass(frozen=True)
class SimilarityConfig:
    """Tunable weights and gates for the duplicate scorer.

    All knobs are here so harness-driven variants stay diff-able.
    """

    # Hard gates (a pair failing any of these scores 0.0).
    require_same_kind: bool = True
    require_same_language: bool = True
    require_different_file: bool = True

    # Corroboration: a high name overlap alone is not enough to call a
    # duplicate unless names are (near) identical.
    name_identical_floor: float = 1.0
    name_only_threshold: float = 0.86  # name jaccard above which name alone counts
    corroborated_name_threshold: float = 0.70  # name jaccard that needs a second signal

    # Weights used to blend signals into the final score.
    weight_name: float = 0.6
    weight_keywords: float = 0.2
    weight_summary: float = 0.15
    weight_signature: float = 0.05

    # A pair is reported only at/above this final score (module-level default).
    decision_threshold: float = 0.82

    # Reject pairs where one name's tokens strictly contain the other plus a
    # discriminating token (specialization, e.g. create_task vs
    # create_refactor_task), unless names are otherwise identical.
    reject_specializations: bool = True

    # Per-kind confidence policy. Resolved by ``policy_for(kind)``; kinds with no
    # explicit entry use ``default_policy`` (the global thresholds above). The
    # ``method`` bucket governs every class-scoped kind (see _CLASS_SCOPED_KINDS).
    per_kind_policy: dict[str, KindPolicy] = field(
        default_factory=lambda: {
            # Module-level surface: highest-value, most-reliable. Standard bar.
            "function": KindPolicy(),
            # Classes/types: standard bar, but they must clear a minimum of
            # concrete *domain* corroboration beyond name + framework boilerplate.
            # Class signatures are declaration-only in the index (``class
            # X(BaseModel)`` — fields are NOT captured), so two unrelated
            # same-named wire-models are otherwise indistinguishable from a real
            # copy and score the detector's max. Requiring one shared domain token
            # (after stripping name + schema/framework vocab) rejects those while
            # keeping genuine copies that share real domain words.
            "class": KindPolicy(min_domain_corroboration=1),
            # Class members (method/property/...): OUT OF SCOPE for v1. The plan's
            # target is top-level public surface (functions/classes/constants/
            # endpoints/commands). On the live index, same-named methods are
            # overwhelmingly interface/override polymorphism (e.g. ``get_health_status``
            # implemented by every scanner subtype) — "consolidating" those means
            # mangling a class hierarchy, the textbook misinformed refactor. The
            # strict thresholds below are retained as defense-in-depth; ``enabled``
            # is the operative switch.
            "method": KindPolicy(
                name_only_threshold=1.01,
                corroborated_name_threshold=0.85,
                decision_threshold=0.90,
                require_strong_corroboration=True,
                min_domain_corroboration=2,
                enabled=False,
            ),
        }
    )

    # Reject same-named callables whose parameter arity differs. A facade that
    # resolves args and delegates to a same-named lower-level impl has a DIFFERENT
    # arg list (e.g. ``get_effective_rules(project_id, category)`` ->
    # ``get_effective_rules(base_standard_id, project_standard_id, category)``);
    # genuine copies preserve arity. Restricted to Python signatures (clean
    # ``ast.unparse`` output) and fires only when BOTH arities parse confidently.
    reject_signature_arity_mismatch: bool = True

    # Reject same-named symbols where one file is a hub module and the other a
    # same-directory split-out it delegates to (``subtasks.py`` vs
    # ``subtasks_crud.py``). A version/copy suffix (``_v2``) is exempt — that is a
    # genuine module copy, not a domain split.
    reject_sibling_module_delegation: bool = True

    # Reject same-named symbols that span two different delegation-stack layers
    # (api/services/storage/tasks) — the layered-call pattern, not duplication.
    reject_cross_layer_delegation: bool = True

    # Reject pairs where exactly one side lives in a ``_client_`` wrapper module.
    # Those mirror server/endpoint names by design (an HTTP client), so the match
    # is a client<->server mirror, not a duplicate. Two client modules still
    # compare normally.
    reject_client_mirror: bool = True

    scope_first_party_only: bool = True
    exclude_tests: bool = True
    public_only: bool = True

    extra_noise_names: frozenset[str] = field(default_factory=frozenset)

    @property
    def default_policy(self) -> ResolvedPolicy:
        """Fallback policy carrying the global thresholds."""
        return ResolvedPolicy(
            name_only_threshold=self.name_only_threshold,
            corroborated_name_threshold=self.corroborated_name_threshold,
            decision_threshold=self.decision_threshold,
            require_strong_corroboration=False,
            min_domain_corroboration=0,
            enabled=True,
        )

    def policy_for(self, kind: str | None) -> ResolvedPolicy:
        """Resolve the effective policy for a symbol kind, filling defaults.

        Class-scoped kinds (method, property, ...) collapse to the ``method``
        bucket so the strict members policy is not silently bypassed by an
        extractor that labels accessors differently.
        """
        key = (kind or "").lower()
        if key in _CLASS_SCOPED_KINDS:
            key = "method"
        base = self.per_kind_policy.get(key)
        if base is None:
            return self.default_policy
        # Fill any None fields from the global defaults.
        return ResolvedPolicy(
            name_only_threshold=(
                base.name_only_threshold
                if base.name_only_threshold is not None
                else self.name_only_threshold
            ),
            corroborated_name_threshold=(
                base.corroborated_name_threshold
                if base.corroborated_name_threshold is not None
                else self.corroborated_name_threshold
            ),
            decision_threshold=(
                base.decision_threshold
                if base.decision_threshold is not None
                else self.decision_threshold
            ),
            require_strong_corroboration=base.require_strong_corroboration,
            min_domain_corroboration=base.min_domain_corroboration,
            enabled=base.enabled,
        )


DEFAULT_CONFIG = SimilarityConfig()


def _strip_version_copy(tokens: set[str]) -> set[str]:
    """Drop versioning/copy markers (v2, 2, new, legacy, ...) from a token set.

    These tokens never distinguish two pieces of design intent — they only mark
    a later copy/version — so they must not dilute name similarity nor count as
    a "discriminating" token when judging specialization.
    """
    return {
        t
        for t in tokens
        if t not in _VERSION_COPY_TOKENS and not _VERSION_TAG.match(t)
    }


def tokenize_name(name: str) -> set[str]:
    """Split an identifier into lowercased subtokens (camelCase + snake_case).

    Version/copy markers (``v2``, ``2``, ``new``, ``legacy`` ...) are stripped:
    they distinguish a copy from its original, never two distinct concepts, so
    they must not dilute name similarity. ``parse_config`` and ``parse_config_v2``
    therefore tokenize identically. If a name is *entirely* version markers
    (degenerate), the raw tokens are kept so the name is not silently emptied.
    """
    if not name:
        return set()
    pieces: list[str] = []
    for chunk in _SPLIT_NONWORD.split(name):
        if not chunk:
            continue
        camel = _CAMEL_BOUNDARY.sub(" ", chunk)
        camel = _DIGIT_RUN.sub(" ", camel)
        pieces.extend(camel.split())
    raw = {p.lower() for p in pieces if p}
    stripped = _strip_version_copy(raw)
    return stripped or raw


def _token_set(text: str | None) -> set[str]:
    if not text:
        return set()
    return {t.lower() for t in _SPLIT_NONWORD.split(text) if len(t) > 1}


def _keyword_set(keywords: Any) -> set[str]:
    if not keywords:
        return set()
    return {str(k).lower() for k in keywords if str(k).strip()}


def jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity of two token sets (0.0 when both empty)."""
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def is_first_party(file_path: str | None) -> bool:
    """True when a path is our own source (not vendored/generated).

    Matches excluded fragments on path-SEGMENT boundaries, so ``alembic/versions/``
    is caught whether it sits at the repo root or under ``backend/``, and a real
    dir like ``redistribute/`` is not mistaken for the ``dist/`` exclusion.
    """
    if not file_path:
        return False
    norm = file_path.replace("\\", "/")
    if norm.startswith("./"):  # strip a leading "./" only — NOT the dot of ".dev-tools"
        norm = norm[2:]
    padded = "/" + norm  # so a leading segment also has a boundary slash
    return not any(("/" + frag.strip("/") + "/") in padded for frag in _NON_FIRST_PARTY_FRAGMENTS)


def _is_test_path(file_path: str | None) -> bool:
    if not file_path:
        return False
    norm = file_path.replace("\\", "/")
    return any(frag in norm for frag in _TEST_PATH_FRAGMENTS)


def _is_client_module(file_path: str | None) -> bool:
    """True for HTTP-client wrappers / published client SDKs.

    Covers ``cli/_client_*.py`` wrappers and ``packages/<name>-client/`` SDK
    packages. Both mirror server/endpoint names (and wire models) by design, so a
    name match across the boundary is a client<->server mirror, not a duplicate.
    """
    if not file_path:
        return False
    norm = file_path.replace("\\", "/")
    return "_client" in norm or "-client/" in norm


def _layer_of(file_path: str | None) -> str | None:
    """The delegation-stack layer of a path, or None for leaf/other locations."""
    if not file_path:
        return None
    norm = file_path.replace("\\", "/")
    for segment, layer in _DELEGATION_LAYER_SEGMENTS.items():
        if segment in norm:
            return layer
    return None


def _module_stem(file_path: str) -> tuple[str, str]:
    """(directory, filename-without-extension) for a path, posix-normalised."""
    norm = file_path.replace("\\", "/")
    directory, _, filename = norm.rpartition("/")
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return directory, stem


def _is_sibling_module_delegation(path_a: str | None, path_b: str | None) -> bool:
    """True for a hub module and a same-directory split-out it delegates to.

    A module ``foo.py`` that aggregates and re-exports/delegates to sibling
    split-outs ``foo_crud.py`` / ``foo_summaries.py`` (same directory, the spoke's
    stem is the hub's stem + ``_<domain>``) is the textbook decomposition idiom:
    the same-named symbol in the hub is a thin facade over the spoke's impl, not
    an independent copy (verified on the live index — ``subtasks.py`` /
    ``db_workbench.py`` / ``context_injector.py`` hubs). The arity gate misses
    these because a pass-through facade preserves arity.

    A *version/copy* suffix (``foo_v2.py``, ``foo_new.py``) is deliberately NOT
    treated as delegation — that is a later copy of the whole module and its
    same-named symbols ARE genuine duplicates to consolidate.
    """
    if not path_a or not path_b:
        return False
    dir_a, stem_a = _module_stem(path_a)
    dir_b, stem_b = _module_stem(path_b)
    if dir_a != dir_b or stem_a == stem_b:
        return False
    hub, spoke = (stem_a, stem_b) if len(stem_a) <= len(stem_b) else (stem_b, stem_a)
    if not spoke.startswith(hub + "_"):
        return False
    # Tokenize the differentiating suffix WITHOUT tokenize_name's degenerate
    # fallback (which would keep a lone version marker). If the suffix is purely
    # version/copy noise (``_v2``, ``_new``) it is a later copy of the module, so
    # its same-named symbols are genuine duplicates — NOT delegation.
    raw_suffix: set[str] = set()
    for chunk in _SPLIT_NONWORD.split(spoke[len(hub) + 1 :]):
        if not chunk:
            continue
        camel = _DIGIT_RUN.sub(" ", _CAMEL_BOUNDARY.sub(" ", chunk))
        raw_suffix.update(p.lower() for p in camel.split() if p)
    return bool(_strip_version_copy(raw_suffix))


# Bracket pairs whose nesting must be tracked when counting callable params, so a
# comma inside a type annotation or default (``dict[str, int]``, ``f(x=g(1, 2))``)
# is not mistaken for a parameter separator. Angle brackets are deliberately NOT
# tracked (``->`` return arrows, ``=>`` arrows, comparisons make ``<``/``>``
# ambiguous); the arity gate is therefore restricted to Python signatures, which
# come from ``ast.unparse`` and never use ``<...>`` for parameter types.
_ARITY_OPENERS: dict[str, str] = {"(": ")", "[": "]", "{": "}"}
_ARITY_CLOSERS: frozenset[str] = frozenset({")", "]", "}"})


def _param_arity(signature: str | None) -> int | None:
    """Count top-level parameters in a callable signature, or None if unparseable.

    Parses the first balanced ``(...)`` of the signature, counting depth-0 commas
    so nested brackets in annotations/defaults do not inflate the count. A leading
    ``self``/``cls`` receiver is dropped. Returns ``None`` when there is no
    parenthesised argument list (a class/constant/type signature) so callers can
    treat "unknown arity" distinctly from "zero arity" — only two *confidently
    parsed* arities are ever compared.
    """
    if not signature:
        return None
    start = signature.find("(")
    if start == -1:
        return None
    depth = 0
    params: list[str] = []
    current: list[str] = []
    closed = False
    for ch in signature[start:]:
        if ch in _ARITY_OPENERS:
            if depth > 0:  # keep the outermost '(' out of the captured params
                current.append(ch)
            depth += 1
        elif ch in _ARITY_CLOSERS:
            depth -= 1
            if depth <= 0:
                closed = True
                break
            current.append(ch)
        elif ch == "," and depth == 1:
            params.append("".join(current))
            current = []
        elif depth >= 1:
            current.append(ch)
    if not closed:
        return None
    tail = "".join(current).strip()
    if tail or params:
        params.append(tail)
    arity = 0
    for raw in params:
        token = raw.strip()
        if not token:
            continue  # empty arg list -> 0 params
        head = token.lstrip("*").split(":", 1)[0].split("=", 1)[0].strip()
        if head in {"self", "cls"}:
            continue
        arity += 1
    return arity


def is_public_symbol(symbol: dict[str, Any], config: SimilarityConfig = DEFAULT_CONFIG) -> bool:
    """True when a symbol is public design surface worth de-duplicating."""
    name = str(symbol.get("name") or "")
    if not name:
        return False
    if name.startswith("_"):
        return False
    if name in _HTTP_VERB_NAMES:  # case-sensitive: Next.js route verbs only
        return False
    low = name.lower()
    if low in _NOISE_NAMES or low in config.extra_noise_names:
        return False
    if _LOCAL_HANDLER_RE.match(name):
        return False
    # ``test_x`` functions and a bare ``test`` are not design surface.
    return not (low.startswith("test_") or low == "test")


def is_eligible(symbol: dict[str, Any], config: SimilarityConfig = DEFAULT_CONFIG) -> bool:
    """Whether a symbol should participate in duplicate detection at all."""
    path = symbol.get("file_path")
    if config.scope_first_party_only and not is_first_party(path):
        return False
    if config.exclude_tests and _is_test_path(path):
        return False
    if config.public_only and not is_public_symbol(symbol, config):
        return False
    return config.policy_for(symbol.get("kind")).enabled


def _is_specialization(tokens_a: set[str], tokens_b: set[str]) -> bool:
    """One token set strictly contains the other plus >=1 *meaningful* token.

    Names are already version/copy-normalized by ``tokenize_name``, so a
    strict-superset here genuinely adds a domain word (a specialization, e.g.
    ``create_task`` vs ``create_refactor_task``) rather than a version suffix.
    """
    if tokens_a == tokens_b:
        return False
    return bool(tokens_a < tokens_b or tokens_b < tokens_a)


def _owner_of(symbol: dict[str, Any]) -> str:
    """The qualifying owner (class) of a member, from its qualified name.

    ``Task.to_dict`` -> ``task``; a bare/unqualified name -> "" (unknown owner).
    """
    qn = str(symbol.get("qualified_name") or "")
    name = str(symbol.get("name") or "")
    if "." in qn:
        owner = qn.rsplit(".", 1)[0]
        # take the last path segment, e.g. ``pkg.Task`` -> ``Task``
        owner = owner.rsplit(".", 1)[-1]
        return owner.lower()
    if qn and qn.lower() != name.lower():
        return qn.lower()
    return ""


def _domain_corroboration(
    name_a: set[str],
    name_b: set[str],
    raw_name_a: str,
    raw_name_b: str,
    kw_a: set[str],
    kw_b: set[str],
    sum_a: set[str],
    sum_b: set[str],
) -> set[str]:
    """Shared tokens that are *concrete domain* evidence, not name/boilerplate.

    Independent corroboration that two same-named symbols are a real duplicate:
    the tokens both share via keywords/summary, after removing everything that
    merely restates the name (the name's subtokens, their crude stems, and the
    whole lowercased identifier — extractors store ``ClientListResponse`` itself
    as a keyword) or is generic vocabulary (conversion verbs, schema/framework
    boilerplate, stopwords, filler descriptors). What remains — ``backoff`` for a
    ``RetryPolicy`` copy, ``hmac`` for a ``WebhookPayload`` copy — is real signal.
    """
    shared = (kw_a & kw_b) | (sum_a & sum_b)
    name_tokens = name_a | name_b
    whole_names = {raw_name_a.lower(), raw_name_b.lower()}
    generic = _CONVERSION_VOCAB | _SCHEMA_FRAMEWORK_VOCAB | _STOPWORDS | _GENERIC_DESCRIPTOR_VOCAB
    # Stems of everything that does NOT count, so a plural/gerund variant
    # (``clients``/``listing``/``requests``) is recognised as a restatement of a
    # name token or generic word, not independent domain evidence.
    ignore_stems = {_stem(t) for t in (name_tokens | generic)}
    domain: set[str] = set()
    for tok in shared:
        if tok in name_tokens or tok in whole_names or tok in generic:
            continue
        if _stem(tok) in ignore_stems:
            continue
        domain.add(tok)
    return domain


@dataclass(frozen=True)
class PairScore:
    """A scored pair with the breakdown that produced it."""

    score: float
    name_sim: float
    keyword_sim: float
    summary_sim: float
    signature_sim: float
    reason: str


def score_pair(
    a: dict[str, Any],
    b: dict[str, Any],
    config: SimilarityConfig = DEFAULT_CONFIG,
) -> PairScore:
    """Pairwise duplicate likelihood in [0, 1] with a breakdown.

    Returns a 0.0 score (with a reason) for any pair that fails a hard gate.
    Per-kind requirements are resolved from the shared ``kind`` via
    :meth:`SimilarityConfig.policy_for`.
    """
    if config.require_same_kind and (a.get("kind") != b.get("kind")):
        return PairScore(0.0, 0.0, 0.0, 0.0, 0.0, "different-kind")
    if config.require_same_language and (a.get("language") != b.get("language")):
        return PairScore(0.0, 0.0, 0.0, 0.0, 0.0, "different-language")
    if config.require_different_file and (a.get("file_path") == b.get("file_path")):
        return PairScore(0.0, 0.0, 0.0, 0.0, 0.0, "same-file")

    if config.reject_cross_layer_delegation:
        layer_a, layer_b = _layer_of(a.get("file_path")), _layer_of(b.get("file_path"))
        if layer_a and layer_b and layer_a != layer_b:
            return PairScore(0.0, 0.0, 0.0, 0.0, 0.0, "cross-layer-delegation")

    if config.reject_client_mirror:
        a_client = _is_client_module(a.get("file_path"))
        b_client = _is_client_module(b.get("file_path"))
        if a_client != b_client:  # exactly one side is a client wrapper/SDK
            return PairScore(0.0, 0.0, 0.0, 0.0, 0.0, "client-mirror")

    policy = config.policy_for(a.get("kind"))

    name_a = tokenize_name(str(a.get("name") or ""))
    name_b = tokenize_name(str(b.get("name") or ""))
    name_sim = jaccard(name_a, name_b)

    if (
        config.reject_specializations
        and name_sim < config.name_identical_floor
        and _is_specialization(name_a, name_b)
    ):
        return PairScore(0.0, name_sim, 0.0, 0.0, 0.0, "specialization")

    # Arity gate: a facade and the same-named lower-level impl it delegates to
    # have different parameter lists (the largest live FP class that the
    # cross-layer rule misses, because facade and impl often sit in the SAME
    # package/tree). Python-only: ``ast.unparse`` signatures are clean enough to
    # count params unambiguously; fires only when both sides parse confidently.
    if (
        config.reject_signature_arity_mismatch
        and str(a.get("language") or "").lower() == "python"
    ):
        arity_a = _param_arity(str(a.get("signature") or ""))
        arity_b = _param_arity(str(b.get("signature") or ""))
        if arity_a is not None and arity_b is not None and arity_a != arity_b:
            return PairScore(0.0, name_sim, 0.0, 0.0, 0.0, "signature-arity-mismatch")

    # Sibling-module delegation: same symbol name in a hub module and a same-dir
    # split-out it delegates to (``subtasks.py`` -> ``subtasks_crud.py``). Checked
    # after specialization so a genuinely different name (``load_config`` vs
    # ``load_config_overrides``) is classed as specialization, not delegation.
    # Restricted to CALLABLE kinds: delegation is a call relationship, so a hub
    # function is a facade over the spoke's impl — but a CONSTANT or TYPE
    # re-declared in a sibling module is genuine duplication (it should import the
    # shared definition), not delegation, and must stay flagged.
    kind_l = str(a.get("kind") or "").lower()
    is_callable = kind_l == "function" or kind_l in _CLASS_SCOPED_KINDS
    if (
        config.reject_sibling_module_delegation
        and is_callable
        and _is_sibling_module_delegation(a.get("file_path"), b.get("file_path"))
    ):
        return PairScore(0.0, name_sim, 0.0, 0.0, 0.0, "sibling-module-delegation")

    kw_a, kw_b = _keyword_set(a.get("keywords")), _keyword_set(b.get("keywords"))
    sum_a, sum_b = _token_set(a.get("summary")), _token_set(b.get("summary"))
    kw_sim = jaccard(kw_a, kw_b)
    sum_sim = jaccard(sum_a, sum_b)
    sig_sim = jaccard(_token_set(a.get("signature")), _token_set(b.get("signature")))

    text_corroboration = (kw_sim > 0.0) or (sum_sim > 0.0)
    sig_corroboration = sig_sim > 0.0

    # Per-kind precision gate: name must be (near) identical on its own, or
    # strong-enough but backed by a second signal. For the strict ``method``
    # bucket the name-only floor is set above 1.0, so a name match alone never
    # qualifies — polymorphism (to_dict on two classes) is rejected here.
    name_qualifies = name_sim >= policy.name_only_threshold or (
        name_sim >= policy.corroborated_name_threshold and text_corroboration
    )
    if not name_qualifies:
        return PairScore(0.0, name_sim, kw_sim, sum_sim, sig_sim, "weak-name")

    # Stricter kinds must show BOTH a text signal and a signature signal, plus a
    # minimum of concrete *domain* corroboration (shared keyword/summary tokens
    # that are not the name itself and not generic conversion vocabulary).
    if policy.require_strong_corroboration and not (text_corroboration and sig_corroboration):
        return PairScore(0.0, name_sim, kw_sim, sum_sim, sig_sim, "needs-strong-corroboration")

    if policy.min_domain_corroboration > 0:
        domain = _domain_corroboration(
            name_a, name_b,
            str(a.get("name") or ""), str(b.get("name") or ""),
            kw_a, kw_b, sum_a, sum_b,
        )
        if len(domain) < policy.min_domain_corroboration:
            # Same name + only generic boilerplate in common: polymorphism for a
            # class member, framework-shaped name collision for a class/type.
            kind_l = str(a.get("kind") or "").lower()
            reason = "polymorphism" if kind_l in _CLASS_SCOPED_KINDS else "weak-domain-corroboration"
            return PairScore(0.0, name_sim, kw_sim, sum_sim, sig_sim, reason)

    score = (
        config.weight_name * name_sim
        + config.weight_keywords * kw_sim
        + config.weight_summary * sum_sim
        + config.weight_signature * sig_sim
    )
    if score < policy.decision_threshold:
        return PairScore(score, name_sim, kw_sim, sum_sim, sig_sim, "below-kind-threshold")
    return PairScore(score, name_sim, kw_sim, sum_sim, sig_sim, "scored")


@dataclass(frozen=True)
class DuplicateCluster:
    """A group of symbols judged to be near-duplicates of each other."""

    members: list[dict[str, Any]]
    score: float
    reason: str

    @property
    def names(self) -> list[str]:
        return [str(m.get("name")) for m in self.members]

    @property
    def paths(self) -> list[str]:
        return [str(m.get("file_path")) for m in self.members]


def cluster_signature(cluster: DuplicateCluster) -> str:
    """Stable identity for a cluster across scans.

    Keyed on the sorted ``name@file_path`` of every member so the same set of
    duplicate sites maps to the same signature on a later scan (enabling dedupe
    and stale-task retirement), independent of symbol_id churn or member order.
    """
    parts = sorted(f"{m.get('name')}@{m.get('file_path')}" for m in cluster.members)
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def find_duplicate_pairs(
    symbols: list[dict[str, Any]],
    config: SimilarityConfig = DEFAULT_CONFIG,
) -> list[tuple[int, int, PairScore]]:
    """All eligible index pairs scoring at/above their per-kind threshold."""
    eligible_idx = [i for i, s in enumerate(symbols) if is_eligible(s, config)]
    hits: list[tuple[int, int, PairScore]] = []
    for ai in range(len(eligible_idx)):
        for bi in range(ai + 1, len(eligible_idx)):
            i, j = eligible_idx[ai], eligible_idx[bi]
            ps = score_pair(symbols[i], symbols[j], config)
            # ``scored`` is the only reason that survives the per-kind threshold;
            # every gate returns a distinct non-scored reason at score 0/below.
            threshold = config.policy_for(symbols[i].get("kind")).decision_threshold
            if ps.reason == "scored" and ps.score >= threshold:
                hits.append((i, j, ps))
    return hits


def cluster_duplicates(
    symbols: list[dict[str, Any]],
    config: SimilarityConfig = DEFAULT_CONFIG,
) -> list[DuplicateCluster]:
    """Group symbols into near-duplicate clusters via connected components."""
    pairs = find_duplicate_pairs(symbols, config)
    if not pairs:
        return []

    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    pair_score: dict[frozenset[int], float] = {}
    for i, j, ps in pairs:
        union(i, j)
        pair_score[frozenset((i, j))] = ps.score

    groups: dict[int, list[int]] = {}
    for node in {n for pair in pair_score for n in pair}:
        groups.setdefault(find(node), []).append(node)

    clusters: list[DuplicateCluster] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        scores = [
            s
            for key, s in pair_score.items()
            if key <= set(members)
        ]
        min_score = min(scores) if scores else 0.0
        clusters.append(
            DuplicateCluster(
                members=[symbols[m] for m in sorted(members)],
                score=min_score,
                reason="consolidate-duplicate",
            )
        )
    clusters.sort(key=lambda c: c.score, reverse=True)
    return clusters
