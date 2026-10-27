"""Core API and workers share extracted engines, not copied implementations."""

from pathlib import Path


def test_code_intelligence_graph_engine_is_shared_with_the_api():
    from code_intelligence import graphify_tools

    from app.services import graphify_tools as legacy_graph

    assert legacy_graph is graphify_tools


def test_design_api_and_workers_share_owner_and_durable_root():
    from design_tools.services.mockup_generator import revisions
    from design_tools.services.mockup_generator.storage_helpers import get_mockup_base_dir

    from app.api import mockups_generation

    assert mockups_generation.rerun_mockup is revisions.rerun_mockup
    assert get_mockup_base_dir() == Path(__file__).resolve().parents[3] / "data/design-studio/mockups"
