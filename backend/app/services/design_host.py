"""SummitFlow infrastructure bindings for the public Design Tools engine."""

from functools import cache
from importlib import import_module
from pathlib import Path


async def _run_browser_command(command: list[str], timeout: float):
    from ..utils import safe_subprocess

    return await safe_subprocess.run_async(
        command, capture_output=True, text=True, timeout=timeout, check=False,
    )


@cache
def configure_design() -> None:
    from design_tools.host import HostBindings, configure

    from ..constants import AGENT_IMAGE_GEN
    from ..logging_config import get_logger

    # Storage imports are deferred because storage.__init__ exposes design assets.
    # Callbacks resolve the canonical host each time (including test overrides).
    configure(HostBindings(
        get_connection=lambda: import_module("app.storage.connection").get_connection(),
        get_cursor=lambda: import_module("app.storage.connection").get_cursor(),
        static_sql=lambda statement: import_module("app.storage._sql").static_sql(statement),
        join_static_sql=lambda fragments, separator: import_module("app.storage._sql").join_static_sql(fragments, separator),
        get_explorer_entry=lambda entry_id: import_module("app.storage.explorer_entries").get_entry_by_id(entry_id),
        get_sync_client=lambda: import_module("app.services.agent_hub_client").get_sync_client(),
        get_agent=lambda slug: import_module("app.services.agent_hub_client").get_agent(slug),
        run_browser_command=_run_browser_command,
        logger_factory=get_logger,
        image_agent_slug=AGENT_IMAGE_GEN,
        mockup_base_dir=Path(__file__).resolve().parents[3] / "data" / "design-studio" / "mockups",
    ))
