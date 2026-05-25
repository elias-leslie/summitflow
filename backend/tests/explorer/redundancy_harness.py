"""Offline harness that scores the redundancy detector against the labeled corpus.

Pure and DB-free. Reports pair-level precision, recall, an *achievable* recall
that excludes pure-synonym pairs (which a lexical detector cannot reach), and the
explicit false-positive list — the number that decides whether the detector is
safe to wire into the live task pipeline.

Run standalone:  python -m tests.explorer.redundancy_harness
Import:          from tests.explorer.redundancy_harness import evaluate
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any

from app.services.explorer.redundancy import (
    DEFAULT_CONFIG,
    SimilarityConfig,
    find_duplicate_pairs,
)

from .redundancy_corpus import GOLD_CLUSTERS, SYMBOLS, SYNONYM_GOLD_CLUSTERS


def _gold_pairs(clusters: list[set[str]]) -> set[frozenset[str]]:
    pairs: set[frozenset[str]] = set()
    for cluster in clusters:
        for a, b in combinations(sorted(cluster), 2):
            pairs.add(frozenset((a, b)))
    return pairs


@dataclass
class HarnessResult:
    precision: float
    recall: float
    achievable_recall: float
    true_positives: list[frozenset[str]]
    false_positives: list[tuple[frozenset[str], float, str, float]]
    false_negatives: list[frozenset[str]]
    predicted_count: int

    @property
    def fp_count(self) -> int:
        return len(self.false_positives)


def evaluate(
    symbols: list[dict[str, Any]] | None = None,
    config: SimilarityConfig = DEFAULT_CONFIG,
) -> HarnessResult:
    """Run the detector over the corpus and compute pair-level metrics."""
    symbols = symbols if symbols is not None else SYMBOLS
    by_index_id = {i: s["id"] for i, s in enumerate(symbols)}

    gold = _gold_pairs(GOLD_CLUSTERS)
    synonym_gold = _gold_pairs(SYNONYM_GOLD_CLUSTERS)
    achievable_gold = gold - synonym_gold

    predicted: dict[frozenset[str], tuple[float, str, float]] = {}
    for i, j, ps in find_duplicate_pairs(symbols, config):
        predicted[frozenset((by_index_id[i], by_index_id[j]))] = (
            ps.score,
            ps.reason,
            ps.name_sim,
        )

    predicted_pairs = set(predicted)
    tp = sorted(predicted_pairs & gold, key=lambda p: sorted(p))
    fp_pairs = sorted(predicted_pairs - gold, key=lambda p: sorted(p))
    fn = sorted(achievable_gold - predicted_pairs, key=lambda p: sorted(p))

    false_positives = [
        (pair, predicted[pair][0], predicted[pair][1], predicted[pair][2])
        for pair in fp_pairs
    ]

    precision = len(tp) / len(predicted_pairs) if predicted_pairs else 1.0
    recall = len(predicted_pairs & gold) / len(gold) if gold else 0.0
    achievable_recall = (
        len(predicted_pairs & achievable_gold) / len(achievable_gold)
        if achievable_gold
        else 0.0
    )

    return HarnessResult(
        precision=precision,
        recall=recall,
        achievable_recall=achievable_recall,
        true_positives=tp,
        false_positives=false_positives,
        false_negatives=fn,
        predicted_count=len(predicted_pairs),
    )


def format_report(result: HarnessResult) -> str:
    """Human-readable harness report."""
    lines = [
        "=== Redundancy detector harness ===",
        f"predicted pairs : {result.predicted_count}",
        f"precision       : {result.precision:.3f}   (false positives: {result.fp_count})",
        f"recall (all)    : {result.recall:.3f}",
        f"recall (lexical): {result.achievable_recall:.3f}   (excludes pure synonyms)",
        "",
        f"TRUE POSITIVES ({len(result.true_positives)}):",
    ]
    for pair in result.true_positives:
        lines.append(f"  + {' ~ '.join(sorted(pair))}")
    lines.append("")
    lines.append(f"FALSE POSITIVES ({result.fp_count}) -- must be 0 to ship:")
    for pair, score, reason, name_sim in result.false_positives:
        lines.append(
            f"  ! {' ~ '.join(sorted(pair))}  score={score:.3f} name={name_sim:.3f} ({reason})"
        )
    lines.append("")
    lines.append(f"MISSED (lexically reachable) ({len(result.false_negatives)}):")
    for pair in result.false_negatives:
        lines.append(f"  - {' ~ '.join(sorted(pair))}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(format_report(evaluate()))
