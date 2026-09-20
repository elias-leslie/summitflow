"""Passive, strict metadata for the trusted ST executable contract."""

from __future__ import annotations

from dataclasses import fields
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .lib.usage import UsageSpec

CONTRACT_VERSION = 1
Effect = Literal["read-local", "write-local", "read-remote", "write-remote", "network", "process", "desktop", "credentials"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError("expected a nonempty project-relative path without parent traversal")
    return value


class DispatchGrant(StrictModel):
    """Operator-reviewed dispatch permission, separate from owner effect claims."""

    enabled: bool
    effects: list[Effect]


class ExtensionBinding(StrictModel):
    id: str = Field(min_length=1)
    owner: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    namespace: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    manifest: str
    executable: str
    grant: DispatchGrant
    arguments: list[str] = Field(default_factory=list)
    environment: list[str] = Field(default_factory=list)
    presentation: Literal["native", "web-details"] = "native"
    policy_adapter: Literal["browser"] | None = None

    @field_validator("manifest", "executable")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return relative_path(value)

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, values: list[str]) -> list[str]:
        import re

        if any(not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in {
            "PYTHONPATH", "PYTHONHOME", "ST_EXTENSION_CONTEXT", "LD_PRELOAD", "LD_LIBRARY_PATH",
        } for key in values):
            raise ValueError("invalid or interpreter-injection environment key")
        return values


class ExtensionManifest(StrictModel):
    id: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    namespace: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][a-zA-Z0-9.-]+)?$")
    st_contract_versions: list[int] = Field(min_length=1)
    summary: str = Field(min_length=1)
    effects: list[Effect]
    help: dict[str, str]
    usage: list[dict[str, object]]

    @model_validator(mode="after")
    def validate_guidance(self) -> ExtensionManifest:
        if "" not in self.help or not self.help[""]:
            raise ValueError("root help is required")
        allowed = {field.name for field in fields(UsageSpec)}
        sequences = {"precautions", "examples", "task_types", "agent_slugs", "consumer_profiles"}
        surfaces: set[str] = set()
        for spec in self.usage:
            if set(spec) - allowed:
                raise ValueError("unknown UsageSpec fields")
            surface = spec.get("surface")
            prefix = f"st.{self.namespace}"
            if not isinstance(surface, str) or not (surface == prefix or surface.startswith(prefix + ".")):
                raise ValueError("usage surface must belong to the registered namespace")
            if surface in surfaces:
                raise ValueError("duplicate usage surface")
            surfaces.add(surface)
            for key, value in spec.items():
                if key in sequences:
                    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                        raise ValueError("usage lists must contain strings")
                elif not isinstance(value, str):
                    raise ValueError("usage scalar must be a string")
            command = spec.get("cmd", "")
            if command and not (command == f"st {self.namespace}" or str(command).startswith(f"st {self.namespace} ")):
                raise ValueError("usage command must belong to the registered namespace")
            if spec.get("tier", "reference") not in {"mandate", "guardrail", "reference"}:
                raise ValueError("invalid usage tier")
        return self

    def usage_specs(self) -> list[UsageSpec]:
        return [UsageSpec(**{key: tuple(value) if isinstance(value, list) else value for key, value in row.items()}) for row in self.usage]  # type: ignore[arg-type]
