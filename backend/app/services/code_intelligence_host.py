"""Canonical SummitFlow indexes and process policy for Code Intelligence."""

from functools import cache
from importlib import import_module


@cache
def configure_code_intelligence() -> None:
    from code_intelligence import graphify_tools
    from code_intelligence.precision import ranking, sections

    graphify_tools.configure_process_runner(
        lambda *args, **kwargs: import_module("app.utils.safe_subprocess").run(*args, **kwargs),
    )
    ranking.configure_search_symbols(
        lambda *args, **kwargs: import_module("app.storage.explorer").search_symbols(*args, **kwargs),
    )
    sections.configure_section_hosts(
        get_project_root=lambda project: import_module("app.services.explorer").get_project_root(project),
        get_symbol=lambda project, symbol: import_module("app.storage.explorer").get_symbol(project, symbol),
        list_related_entries_for_file=lambda project, path: import_module("app.storage.explorer").list_related_entries_for_file(project, path),
    )
