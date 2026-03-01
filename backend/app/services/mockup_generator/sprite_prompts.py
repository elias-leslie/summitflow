"""Prompt templates for game asset generation.

These templates wrap user prompts with structure appropriate to different
asset types (single sprite, sprite sheet, environment art).  The image-gen
agent provides general quality guardrails; these templates add the
game-specific framing.
"""

from __future__ import annotations


def build_sprite_prompt(user_prompt: str, style: str | None = None) -> str:
    """Build a prompt for a single character/item sprite.

    Args:
        user_prompt: User's description of the desired sprite.
        style: Optional style descriptor (e.g. "hand-drawn cartoon").

    Returns:
        Merged prompt string ready for image generation.
    """
    style_line = f"\nArt style: {style}" if style else ""
    return (
        f"Single game sprite on a transparent background.\n"
        f"{user_prompt}\n"
        f"Requirements: centered subject, clean edges, no drop shadow, "
        f"suitable for compositing onto any background.{style_line}"
    )


def build_sheet_prompt(
    user_prompt: str,
    cols: int = 4,
    rows: int = 2,
    frame_size: int = 128,
    animations: str | None = None,
    style: str | None = None,
) -> str:
    """Build a prompt for a sprite sheet grid.

    Args:
        user_prompt: Description of the character/item.
        cols: Number of columns in the grid.
        rows: Number of rows in the grid.
        frame_size: Pixel size of each frame (square).
        animations: Comma-separated animation names (e.g. "idle,walk,attack").
        style: Optional style descriptor.

    Returns:
        Merged prompt string.
    """
    anim_line = f"\nAnimation rows: {animations}" if animations else ""
    style_line = f"\nArt style: {style}" if style else ""
    return (
        f"Sprite sheet grid: {cols} columns x {rows} rows, "
        f"each cell {frame_size}x{frame_size}px.\n"
        f"{user_prompt}\n"
        f"Requirements: uniform cell size, consistent character proportions "
        f"across all frames, transparent background, "
        f"thin visible grid lines between cells for easy slicing."
        f"{anim_line}{style_line}"
    )


def build_environment_prompt(
    user_prompt: str,
    width: int = 1920,
    height: int = 1080,
    style: str | None = None,
) -> str:
    """Build a prompt for background/environment art.

    Args:
        user_prompt: Description of the environment.
        width: Target width in pixels.
        height: Target height in pixels.
        style: Optional style descriptor.

    Returns:
        Merged prompt string.
    """
    style_line = f"\nArt style: {style}" if style else ""
    return (
        f"Game background art, {width}x{height}px.\n"
        f"{user_prompt}\n"
        f"Requirements: seamless horizontal tiling where possible, "
        f"parallax-friendly layering, rich detail without distracting "
        f"from foreground gameplay elements.{style_line}"
    )


__all__ = ["build_environment_prompt", "build_sheet_prompt", "build_sprite_prompt"]
