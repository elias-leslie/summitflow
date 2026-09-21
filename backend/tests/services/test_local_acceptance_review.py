"""Independent review of mandatory acceptance completion semantics."""

from app.services.task_acceptance import completion_gates


def test_implementation_task_cannot_complete_without_local_acceptance() -> None:
    task = {
        "context": {
            "files_to_modify": ["backend/app/example.py"],
            "completion_requirements": {
                "deployment": False,
                "live_checks": [],
            },
        },
        "verification_result": {},
    }

    gates = completion_gates(task)

    assert [gate["gate"] for gate in gates] == ["acceptance"]
