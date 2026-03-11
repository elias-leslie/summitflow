"""Tests for the design_standards storage module."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from app.storage import design_standards
from app.storage.connection import get_connection


@pytest.fixture
def conn() -> Generator[Any]:
    """Database connection fixture."""
    with get_connection() as connection:
        yield connection


@pytest.fixture
def cleanup_project(conn: Any) -> Generator[str]:
    """Fixture to clean up test project data after tests."""
    project_id = "test-design-project"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url)
            VALUES (%s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (project_id, "Test Design Project", "http://localhost"),
        )
        conn.commit()

    yield project_id

    with conn.cursor() as cur:
        cur.execute("DELETE FROM design_standards WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()


@pytest.fixture
def base_standard(conn: Any) -> Generator[dict[str, Any]]:
    """Create a base standard for testing."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM design_standards WHERE is_base = TRUE AND project_id IS NULL")
        conn.commit()

    standard = design_standards.create_standard(
        name="Base UI/UX Standard",
        description="Default design rules",
        is_base=True,
    )

    yield standard

    with conn.cursor() as cur:
        cur.execute("DELETE FROM design_standards WHERE id = %s", (standard["id"],))
        conn.commit()


class TestDesignStandardsCRUD:
    """Tests for standard CRUD operations."""

    def test_create_base_standard(self, conn: Any) -> None:
        """Create a base standard with no project."""
        with conn.cursor() as cur:
            cur.execute("DELETE FROM design_standards WHERE is_base = TRUE AND project_id IS NULL")
            conn.commit()

        try:
            result = design_standards.create_standard(
                name="Test Base",
                description="Test base standard",
                is_base=True,
            )

            assert result["name"] == "Test Base"
            assert result["is_base"]
            assert result["project_id"] is None
        finally:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM design_standards WHERE name = %s AND is_base = TRUE",
                    ("Test Base",),
                )
                conn.commit()

    def test_create_project_standard(self, cleanup_project: str) -> None:
        """Create a project-specific standard."""
        project_id = cleanup_project
        result = design_standards.create_standard(
            name="Project Standard",
            description="Custom rules for project",
            project_id=project_id,
        )

        assert result["name"] == "Project Standard"
        assert result["project_id"] == project_id
        assert not result["is_base"]

    def test_get_base_standard(self, base_standard: dict[str, Any]) -> None:
        """Get the base standard."""
        result = design_standards.get_base_standard()

        assert result is not None
        assert result["id"] == base_standard["id"]
        assert result["is_base"]

    def test_get_project_standard(self, cleanup_project: str) -> None:
        """Get project-specific standard."""
        project_id = cleanup_project
        created = design_standards.create_standard(
            name="Custom",
            project_id=project_id,
        )

        result = design_standards.get_project_standard(project_id)
        assert result is not None
        assert result["id"] == created["id"]

    def test_get_project_standard_by_name(self, cleanup_project: str) -> None:
        """Get project standard by name."""
        project_id = cleanup_project
        design_standards.create_standard(name="First", project_id=project_id)
        second = design_standards.create_standard(name="Second", project_id=project_id)

        result = design_standards.get_project_standard(project_id, name="Second")
        assert result is not None
        assert result["id"] == second["id"]

    def test_get_standard_by_id(self, base_standard: dict[str, Any]) -> None:
        """Get standard by ID."""
        result = design_standards.get_standard_by_id(base_standard["id"])

        assert result is not None
        assert result["name"] == base_standard["name"]

    def test_list_standards(self, cleanup_project: str, base_standard: dict[str, Any]) -> None:
        """List standards for a project."""
        project_id = cleanup_project
        design_standards.create_standard(name="Project Std", project_id=project_id)

        result = design_standards.list_standards(project_id)

        assert len(result) >= 2
        names = [s["name"] for s in result]
        assert "Base UI/UX Standard" in names
        assert "Project Std" in names

    def test_list_base_standards_only(self, base_standard: dict[str, Any]) -> None:
        """List only base standards when no project specified."""
        result = design_standards.list_standards()

        assert len(result) >= 1
        assert all(s["is_base"] for s in result)

    def test_update_standard(self, cleanup_project: str) -> None:
        """Update standard fields."""
        project_id = cleanup_project
        created = design_standards.create_standard(
            name="Original",
            description="Original desc",
            project_id=project_id,
        )

        result = design_standards.update_standard(
            created["id"],
            name="Updated",
            description="Updated desc",
        )

        assert result is not None
        assert result["name"] == "Updated"
        assert result["description"] == "Updated desc"

    def test_delete_standard(self, cleanup_project: str) -> None:
        """Delete a standard."""
        project_id = cleanup_project
        created = design_standards.create_standard(
            name="To Delete",
            project_id=project_id,
        )

        deleted = design_standards.delete_standard(created["id"])
        assert deleted

        result = design_standards.get_standard_by_id(created["id"])
        assert result is None


class TestDesignStandardsInheritance:
    """Tests for standard inheritance."""

    def test_inherit_from_base(self, cleanup_project: str, base_standard: dict[str, Any]) -> None:
        """Create project standard inheriting from base."""
        project_id = cleanup_project

        result = design_standards.inherit_from_base(project_id)

        assert result["project_id"] == project_id
        assert result["base_standard_id"] == base_standard["id"]
        assert not result["is_base"]

    def test_inherit_from_base_no_base_exists(self, cleanup_project: str, conn: Any) -> None:
        """Error when no base standard exists."""
        with conn.cursor() as cur:
            cur.execute("DELETE FROM design_standards WHERE is_base = TRUE")
            conn.commit()

        with pytest.raises(ValueError, match="No base standard"):
            design_standards.inherit_from_base(cleanup_project)


class TestDesignRulesCRUD:
    """Tests for design rule operations."""

    @pytest.fixture
    def standard(self, cleanup_project: str) -> dict[str, Any]:
        """Create a test standard."""
        return design_standards.create_standard(
            name="Test Rules Standard",
            project_id=cleanup_project,
        )

    def test_create_rule(self, standard: dict[str, Any]) -> None:
        """Create a design rule."""
        result = design_standards.create_rule(
            standard_id=standard["id"],
            category="typography",
            rule_id="typo-001",
            name="Heading Size",
            requirements={"font_size": {"min": 16, "max": 48}},
        )

        assert result["rule_id"] == "typo-001"
        assert result["category"] == "typography"
        assert result["requirements"]["font_size"]["min"] == 16

    def test_get_rule(self, standard: dict[str, Any]) -> None:
        """Get a specific rule."""
        design_standards.create_rule(
            standard_id=standard["id"],
            category="color",
            rule_id="color-001",
            name="Primary Color",
            requirements={"value": {"exact": "#00D9FF"}},
        )

        result = design_standards.get_rule(standard["id"], "color-001")
        assert result is not None
        assert result["name"] == "Primary Color"

    def test_list_rules(self, standard: dict[str, Any]) -> None:
        """List all rules for a standard."""
        design_standards.create_rule(standard["id"], "layout", "lay-001", "Grid", {})
        design_standards.create_rule(standard["id"], "typography", "typo-001", "Font", {})

        result = design_standards.list_rules(standard["id"])
        assert len(result) == 2

    def test_list_rules_by_category_filter(self, standard: dict[str, Any]) -> None:
        """List rules filtered by category."""
        design_standards.create_rule(standard["id"], "layout", "lay-001", "Grid", {})
        design_standards.create_rule(standard["id"], "typography", "typo-001", "Font", {})

        result = design_standards.list_rules(standard["id"], category="typography")
        assert len(result) == 1
        assert result[0]["category"] == "typography"

    def test_list_rules_by_category_grouped(self, standard: dict[str, Any]) -> None:
        """List rules grouped by category."""
        design_standards.create_rule(standard["id"], "layout", "lay-001", "Grid", {})
        design_standards.create_rule(standard["id"], "layout", "lay-002", "Spacing", {})
        design_standards.create_rule(standard["id"], "typography", "typo-001", "Font", {})

        result = design_standards.list_rules_by_category(standard["id"])
        assert "layout" in result
        assert "typography" in result
        assert len(result["layout"]) == 2
        assert len(result["typography"]) == 1

    def test_upsert_rule_create(self, standard: dict[str, Any]) -> None:
        """Upsert creates new rule."""
        result = design_standards.upsert_rule(
            standard["id"], "component", "comp-001", "Button", {"padding": {"min": 8}}
        )

        assert result["rule_id"] == "comp-001"

    def test_upsert_rule_update(self, standard: dict[str, Any]) -> None:
        """Upsert updates existing rule."""
        design_standards.create_rule(
            standard["id"], "component", "comp-001", "Button", {"padding": {"min": 8}}
        )

        result = design_standards.upsert_rule(
            standard["id"], "component", "comp-001", "Button Updated", {"padding": {"min": 12}}
        )

        assert result["name"] == "Button Updated"
        assert result["requirements"]["padding"]["min"] == 12

    def test_delete_rule(self, standard: dict[str, Any]) -> None:
        """Delete a rule."""
        design_standards.create_rule(standard["id"], "layout", "lay-delete", "Delete Me", {})

        deleted = design_standards.delete_rule(standard["id"], "lay-delete")
        assert deleted

        result = design_standards.get_rule(standard["id"], "lay-delete")
        assert result is None


class TestEffectiveRules:
    """Tests for effective rules merging."""

    def test_effective_rules_base_only(self, base_standard: dict[str, Any], cleanup_project: str) -> None:
        """Effective rules from base when no project override."""
        design_standards.create_rule(
            base_standard["id"], "typography", "typo-001", "Base Font", {"size": {"exact": 16}}
        )

        result = design_standards.get_effective_rules(cleanup_project)
        assert len(result) == 1
        assert result[0]["source"] == "base"

    def test_effective_rules_project_override(self, base_standard: dict[str, Any], cleanup_project: str) -> None:
        """Project rule overrides base rule with same ID."""
        design_standards.create_rule(
            base_standard["id"], "typography", "typo-001", "Base Font", {"size": {"exact": 16}}
        )

        project_std = design_standards.create_standard(name="Project", project_id=cleanup_project)
        design_standards.create_rule(
            project_std["id"], "typography", "typo-001", "Project Font", {"size": {"exact": 14}}
        )

        result = design_standards.get_effective_rules(cleanup_project)
        assert len(result) == 1
        assert result[0]["source"] == "project"
        assert result[0]["name"] == "Project Font"

    def test_effective_rules_merged(self, base_standard: dict[str, Any], cleanup_project: str) -> None:
        """Base and project rules merge when different IDs."""
        design_standards.create_rule(base_standard["id"], "typography", "typo-001", "Base Rule", {})

        project_std = design_standards.create_standard(name="Project", project_id=cleanup_project)
        design_standards.create_rule(
            project_std["id"], "typography", "typo-002", "Project Rule", {}
        )

        result = design_standards.get_effective_rules(cleanup_project)
        assert len(result) == 2

        rule_ids = {r["rule_id"] for r in result}
        assert rule_ids == {"typo-001", "typo-002"}


class TestValidation:
    """Tests for rule validation."""

    @pytest.fixture
    def standard_with_rules(self, cleanup_project: str) -> dict[str, Any]:
        """Standard with validation rules."""
        std = design_standards.create_standard(
            name="Validation Test",
            project_id=cleanup_project,
        )

        design_standards.create_rule(
            std["id"],
            "typography",
            "typo-001",
            "Font Size",
            {"font_size": {"min": 12, "max": 48, "severity": "error"}},
        )
        design_standards.create_rule(
            std["id"],
            "color",
            "color-001",
            "Primary Color",
            {"primary_color": {"exact": "#00D9FF", "severity": "warning"}},
        )
        design_standards.create_rule(
            std["id"],
            "layout",
            "layout-001",
            "Allowed Layouts",
            {"layout_type": {"allowed": ["grid", "flex"], "severity": "error"}},
        )

        return std

    def test_validate_no_violations(self, cleanup_project: str, standard_with_rules: dict[str, Any]) -> None:
        """No violations when data matches rules."""
        result = design_standards.validate_against_rules(
            cleanup_project,
            {"font_size": 16, "primary_color": "#00D9FF", "layout_type": "grid"},
        )
        assert len(result) == 0

    def test_validate_range_violation(self, cleanup_project: str, standard_with_rules: dict[str, Any]) -> None:
        """Detect range violation."""
        result = design_standards.validate_against_rules(
            cleanup_project,
            {"font_size": 8},  # Below min of 12
        )

        assert len(result) == 1
        assert result[0]["rule_id"] == "typo-001"
        assert result[0]["severity"] == "error"

    def test_validate_exact_violation(self, cleanup_project: str, standard_with_rules: dict[str, Any]) -> None:
        """Detect exact match violation."""
        result = design_standards.validate_against_rules(
            cleanup_project,
            {"primary_color": "#FF0000"},  # Wrong color
        )

        assert len(result) == 1
        assert result[0]["rule_id"] == "color-001"
        assert result[0]["expected"] == "#00D9FF"
        assert result[0]["actual"] == "#FF0000"

    def test_validate_allowed_violation(self, cleanup_project: str, standard_with_rules: dict[str, Any]) -> None:
        """Detect allowed values violation."""
        result = design_standards.validate_against_rules(
            cleanup_project,
            {"layout_type": "table"},  # Not in allowed list
        )

        assert len(result) == 1
        assert result[0]["rule_id"] == "layout-001"
        assert "table" in result[0]["actual"]

    def test_validate_by_category(self, cleanup_project: str, standard_with_rules: dict[str, Any]) -> None:
        """Validate against specific category."""
        result = design_standards.validate_against_rules(
            cleanup_project,
            {"font_size": 8, "primary_color": "#FF0000"},
            category="typography",
        )

        # Should only check typography rules
        assert len(result) == 1
        assert result[0]["category"] == "typography"

    def test_validate_missing_properties_ignored(self, cleanup_project: str, standard_with_rules: dict[str, Any]) -> None:
        """Missing properties don't cause violations."""
        result = design_standards.validate_against_rules(
            cleanup_project,
            {"other_property": "value"},
        )
        assert len(result) == 0
