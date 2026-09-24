"""Read-only help-routing probes for opaque extension argv."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ST = ROOT / "backend/.venv/bin/st"
OWNER = Path("/srv/workspaces/projects/agent-hub/backend/.venv/bin/agent-hub-st")
NERI_OWNER = Path("/srv/workspaces/projects/neri/backend/.venv/bin/neri-st")
CASES = (
    ("st_option_value_equals_command", ST, ("feedback", "--id", "resolve", "--help")),
    ("owner_option_value_equals_command", OWNER, ("feedback", "--id", "resolve", "--help")),
    ("st_positional_id_equals_command", ST, ("feedback", "get", "resolve", "--help")),
    ("owner_positional_id_equals_command", OWNER, ("feedback", "get", "resolve", "--help")),
    ("st_unknown_prefix_then_command", ST, ("feedback", "bogus", "resolve", "--help")),
    ("owner_unknown_prefix_then_command", OWNER, ("feedback", "bogus", "resolve", "--help")),
    ("st_models_value_equals_command", ST, ("models", "--id", "list", "--help")),
    ("owner_models_value_equals_command", OWNER, ("models", "--id", "list", "--help")),
    ("st_models_value_before_command", ST, ("models", "--id", "foo", "list", "--help")),
    ("owner_models_value_before_command", OWNER, ("models", "--id", "foo", "list", "--help")),
    ("st_models_boolean_before_command", ST, ("models", "--free", "list", "--help")),
    ("owner_models_boolean_before_command", OWNER, ("models", "--free", "list", "--help")),
    ("st_models_equals_value_before_command", ST, ("models", "--id=foo", "list", "--help")),
    ("owner_models_equals_value_before_command", OWNER, ("models", "--id=foo", "list", "--help")),
    ("st_models_value_and_same_named_command", ST, ("models", "--id", "list", "list", "--help")),
    ("owner_models_value_and_same_named_command", OWNER, ("models", "--id", "list", "list", "--help")),
    ("st_models_missing_value", ST, ("models", "--id", "--help")),
    ("owner_models_missing_value", OWNER, ("models", "--id", "--help")),
    ("st_models_unknown_option_before_command", ST, ("models", "--unknown", "list", "--help")),
    ("owner_models_unknown_option_before_command", OWNER, ("models", "--unknown", "list", "--help")),
    ("st_neri_unknown_prefix_before_leaf", ST, ("neri", "research", "bogus", "hypotheses", "--help")),
    ("owner_neri_unknown_prefix_before_leaf", NERI_OWNER, ("research", "bogus", "hypotheses", "--help")),
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("label", choices=("before", "after"))
    label = parser.parse_args().label
    rows = []
    for name, executable, arguments in CASES:
        result = subprocess.run(
            [str(executable), *arguments],
            cwd="/tmp",
            capture_output=True,
            timeout=20,
        )
        rows.append(
            {
                "name": name,
                "argv": [str(executable), *arguments],
                "exit_code": result.returncode,
                "stdout": result.stdout.decode("utf-8", "replace"),
                "stderr": result.stderr.decode("utf-8", "replace"),
                "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
            }
        )
    destination = Path(__file__).resolve().parent / f"help-route-probes-{label}.json"
    destination.write_text(
        json.dumps({"captured_utc": datetime.now(timezone.utc).isoformat(), "results": rows}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(destination)
    for row in rows:
        first_line = (row["stdout"] or row["stderr"]).strip().splitlines()[0]
        print(row["name"], row["exit_code"], first_line)


if __name__ == "__main__":
    main()
