"""Prompt builder for the completion gate LLM call."""

from __future__ import annotations

from ....services.task_harness import summarize_execution_contract


def _contract_section(execution_contract: object) -> str:
    """Build the EXECUTION CONTRACT section, or empty string if not needed."""
    contract_summary = summarize_execution_contract(execution_contract)
    needs_section = (
        contract_summary["target_url_count"] > 0
        or contract_summary["user_flow_count"] > 0
        or contract_summary["api_check_count"] > 0
        or contract_summary["negative_case_count"] > 0
        or contract_summary["has_design_criteria"]
    )
    if not needs_section:
        return ""
    return (
        "\nEXECUTION CONTRACT:\n"
        f"  mode={contract_summary['mode']}\n"
        f"  target_urls={contract_summary['target_url_count']}\n"
        f"  user_flows={contract_summary['user_flow_count']}\n"
        f"  api_checks={contract_summary['api_check_count']}\n"
        f"  negative_cases={contract_summary['negative_case_count']}\n"
        f"  design_critic={'yes' if contract_summary['has_design_criteria'] else 'no'}\n"
    )


def build_completion_gate_prompt(
    description: str,
    spirit_anti: str,
    done_when: list[str],
    modified_files: list[str],
    file_contents: str,
    diff_summary: str,
    execution_contract: object,
) -> str:
    """Build the completion gate verification prompt."""
    done_items = "\n".join(f"  {i+1}. {item}" for i, item in enumerate(done_when))
    anti_section = f"\nSPIRIT_ANTI (must NOT happen):\n{spirit_anti}" if spirit_anti else ""
    files_list = "\n".join(f"  - {f}" for f in modified_files) if modified_files else "  (none)"
    contract_section = _contract_section(execution_contract)
    return (
        "You are performing a completion gate check. Verify that the task's done_when criteria "
        "have been met by examining the actual code changes.\n\n"
        f"TASK DESCRIPTION: {description}{anti_section}\n\n"
        f"DONE_WHEN CRITERIA:\n{done_items}\n\n"
        f"{contract_section}\n"
        f"MODIFIED FILES:\n{files_list}\n\n"
        f"CHANGES SUMMARY:\n{diff_summary}\n\n"
        f"FILE CONTENTS:\n{file_contents}\n\n"
        "For each done_when criterion, respond with:\n"
        "CRITERION_N: MET|NOT_MET|PARTIAL - file:line evidence or explanation\n\n"
        "Then:\n"
        "CONFIDENCE: 0-100\n"
        "GAPS: comma-separated list of unmet items, or NONE\n"
        "ANTI_CHECK: any spirit_anti violations found, or CLEAR\n"
    )
