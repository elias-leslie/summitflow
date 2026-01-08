"""Sub-element discovery service for finding interactive elements on pages."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from ...storage import explorer_sub_elements


def get_browser_scripts_dir() -> Path:
    """Get browser scripts directory."""
    return Path(os.path.expanduser("~/.claude/skills/browser-automation/scripts"))


# Element type selectors for discovery
ELEMENT_SELECTORS = {
    "tab": '[role="tab"]',
    "accordion": "[aria-expanded]",
    "expandable_row": "tr.expandable, tr[data-expandable]",
    "modal_trigger": '[data-toggle="modal"], [data-bs-toggle="modal"]',
    "dropdown": '[data-toggle="dropdown"], [data-bs-toggle="dropdown"]',
    "collapsible": '[data-toggle="collapse"], [data-bs-toggle="collapse"]',
}

# Elements to skip (potentially destructive actions)
SKIP_SELECTORS = [
    'button[type="submit"]',
    'a[href]:not([href^="#"])',
    "form button",
    '[data-action="delete"]',
    '[data-action="remove"]',
]


async def discover_elements(url: str) -> list[dict[str, str]]:
    """Discover interactive sub-elements on a page.

    Uses Puppeteer to scan for tabs, accordions, expandable rows, etc.

    Args:
        url: The page URL to scan

    Returns:
        List of discovered elements with selector, type, and label
    """
    scripts_dir = get_browser_scripts_dir()
    script_path = scripts_dir / "discover-sub-elements.js"

    # If dedicated script doesn't exist, use inline discovery
    if not script_path.exists():
        return await _inline_discovery(url)

    try:
        proc = await asyncio.create_subprocess_exec(
            "node",
            str(script_path),
            url,
            "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=60,
        )

        output = stdout.decode()

        # Parse JSON output
        for line in output.split("\n"):
            if line.strip().startswith("["):
                try:
                    elements: list[dict[str, str]] = json.loads(line.strip())
                    return elements
                except json.JSONDecodeError:
                    continue

        return []

    except TimeoutError:
        return []
    except Exception:
        return []


async def _inline_discovery(url: str) -> list[dict[str, str]]:
    """Fallback inline discovery using puppeteer."""
    scripts_dir = get_browser_scripts_dir()

    # Build inline discovery script
    selectors_json = json.dumps(ELEMENT_SELECTORS)
    skip_json = json.dumps(SKIP_SELECTORS)

    inline_script = f"""
    const puppeteer = require('puppeteer');

    (async () => {{
        const browser = await puppeteer.launch({{ headless: 'new' }});
        const page = await browser.newPage();

        try {{
            await page.goto('{url}', {{ waitUntil: 'networkidle2', timeout: 30000 }});

            const selectors = {selectors_json};
            const skipSelectors = {skip_json};
            const elements = [];

            for (const [type, selector] of Object.entries(selectors)) {{
                const found = await page.$$(selector);
                for (let i = 0; i < found.length; i++) {{
                    const el = found[i];

                    // Check if element matches skip selectors
                    const shouldSkip = await el.evaluate((node, skips) => {{
                        return skips.some(s => node.matches(s));
                    }}, skipSelectors);

                    if (shouldSkip) continue;

                    // Get element info
                    const info = await el.evaluate((node) => {{
                        return {{
                            selector: node.getAttribute('data-testid') ||
                                      node.id ? '#' + node.id :
                                      node.className ? '.' + node.className.split(' ')[0] :
                                      node.tagName.toLowerCase(),
                            label: node.textContent?.trim().slice(0, 50) ||
                                   node.getAttribute('aria-label') ||
                                   node.getAttribute('title') || ''
                        }};
                    }});

                    elements.push({{
                        selector: info.selector,
                        element_type: type,
                        label: info.label
                    }});
                }}
            }}

            console.log(JSON.stringify(elements));
        }} catch (e) {{
            console.log('[]');
        }} finally {{
            await browser.close();
        }}
    }})();
    """

    try:
        proc = await asyncio.create_subprocess_exec(
            "node",
            "-e",
            inline_script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(scripts_dir),
        )

        stdout, _ = await asyncio.wait_for(
            proc.communicate(),
            timeout=60,
        )

        output = stdout.decode().strip()
        if output.startswith("["):
            elements: list[dict[str, str]] = json.loads(output)
            return elements

        return []

    except Exception:
        return []


async def discover_and_store(
    project_id: str,
    explorer_entry_id: int,
    url: str,
) -> int:
    """Discover sub-elements and store them in the database.

    Args:
        project_id: Project ID
        explorer_entry_id: Parent explorer entry ID
        url: Page URL to scan

    Returns:
        Number of elements discovered and stored
    """
    elements = await discover_elements(url)

    if not elements:
        return 0

    # Bulk upsert discovered elements
    return explorer_sub_elements.bulk_upsert_elements(
        explorer_entry_id=explorer_entry_id,
        elements=elements,
    )


def filter_safe_elements(elements: list[dict[str, str]]) -> list[dict[str, str]]:
    """Filter elements to only include safe ones for interaction.

    Args:
        elements: List of discovered elements

    Returns:
        Filtered list excluding potentially destructive elements
    """
    safe_elements = []

    for el in elements:
        selector = el.get("selector", "").lower()
        label = el.get("label", "").lower()

        # Skip elements with destructive keywords
        if any(
            keyword in selector or keyword in label
            for keyword in ["delete", "remove", "destroy", "logout", "signout"]
        ):
            continue

        safe_elements.append(el)

    return safe_elements
