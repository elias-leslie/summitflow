"""Design Ops commands for UI mockups and production assets.

Use this when... matrix:

    Goal                                              | Command
    --------------------------------------------------+-----------------------
    Store hand-authored HTML as a new mockup          | st design ui create
    Add a hand-authored revision to an existing one   | st design ui attach
    Have an AI agent inspect a live URL and design    | st design ui analyze
    Have an AI agent regenerate an existing mockup    | st design ui rerun
    Import self/user-generated image asset            | st design asset import
    Generate a sprite / portrait / game art asset     | st design asset generate
    Critique a sprite / tile / game art image         | st design asset critique
    Export sprite-sheet frames                        | st design asset export

`ui create` and `ui attach` are the right tools when an agent (Claude Code,
Codex CLI, etc.) wants to hand-author the HTML itself and just have it stored.
They never call an AI image / mockup agent.

`asset generate` is for game / marketing artwork only — even with
`--workflow ui` it routes to image generation (Cloudflare flux / Leonardo) and
will silently prepend "Create a polished marketing mockup for a game production
pipeline." to the prompt. Don't use it for UI screen mockups.

Design source gate: before making a visual artifact, ask the project lead
whether the current agent/user should create it and import it manually, or
whether Agent Hub's image / UI design agents should generate it.

Storage gate: Asset Studio and UI Design artifacts are important project
state. They must be stored through SummitFlow's durable Design Ops storage,
never in `/tmp` or another temp-only location.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..config import get_config
from ..lib.usage import usage
from ..output import handle_api_error, output_error, output_json, require_explicit_project
from ._complete_http import call_complete

app = typer.Typer(
    help=(
        "Design Ops: UI mockups (hand-authored or AI) and game/marketing assets. "
        "Run `st design` for the full subcommand matrix."
    )
)
asset_app = typer.Typer(
    help=(
        "Asset Studio: import self/user-generated images, generate game / "
        "marketing artwork via Agent Hub image agents, and export sprite "
        "sheets. Ask the source gate first: manual/current-agent or Agent Hub? "
        "Storage must be durable; never /tmp."
    )
)
ui_app = typer.Typer(
    help=(
        "UI Design mockups. `create` / `attach` store hand-authored HTML. "
        "`analyze` / `rerun` invoke the AI ui-mockup-designer agent."
    )
)

# ---------------------------------------------------------------------------
# Annotated type aliases — keeps command signatures readable and concise
# ---------------------------------------------------------------------------
_AssetType = Annotated[
    str,
    typer.Option(
        "--type", "-t",
        help="Asset type (sprite, sprite_sheet, portrait, environment, icon, illustration, ui_texture, marketing_mockup, tile_set, concept_art)",
    ),
]
_Workflow = Annotated[
    str,
    typer.Option("--workflow", "-w", help="Workflow lane: concept, production, marketing, ui"),
]
_Background = Annotated[
    str,
    typer.Option("--background", help="Background mode: transparent, solid, scene"),
]
_VariantCount = Annotated[
    int,
    typer.Option("--variants", min=1, max=4, help="Number of variants to generate"),
]
DEFAULT_ASSET_CRITIQUE_AGENT = "game-art-critic"
GEMMA_ASSET_CRITIQUE_AGENT = "game-art-critic-gemma"
DEFAULT_ASSET_CRITIQUE_MODELS = (
    "xai/grok-4.20-0309-reasoning",
    "gemini-3.1-flash-lite",
)


@app.callback(invoke_without_command=True)
@usage(
    surface="st.design",
    cmd="st design ui create | st design asset import | st design asset generate",
    when="creating UI mockups, game art, sprites, icons, tile sets, portraits, or marketing visuals",
    precautions=(
        "before generating visual work, ask the project lead whether the current agent/user should create it manually or Agent Hub design/image agents should generate it",
        "use st design ui create/attach for hand-authored HTML UI mockups; never route UI screens through asset image generation",
        "use st design asset import for current-agent/user-generated PNG/JPEG/WebP/SVG assets so they still enter Asset Studio approval",
        "use st design asset critique for Agent Hub-routed visual/design critique before accepting production game assets",
        "use the calling agent's native image generator first, then st design asset import; use st design asset generate only as an explicit Agent Hub fallback when the caller has no native image generation",
        "Design Ops storage is durable project state; never configure Asset Studio or UI mockup storage under /tmp",
        "do not export or commit visual assets into the repo until approved in Design/Asset Studio",
    ),
    task_types=("design", "implementation"),
    tier="guardrail",
)
def design_default(ctx: typer.Context) -> None:
    """Design Ops command group."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


@asset_app.command("generate")
def generate_asset(
    name: Annotated[str, typer.Argument(help="Asset display name")],
    prompt: Annotated[str, typer.Argument(help="Creative brief for the generated asset")],
    description: Annotated[str | None, typer.Option("--description", "-d", help="Optional description stored with the asset")] = None,
    asset_type: _AssetType = "sprite",
    workflow: _Workflow = "concept",
    size: Annotated[str, typer.Option("--size", help="Target size in WIDTHxHEIGHT format")] = "1024x1024",
    agent_slug: Annotated[str | None, typer.Option("--agent", help="Agent Hub image agent slug")] = None,
    style_prompt: Annotated[str | None, typer.Option("--style", help="Style direction for the image prompt")] = None,
    negative_prompt: Annotated[str | None, typer.Option("--negative", help="Negative prompt guidance")] = None,
    background: _Background = "transparent",
    variant_count: _VariantCount = 1,
    tags: Annotated[str | None, typer.Option("--tags", help="Comma-separated tags")] = None,
    sheet_columns: Annotated[int | None, typer.Option("--sheet-columns", help="Sprite sheet columns")] = None,
    sheet_rows: Annotated[int | None, typer.Option("--sheet-rows", help="Sprite sheet rows")] = None,
    frame_width: Annotated[int | None, typer.Option("--frame-width", help="Sprite sheet frame width")] = None,
    frame_height: Annotated[int | None, typer.Option("--frame-height", help="Sprite sheet frame height")] = None,
    animation_labels: Annotated[str | None, typer.Option("--animations", help="Comma-separated animation row labels")] = None,
    source_asset_id: Annotated[int | None, typer.Option("--source-asset-id", help="Source asset DB id for variant derivation")] = None,
    reference_image_path: Annotated[str | None, typer.Option("--reference-image-path", help="Path to a PNG/JPEG/WebP reference image for sprite consistency")] = None,
    reference_mime_type: Annotated[str | None, typer.Option("--reference-mime-type", help="Reference image MIME type override")] = None,
    agent_hub_fallback: Annotated[
        bool,
        typer.Option(
            "--agent-hub-fallback",
            help="Required: confirm the caller has no native image generation and wants Agent Hub image generation.",
        ),
    ] = False,
) -> None:
    """Fallback Agent Hub image generation for callers with no native imagegen.

    Default rule: use the calling agent's native image generator first, save
    the result durably, then run `st design asset import` so Asset Studio still
    owns review/approval. This command is only for agents/surfaces with no
    native image generation; pass `--agent-hub-fallback` to confirm that.

    For hand-authored UI HTML, use `st design ui create` / `attach`.
    For AI-generated UI mockups from a live URL, use `st design ui analyze`.
    """
    if not agent_hub_fallback:
        typer.echo(
            "GATE: use the calling agent's native image generator first, then "
            "`st design asset import`. Rerun with --agent-hub-fallback only "
            "if this caller has no native image generation.",
            err=True,
        )
        raise typer.Exit(2)

    require_explicit_project(get_config())
    client = STClient()

    payload = _build_asset_payload(
        name=name, prompt=prompt, description=description,
        asset_type=asset_type, workflow=workflow, size=size,
        agent_slug=agent_slug, style_prompt=style_prompt, negative_prompt=negative_prompt,
        background=background, variant_count=variant_count, tags=tags,
        sheet_columns=sheet_columns, sheet_rows=sheet_rows,
        frame_width=frame_width, frame_height=frame_height,
        animation_labels=animation_labels, source_asset_id=source_asset_id,
        reference_image_path=reference_image_path, reference_mime_type=reference_mime_type,
    )

    try:
        result = client.post(client._url("/design-assets/generate"), json=payload)
    except APIError as exc:
        handle_api_error(exc)
        raise typer.Exit(1) from None

    output_json(result)


@asset_app.command("import")
def import_asset(
    name: Annotated[str, typer.Argument(help="Asset display name")],
    image_file: Annotated[Path, typer.Argument(help="PNG/JPEG/WebP/SVG image to store in Asset Studio")],
    prompt: Annotated[str, typer.Option("--prompt", help="Brief/source note shown with the asset")] = "Manual asset import",
    description: Annotated[str | None, typer.Option("--description", "-d", help="Optional description stored with the asset")] = None,
    asset_type: _AssetType = "sprite",
    workflow: _Workflow = "concept",
    background: _Background = "transparent",
    tags: Annotated[str | None, typer.Option("--tags", help="Comma-separated tags")] = None,
    sheet_columns: Annotated[int | None, typer.Option("--sheet-columns", help="Sprite sheet columns")] = None,
    sheet_rows: Annotated[int | None, typer.Option("--sheet-rows", help="Sprite sheet rows")] = None,
    frame_width: Annotated[int | None, typer.Option("--frame-width", help="Sprite sheet frame width")] = None,
    frame_height: Annotated[int | None, typer.Option("--frame-height", help="Sprite sheet frame height")] = None,
    animation_labels: Annotated[str | None, typer.Option("--animations", help="Comma-separated animation row labels")] = None,
    source_asset_id: Annotated[int | None, typer.Option("--source-asset-id", help="Source asset DB id for variant derivation")] = None,
    generator_note: Annotated[str | None, typer.Option("--generator-note", help="Who/what produced this manual asset")] = None,
) -> None:
    """Import a self/user-generated image into Asset Studio for approval.

    This is the manual/current-agent path. It does not invoke Agent Hub image
    generation. Use it when the project lead chooses for you (or another
    agent/user) to create the image yourself, while still preserving the
    Asset Studio review and approval gate.
    """
    require_explicit_project(get_config())
    client = STClient()
    payload = _build_import_asset_payload(
        name=name,
        image_file=image_file,
        prompt=prompt,
        description=description,
        asset_type=asset_type,
        workflow=workflow,
        background=background,
        tags=tags,
        sheet_columns=sheet_columns,
        sheet_rows=sheet_rows,
        frame_width=frame_width,
        frame_height=frame_height,
        animation_labels=animation_labels,
        source_asset_id=source_asset_id,
        generator_note=generator_note,
    )

    try:
        result = client.post(client._url("/design-assets/import"), json=payload)
    except APIError as exc:
        handle_api_error(exc)
        raise typer.Exit(1) from None

    output_json(result)


@asset_app.command("critique")
def critique_asset(
    image_file: Annotated[Path, typer.Argument(help="PNG/JPEG/GIF/WebP image to critique")],
    brief: Annotated[str | None, typer.Option("--brief", help="Asset-specific art direction / acceptance criteria")] = None,
    brief_file: Annotated[Path | None, typer.Option("--brief-file", help="Read art direction / acceptance criteria from a file")] = None,
    asset_kind: Annotated[
        str,
        typer.Option("--kind", help="Asset kind: sprite, animation, tileset, environment, ui, icon, vfx"),
    ] = "sprite",
    agent_slug: Annotated[
        str,
        typer.Option("--agent", help="Agent Hub visual critique agent slug"),
    ] = DEFAULT_ASSET_CRITIQUE_AGENT,
    gemma: Annotated[
        bool,
        typer.Option("--gemma", help="Use local Gemma 4 12B game-art critic agent"),
    ] = False,
    model_overrides: Annotated[
        list[str] | None,
        typer.Option("--model", "-M", help="Model override. Repeat for a critique panel."),
    ] = None,
    ensemble: Annotated[
        bool,
        typer.Option("--ensemble", help="Run the default complementary critique panel instead of only the agent default."),
    ] = False,
    memory: Annotated[bool, typer.Option("--memory/--no-memory", help="Enable Agent Hub memory injection")] = True,
    timeout: Annotated[float, typer.Option("--timeout", "-t", min=1.0, help="HTTP read-timeout per critique call")] = 120.0,
) -> None:
    """Critique a visual game asset through Agent Hub.

    This is the canonical non-siloed game-asset critique surface. It calls an
    Agent Hub specialist (`game-art-critic` by default), can run a multi-model
    panel, and returns compact structured output suitable for agent workflows.

    Examples:
        st -P the-aftertimes design asset critique ranger-proof.png --kind sprite
        st -P the-aftertimes design asset critique ranger-proof.png --kind sprite --gemma
        st -P the-aftertimes design asset critique ranger-proof.png --ensemble
        st design asset critique sheet.png -M xai/grok-4.20-0309-reasoning -M gemini-3.1-flash-lite
    """
    cfg = get_config()
    require_explicit_project(cfg)
    if not image_file.is_file():
        output_error(f"Image not found: {image_file}")
        raise typer.Exit(1)
    effective_agent_slug = GEMMA_ASSET_CRITIQUE_AGENT if gemma else agent_slug
    resolved_brief = _resolve_optional_text(brief, brief_file)
    prompt = _build_asset_critique_prompt(asset_kind=asset_kind, brief=resolved_brief)
    models = _critique_model_plan(model_overrides, ensemble)

    critiques: list[dict[str, Any]] = []
    for model in models:
        model_prompt = f"@{model} {prompt}" if model else prompt
        label = model or f"{effective_agent_slug}:default"
        try:
            result = call_complete(
                agent_slug=effective_agent_slug,
                message=model_prompt,
                project_id=cfg.project_id,
                source_client="st-design-asset-critique",
                use_memory=memory,
                timeout=timeout,
                skip_cache=True,
                task_type="design_asset_critique",
                images=[str(image_file)],
                source_metadata={
                    "surface": "st.design.asset.critique",
                    "asset_kind": asset_kind,
                    "image_file": str(image_file),
                    "model_override": model,
                    "ensemble": ensemble,
                    "gemma": gemma,
                },
                tool_name="st design asset critique",
            )
        except typer.Exit:
            raise
        except Exception as exc:  # pragma: no cover - defensive CLI boundary
            critiques.append({"model": label, "ok": False, "error": str(exc)})
            continue
        critiques.append({
            "model": label,
            "ok": not bool(result.get("error")),
            "content": result.get("content", ""),
            "session_id": result.get("session_id"),
            "raw_error": result.get("error"),
        })

    output_json({
        "success": all(item.get("ok") for item in critiques),
        "agent": effective_agent_slug,
        "project_id": cfg.project_id,
        "image_file": str(image_file),
        "asset_kind": asset_kind,
        "ensemble": len(models) > 1,
        "models": [model or f"{effective_agent_slug}:default" for model in models],
        "critiques": critiques,
    })


@asset_app.command("export")
def export_asset(
    asset_id: Annotated[str, typer.Argument(help="Design asset id to export")],
    export_type: Annotated[
        str,
        typer.Option("--type", "-t", help="Export type (currently: sprite-frames)"),
    ] = "sprite-frames",
) -> None:
    """Export an existing Design Ops asset.

    Currently supports sprite sheet frame exports.
    """
    require_explicit_project(get_config())
    client = STClient()

    export_path = _resolve_asset_export_path(asset_id, export_type)

    try:
        result = client.post(client._url(export_path))
    except APIError as exc:
        handle_api_error(exc)
        raise typer.Exit(1) from None

    output_json(result)


def _resolve_optional_text(text: str | None, text_file: Path | None) -> str:
    """Resolve optional inline/file text."""
    parts: list[str] = []
    if text:
        parts.append(text)
    if text_file is not None:
        if not text_file.is_file():
            raise typer.BadParameter(f"Brief file not found: {text_file}")
        parts.append(text_file.read_text())
    return "\n\n".join(part.strip() for part in parts if part.strip())


def _critique_model_plan(model_overrides: list[str] | None, ensemble: bool) -> list[str | None]:
    """Return model overrides to run; None means use the agent default."""
    if model_overrides:
        cleaned: list[str | None] = [model.strip() for model in model_overrides if model.strip()]
        if cleaned:
            return cleaned
        return [None]
    if ensemble:
        return list(DEFAULT_ASSET_CRITIQUE_MODELS)
    return [None]


def _build_asset_critique_prompt(*, asset_kind: str, brief: str) -> str:
    """Build the standard game-asset critique prompt."""
    brief_section = brief or "No extra brief supplied. Apply general production game-asset standards."
    return f"""You are critiquing a game {asset_kind} image for production use across 2D/3D game art media.

First prove you are looking at this exact image by naming 3-5 visible elements. If the image is unavailable, say that and stop; do not hallucinate.

Critique the whole image, not only the checklist. If the supplied brief is narrow, still report any other production issue you observe. For labeled direction sheets or turnaround poses, verify that each label actually faces that direction and flag any duplicate/mislabeled facing.

Critique against these standards:
- strong silhouette/readability at intended game scale;
- disciplined hard pixel clusters and no blurry pseudo-pixel art when the asset is pixel art;
- coherent shape language, value grouping, material/readability, and export-safe edges for non-pixel 2D/UI art;
- proportions, material/texture read, UV/normal/lighting artifacts when visible, and rig/LOD readiness for 3D/model renders;
- non-generic player/enemy/environment identity;
- material separation, lighting direction, and beautiful cohesive mood;
- animation/runtime readiness: pivots, contacts, seams, scale, alpha, and engine export risks;
- concrete local edits an agent can implement.

Project/user brief:
{brief_section}

Return only:
1. Vision sanity: concrete observed elements.
2. Verdict: approve / approve-with-revisions / reject.
3. Blocking issues: exact region + why it hurts quality.
4. Concrete edit instructions: exact local edits.
5. Animation/engine-readiness risks.
6. What not to change.
7. Usefulness score 1-10.
"""


@ui_app.command("analyze")
def analyze_ui(
    page_url: Annotated[str, typer.Argument(help="Fully-qualified page URL to analyze")],
    page_path: Annotated[
        str | None,
        typer.Option("--page-path", help="Optional project page path metadata"),
    ] = None,
) -> None:
    """AI-analyze a live URL and produce a UI mockup via the design agent.

    Requires the page to be reachable. Invokes the `ui-mockup-designer` agent
    through Agent Hub, which screenshots the page and proposes a redesign.
    Use this when you want AI-generated suggestions from a live reference.

    Use `st design ui create` instead when you (or another agent) want to
    hand-author the HTML and just have it stored without AI regeneration.
    """
    require_explicit_project(get_config())
    client = STClient()

    try:
        result = client.post(
            client._url("/mockups/analyze-page"),
            json={"page_url": page_url, "page_path": page_path},
        )
    except APIError as exc:
        handle_api_error(exc)
        raise typer.Exit(1) from None

    output_json(result)


@ui_app.command("rerun")
def rerun_ui_mockup(
    mockup_id: Annotated[str, typer.Argument(help="Mockup id to rerun")],
    notes: Annotated[
        str | None,
        typer.Option("--notes", "-n", help="Revision notes for the UI mockup agent"),
    ] = None,
    notes_file: Annotated[
        Path | None,
        typer.Option("--notes-file", help="Path to a file containing revision notes"),
    ] = None,
) -> None:
    """Rerun a stored UI mockup through the AI design agent.

    Always invokes the `ui-mockup-designer` agent and saves the regenerated
    HTML as a child version. The agent rewrites the HTML — your exact markup
    will not survive.

    Use `st design ui attach` instead when you want to save a hand-authored
    revision under an existing mockup without AI regeneration.
    """
    require_explicit_project(get_config())
    revision_notes = _resolve_notes(notes, notes_file)
    client = STClient()

    try:
        result = client.post(
            client._url(f"/mockups/{mockup_id}/rerun"),
            json={"notes": revision_notes},
        )
    except APIError as exc:
        handle_api_error(exc)
        raise typer.Exit(1) from None

    output_json(result)


@ui_app.command("create")
def create_ui_mockup(
    name: Annotated[str, typer.Argument(help="Mockup display name")],
    html: Annotated[
        str | None,
        typer.Option("--html", help="Inline HTML content for the mockup"),
    ] = None,
    html_file: Annotated[
        Path | None,
        typer.Option("--html-file", help="Path to a file containing the HTML mockup"),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", "-d", help="Optional description stored with the mockup"),
    ] = None,
    mockup_type: Annotated[
        str,
        typer.Option(
            "--mockup-type",
            help="Mockup classification: page, component, layout, flow, system",
        ),
    ] = "page",
    reference_url: Annotated[
        str | None,
        typer.Option("--reference-url", help="Live page URL this mockup references (stored as page_path)"),
    ] = None,
    reference_image: Annotated[
        Path | None,
        typer.Option(
            "--reference-image",
            help="Path to a reference screenshot; stored in metadata as reference_image_path",
        ),
    ] = None,
    tags: Annotated[
        str | None,
        typer.Option("--tags", help="Comma-separated tags stored in metadata"),
    ] = None,
    task_id: Annotated[
        str | None,
        typer.Option("--task-id", help="Optional task id to associate with the mockup"),
    ] = None,
) -> None:
    """Store hand-authored HTML as a new mockup (no AI regeneration).

    Use this when you (or another agent) want to commit a specific HTML
    layout and have it appear in the project's design gallery exactly as
    written. The HTML is saved verbatim with generator="manual-html".

    Don't use this for AI-driven mockup generation — use `ui analyze` for
    a fresh AI proposal from a live URL, or `ui rerun` to revise an existing
    mockup with the AI agent.

    Examples:
        st -P portfolio-ai design ui create today-layout-a \\
            --html-file /tmp/layout-a.html \\
            --reference-url https://example.com/ \\
            --reference-image /tmp/today.png \\
            -d "Balanced /today layout: hero + digest"

        st -P portfolio-ai design ui create signal-card --html "<section>...</section>" \\
            --mockup-type component --tags "signals,deterministic"
    """
    require_explicit_project(get_config())
    content = _resolve_html(html, html_file)
    client = STClient()

    payload = _build_manual_mockup_payload(
        name=name,
        content=content,
        description=description,
        mockup_type=mockup_type,
        reference_url=reference_url,
        reference_image=reference_image,
        tags=tags,
        task_id=task_id,
    )

    try:
        result = client.post(client._url("/mockups"), json=payload)
    except APIError as exc:
        handle_api_error(exc)
        raise typer.Exit(1) from None

    output_json(result)


@ui_app.command("attach")
def attach_ui_mockup(
    mockup_id: Annotated[
        str,
        typer.Argument(help="Existing mockup id (e.g. mk-abc123) to attach a revision to"),
    ],
    html: Annotated[
        str | None,
        typer.Option("--html", help="Inline HTML content for the revision"),
    ] = None,
    html_file: Annotated[
        Path | None,
        typer.Option("--html-file", help="Path to a file containing the revision HTML"),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", "-d", help="Optional description stored with the revision"),
    ] = None,
    reference_url: Annotated[
        str | None,
        typer.Option("--reference-url", help="Live page URL this revision references"),
    ] = None,
    reference_image: Annotated[
        Path | None,
        typer.Option(
            "--reference-image",
            help="Path to a reference screenshot; stored in metadata as reference_image_path",
        ),
    ] = None,
) -> None:
    """Attach a hand-authored HTML revision to an existing mockup.

    Resolves the public mockup id (string) to its DB row id and creates a
    child mockup linked via parent_mockup_id, preserving the iteration chain
    in the gallery. The HTML is stored verbatim — no AI regeneration.

    Use `st design ui rerun` instead when you want the AI ui-mockup-designer
    agent to generate the next iteration for you.

    Example:
        st -P portfolio-ai design ui attach mk-abc123 \\
            --html-file /tmp/layout-a-v2.html \\
            -d "Tightened spacing, added deterministic badge"
    """
    require_explicit_project(get_config())
    content = _resolve_html(html, html_file)
    client = STClient()

    try:
        parent = client.get(client._url(f"/mockups/{mockup_id}"))
    except APIError as exc:
        handle_api_error(exc)
        raise typer.Exit(1) from None

    parent_db_id = parent.get("id")
    if not isinstance(parent_db_id, int):
        raise typer.BadParameter(
            f"Could not resolve parent mockup id from {mockup_id} (no integer 'id' field)"
        )

    name = parent.get("name") or mockup_id
    payload = _build_manual_mockup_payload(
        name=name,
        content=content,
        description=description,
        mockup_type=parent.get("mockup_type") or "page",
        reference_url=reference_url or parent.get("page_path"),
        reference_image=reference_image,
        tags=None,
        task_id=parent.get("task_id"),
        parent_mockup_id=parent_db_id,
    )

    try:
        result = client.post(client._url("/mockups"), json=payload)
    except APIError as exc:
        handle_api_error(exc)
        raise typer.Exit(1) from None

    output_json(result)


def _build_manual_mockup_payload(
    *,
    name: str,
    content: str,
    description: str | None,
    mockup_type: str,
    reference_url: str | None,
    reference_image: Path | None,
    tags: str | None,
    task_id: str | None,
    parent_mockup_id: int | None = None,
) -> dict[str, Any]:
    """Build a POST /mockups payload for hand-authored HTML."""
    metadata: dict[str, Any] = {}
    if reference_image is not None:
        metadata["reference_image_path"] = str(reference_image)
    parsed_tags = _split_csv(tags)
    if parsed_tags:
        metadata["tags"] = parsed_tags

    payload: dict[str, Any] = {
        "name": name,
        "mockup_type": mockup_type,
        "content": content,
        "generator": "manual-html",
    }
    if description:
        payload["description"] = description
    if reference_url:
        payload["page_path"] = reference_url
    if task_id:
        payload["task_id"] = task_id
    if parent_mockup_id is not None:
        payload["parent_mockup_id"] = parent_mockup_id
    if metadata:
        payload["metadata"] = metadata
    return payload


def _build_import_asset_payload(
    *,
    name: str,
    image_file: Path,
    prompt: str,
    description: str | None,
    asset_type: str,
    workflow: str,
    background: str,
    tags: str | None,
    sheet_columns: int | None,
    sheet_rows: int | None,
    frame_width: int | None,
    frame_height: int | None,
    animation_labels: str | None,
    source_asset_id: int | None,
    generator_note: str | None,
) -> dict[str, Any]:
    """Build a manual asset import payload from a local image file."""
    if not image_file.exists() or not image_file.is_file():
        raise typer.BadParameter(f"Image file not found: {image_file}")
    metadata: dict[str, Any] = {"source_gate": "manual-current-agent"}
    if generator_note:
        metadata["generator_note"] = generator_note
    payload: dict[str, Any] = {
        "name": name,
        "image_base64": base64.b64encode(image_file.read_bytes()).decode("utf-8"),
        "mime_type": _guess_mime_type(image_file),
        "original_file_name": image_file.name,
        "prompt": prompt,
        "asset_type": asset_type,
        "workflow": workflow,
        "background": background,
        "transparent_background": background == "transparent",
        "metadata": metadata,
    }
    if description:
        payload["description"] = description
    if source_asset_id is not None:
        payload["source_asset_id"] = source_asset_id
    _apply_sheet_fields(payload, tags=tags, animation_labels=animation_labels,
                        sheet_columns=sheet_columns, sheet_rows=sheet_rows,
                        frame_width=frame_width, frame_height=frame_height)
    return payload


def _build_asset_payload(
    *,
    name: str,
    prompt: str,
    description: str | None,
    asset_type: str,
    workflow: str,
    size: str,
    agent_slug: str | None,
    style_prompt: str | None,
    negative_prompt: str | None,
    background: str,
    variant_count: int,
    tags: str | None,
    sheet_columns: int | None,
    sheet_rows: int | None,
    frame_width: int | None,
    frame_height: int | None,
    animation_labels: str | None,
    source_asset_id: int | None,
    reference_image_path: str | None = None,
    reference_mime_type: str | None = None,
) -> dict[str, Any]:
    """Build the asset generation payload."""
    payload: dict[str, Any] = {
        "name": name,
        "prompt": prompt,
        "asset_type": asset_type,
        "workflow": workflow,
        "size": size,
        "background": background,
        "transparent_background": background == "transparent",
        "variant_count": variant_count,
    }
    _apply_optional_fields(payload, description=description, agent_slug=agent_slug,
                           style_prompt=style_prompt, negative_prompt=negative_prompt,
                           source_asset_id=source_asset_id)
    _apply_reference_image(payload, reference_image_path, reference_mime_type)
    _apply_sheet_fields(payload, tags=tags, animation_labels=animation_labels,
                        sheet_columns=sheet_columns, sheet_rows=sheet_rows,
                        frame_width=frame_width, frame_height=frame_height)
    return payload


def _apply_optional_fields(
    payload: dict[str, Any],
    *,
    description: str | None,
    agent_slug: str | None,
    style_prompt: str | None,
    negative_prompt: str | None,
    source_asset_id: int | None,
) -> None:
    """Apply simple optional scalar fields to the payload in place."""
    if description:
        payload["description"] = description
    if agent_slug:
        payload["agent_slug"] = agent_slug
    if style_prompt:
        payload["style_prompt"] = style_prompt
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    if source_asset_id is not None:
        payload["source_asset_id"] = source_asset_id


def _apply_reference_image(
    payload: dict[str, Any],
    reference_image_path: str | None,
    reference_mime_type: str | None,
) -> None:
    """Encode and attach a reference image to the payload in place."""
    if not reference_image_path:
        return
    image_path = Path(reference_image_path)
    payload["reference_image_path"] = str(image_path)
    payload["reference_image"] = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    payload["reference_mime_type"] = reference_mime_type or _guess_mime_type(image_path)


def _apply_sheet_fields(
    payload: dict[str, Any],
    *,
    tags: str | None,
    animation_labels: str | None,
    sheet_columns: int | None,
    sheet_rows: int | None,
    frame_width: int | None,
    frame_height: int | None,
) -> None:
    """Apply sprite sheet and tag fields to the payload in place."""
    parsed_tags = _split_csv(tags)
    if parsed_tags:
        payload["tags"] = parsed_tags
    parsed_animations = _split_csv(animation_labels)
    if parsed_animations:
        payload["animation_labels"] = parsed_animations
    if sheet_columns is not None:
        payload["sheet_columns"] = sheet_columns
    if sheet_rows is not None:
        payload["sheet_rows"] = sheet_rows
    if frame_width is not None:
        payload["frame_width"] = frame_width
    if frame_height is not None:
        payload["frame_height"] = frame_height


def _split_csv(value: str | None) -> list[str]:
    """Split a comma-separated option into trimmed values."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _resolve_notes(notes: str | None, notes_file: Path | None) -> str:
    """Resolve revision notes from an option or file."""
    if notes and notes_file:
        raise typer.BadParameter("Use either --notes or --notes-file, not both")
    value = notes_file.read_text(encoding="utf-8").strip() if notes_file else (notes or "").strip()
    if not value:
        raise typer.BadParameter("Revision notes are required")
    return value


def _resolve_html(html: str | None, html_file: Path | None) -> str:
    """Resolve mockup HTML content from an inline option or file."""
    if html and html_file:
        raise typer.BadParameter("Use either --html or --html-file, not both")
    value = html_file.read_text(encoding="utf-8") if html_file else (html or "")
    if not value.strip():
        raise typer.BadParameter("HTML content is required (use --html or --html-file)")
    return value


def _guess_mime_type(path: Path) -> str:
    """Infer MIME type from a reference image file extension."""
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".svg":
        return "image/svg+xml"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _resolve_asset_export_path(asset_id: str, export_type: str) -> str:
    """Map CLI export type to API path."""
    export_type_key = export_type.strip().lower()
    if export_type_key != "sprite-frames":
        raise typer.BadParameter("Unsupported export type. Use: sprite-frames")
    return f"/design-assets/{asset_id}/exports/sprite-frames"


app.add_typer(asset_app, name="asset")
app.add_typer(ui_app, name="ui")
