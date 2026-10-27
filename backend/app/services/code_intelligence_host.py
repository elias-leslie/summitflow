"""SummitFlow process policy for the public Code Intelligence engine."""

from functools import cache
from importlib import import_module


@cache
def configure_code_intelligence() -> None:
    from code_intelligence import graphify_tools

    graphify_tools.configure_process_runner(
        lambda *args, **kwargs: import_module("app.utils.safe_subprocess").run(*args, **kwargs),
    )
