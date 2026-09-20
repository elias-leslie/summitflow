"""Compatibility names for explicitly installed, versioned public libraries.

This is not extension discovery: every caller supplies a fixed module name from
an exact package dependency. Aliases keep API/worker callers on one engine.
"""

from importlib import import_module
from sys import modules


def expose_module(local_name: str, public_name: str, children: tuple[str, ...] = ()) -> None:
    implementation = import_module(public_name)
    for child in children:
        modules[f"{local_name}.{child}"] = import_module(f"{public_name}.{child}")
    modules[local_name] = implementation
