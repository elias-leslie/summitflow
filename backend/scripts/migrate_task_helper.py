#!/usr/bin/env python3
"""Task migration helper - Extract objectives and summaries using Gemini Flash.

Usage:
    # Extract objective and summary for a single task
    python migrate_task_helper.py --task task-abc123

    # Process all completed tasks (objective + summary only)
    python migrate_task_helper.py --completed

    # Process a pending task (with subtask proposals)
    python migrate_task_helper.py --task task-abc123 --with-subtasks

    # Dry run (show what would be extracted)
    python migrate_task_helper.py --task task-abc123 --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.agents.gemini import GeminiClient

from app.constants import DEFAULT_GEMINI_MODEL
from app.storage.subtasks import bulk_create_subtasks
from app.storage.tasks import get_task, update_task


def extract_objective_and_summary(
    title: str,
    description: str,
    gemini: GeminiClient,
) -> tuple[str, str]:
    """Use Gemini Flash to extract objective and create summary.

    Returns:
        Tuple of (objective, summary)
    """
    prompt = f"""Analyze this task and extract:
1. OBJECTIVE: A single sentence stating the measurable goal (what success looks like)
2. SUMMARY: 2-3 sentences of context/background (why this task exists, what problem it solves)

Task Title: {title}

Task Description:
{description}

Respond in this exact format:
OBJECTIVE: <single sentence objective>
SUMMARY: <2-3 sentence summary>

Rules:
- Objective should be measurable/verifiable
- Summary should NOT repeat the objective
- Summary should focus on context, background, motivation
- If description already has "## Objective" section, extract and refine it
- Keep both concise"""

    response = gemini.generate(prompt, temperature=0.3)
    content = response.content

    # Parse response
    objective = ""
    summary = ""

    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("OBJECTIVE:"):
            objective = line[len("OBJECTIVE:") :].strip()
        elif line.startswith("SUMMARY:"):
            summary = line[len("SUMMARY:") :].strip()

    # Handle multi-line summary (everything after SUMMARY: until end or next section)
    if "SUMMARY:" in content:
        summary_start = content.index("SUMMARY:") + len("SUMMARY:")
        summary = content[summary_start:].strip()

    return objective, summary


def propose_subtasks(
    title: str,
    description: str,
    objective: str,
    gemini: GeminiClient,
) -> list[dict[str, Any]]:
    """Use Gemini Flash to propose subtasks for a pending task.

    Returns:
        List of subtask dicts with keys: subtask_id, phase, description, steps
    """
    prompt = f"""Analyze this task and propose actionable subtasks.

Task Title: {title}
Objective: {objective}

Full Description:
{description}

Create subtasks that break this work into logical chunks. Each subtask should:
- Be completable independently
- Have clear verification criteria
- Map to a phase: research, database, backend, frontend, testing, verification

Respond with JSON array:
[
  {{
    "subtask_id": "1",
    "phase": "research|database|backend|frontend|testing|verification",
    "description": "What to do",
    "steps": ["Step 1", "Step 2", "Verification step"]
  }}
]

Rules:
- 3-8 subtasks typically (fewer for simple tasks, more for complex)
- Skip subtasks for trivial items
- Last step should always be verification
- Return empty array [] if task is too simple for subtasks"""

    response = gemini.generate(prompt, temperature=0.3)
    content = response.content

    # Extract JSON from response
    try:
        # Find JSON array in response
        start = content.find("[")
        end = content.rfind("]") + 1
        if start >= 0 and end > start:
            json_str = content[start:end]
            subtasks = json.loads(json_str)
            return subtasks
    except json.JSONDecodeError as e:
        print(f"  Warning: Could not parse subtasks JSON: {e}")

    return []


def process_task(
    task_id: str,
    gemini: GeminiClient,
    with_subtasks: bool = False,
    dry_run: bool = False,
) -> bool:
    """Process a single task.

    Returns:
        True if successful, False otherwise
    """
    task = get_task(task_id)
    if not task:
        print(f"Error: Task {task_id} not found")
        return False

    title = task["title"]
    description = task.get("description") or ""
    status = task["status"]
    existing_objective = task.get("objective")

    if not description:
        print(f"Skipping {task_id}: No description to process")
        return False

    if existing_objective:
        print(f"Skipping {task_id}: Already has objective")
        return False

    print(f"\n{'=' * 60}")
    print(f"Task: {task_id}")
    print(f"Title: {title}")
    print(f"Status: {status}")
    print(f"Description length: {len(description)} chars")
    print(f"{'=' * 60}")

    # Extract objective and summary
    print("\nExtracting objective and summary...")
    objective, summary = extract_objective_and_summary(title, description, gemini)

    print(f"\nOBJECTIVE: {objective}")
    print(f"\nSUMMARY: {summary}")

    # Propose subtasks if requested and task is pending
    subtasks = []
    if with_subtasks and status in ("pending", "running"):
        print("\nProposing subtasks...")
        subtasks = propose_subtasks(title, description, objective, gemini)

        if subtasks:
            print(f"\nProposed {len(subtasks)} subtasks:")
            for st in subtasks:
                print(f"  {st['subtask_id']}. [{st['phase']}] {st['description']}")
                for step in st.get("steps", []):
                    print(f"      - {step}")
        else:
            print("  (No subtasks proposed - task is simple)")

    if dry_run:
        print("\n[DRY RUN - No changes applied]")
        return True

    # Apply updates
    print("\nApplying updates...")

    # Update task with objective and summary
    update_task(
        task_id,
        objective=objective,
        description=summary,
    )
    print("  Updated objective and description")

    # Create subtasks if any
    if subtasks:
        # Format for bulk_create_subtasks
        formatted_subtasks = []
        for i, st in enumerate(subtasks):
            formatted_subtasks.append(
                {
                    "subtask_id": st["subtask_id"],
                    "phase": st["phase"],
                    "description": st["description"],
                    "steps": st.get("steps", []),
                    "display_order": i,
                    "passes": False,
                }
            )

        bulk_create_subtasks(task_id, formatted_subtasks)
        print(f"  Created {len(subtasks)} subtasks")

    print("  Done!")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Task migration helper")
    parser.add_argument("--task", help="Task ID to process")
    parser.add_argument("--completed", action="store_true", help="Process all completed tasks")
    parser.add_argument("--with-subtasks", action="store_true", help="Also propose subtasks")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")

    args = parser.parse_args()

    if not args.task and not args.completed:
        parser.print_help()
        sys.exit(1)

    # Initialize Gemini client
    gemini = GeminiClient(model=DEFAULT_GEMINI_MODEL)
    if not gemini.is_available():
        print("Error: Gemini credentials not available")
        print("Set GOOGLE_API_KEY or GEMINI_API_KEY environment variable")
        sys.exit(1)

    print(f"Using model: {gemini.get_model_name()}")

    if args.task:
        success = process_task(
            args.task,
            gemini,
            with_subtasks=args.with_subtasks,
            dry_run=args.dry_run,
        )
        sys.exit(0 if success else 1)

    # Process completed tasks would go here
    if args.completed:
        print("Processing completed tasks not yet implemented")
        print("Use --task <id> for now")
        sys.exit(1)


if __name__ == "__main__":
    main()
