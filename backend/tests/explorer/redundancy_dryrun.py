"""Real-world dry run: run the tuned detector over the LIVE explorer_symbols index.

Read-only. Creates NO tasks. This is the Phase-0 gate: review what the detector
*would* flag on real data before any pipeline wiring.

Candidates are narrowed with an inverted name-token index (the cheap stand-in for
the production ``search_symbols`` narrowing step) so we avoid the O(n^2) blowup,
then scored with the pure detector.

Run from backend/:  .venv/bin/python -m tests.explorer.redundancy_dryrun [project_id]
"""

from __future__ import annotations

import sys
from collections import defaultdict
from typing import Any

from app.services.explorer.redundancy import (
    DEFAULT_CONFIG,
    SimilarityConfig,
    cluster_duplicates,
    is_eligible,
    tokenize_name,
)
from app.storage.connection import get_cursor


def _load_symbols(project_id: str) -> list[dict[str, Any]]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT file_path, symbol_id, qualified_name, name, kind,
                   signature, language, summary, keywords
            FROM explorer_symbols
            WHERE project_id = %s
            """,
            (project_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "file_path": r[0],
            "symbol_id": r[1],
            "qualified_name": r[2],
            "name": r[3],
            "kind": r[4],
            "signature": r[5],
            "language": r[6],
            "summary": r[7],
            "keywords": r[8] or [],
        }
        for r in rows
    ]


def _narrow_candidate_indices(
    symbols: list[dict[str, Any]], config: SimilarityConfig
) -> list[int]:
    return [i for i, s in enumerate(symbols) if is_eligible(s, config)]


def run(project_id: str, config: SimilarityConfig = DEFAULT_CONFIG) -> None:
    symbols = _load_symbols(project_id)
    eligible = _narrow_candidate_indices(symbols, config)

    # Inverted index: name-token -> eligible symbol indices that contain it.
    token_index: dict[str, list[int]] = defaultdict(list)
    for i in eligible:
        for tok in tokenize_name(str(symbols[i].get("name") or "")):
            token_index[tok].append(i)

    # Candidate set = eligible symbols that share >=1 name token with another.
    candidate_set: set[int] = set()
    for members in token_index.values():
        if len(members) > 1:
            candidate_set.update(members)
    candidates = [symbols[i] for i in sorted(candidate_set)]

    clusters = cluster_duplicates(candidates, config)

    print(f"project           : {project_id}")
    print(f"total symbols     : {len(symbols)}")
    print(f"eligible symbols  : {len(eligible)}")
    print(f"token candidates  : {len(candidates)}")
    print(f"clusters flagged  : {len(clusters)}")
    print("=" * 72)
    for n, c in enumerate(clusters, 1):
        print(f"[{n}] score={c.score:.3f}  ({c.reason})")
        for m in c.members:
            print(f"      {m['kind']:8} {m['name']}  ->  {m['file_path']}")
        print()


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "summitflow")
