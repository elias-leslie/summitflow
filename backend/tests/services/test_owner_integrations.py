"""Core API and workers share extracted engines, not copied implementations."""

from pathlib import Path


def test_code_intelligence_is_shared_by_indexer_and_api():
    from code_intelligence import analyzers, graphify_tools
    from code_intelligence.precision import ranking

    from app.services import graphify_tools as legacy_graph
    from app.services.context_gatherer import _precision_ranking
    from app.services.explorer.types import files

    assert legacy_graph is graphify_tools
    assert _precision_ranking is ranking
    assert files.extract_symbols is analyzers.extract_symbols


def test_design_api_and_workers_share_owner_and_durable_root():
    from design_tools.services import design_asset_pipeline
    from design_tools.services.mockup_generator.analysis import screenshot, vision
    from design_tools.services.mockup_generator.storage_helpers import get_mockup_base_dir

    from app.api import design_assets
    from app.tasks.autonomous.exec_modules import design_critic, runtime_evaluator

    assert design_assets.generate_asset_image is design_asset_pipeline.generate_asset_image
    assert design_critic.analyze_screenshot_with_prompt is vision.analyze_screenshot_with_prompt
    assert runtime_evaluator.analyze_screenshot_with_prompt is vision.analyze_screenshot_with_prompt
    assert runtime_evaluator.capture_page_screenshot is screenshot.capture_page_screenshot
    assert get_mockup_base_dir() == Path(__file__).resolve().parents[3] / "data/design-studio/mockups"
