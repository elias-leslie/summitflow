# Registered project README template

Root `README.md` is the source for SummitFlow's project Overview. Use the shared
structure below for registered applications, desktop tools, games, CLIs, libraries,
and workspaces. The opening description should tell an operator what the project
is, who uses it, and what it helps them accomplish.

```markdown
# <Canonical project name>

<What the project is, who uses it, and its concrete purpose.>

## What it does

<Implemented capabilities and useful workflows.>

## Current scope

<Implemented scope, material limitations, and experimental or planned work.>

## Getting started

<Supported entry point, prerequisites, shortest useful path, and expected result.>

## Runtime, data, and integrations

<Runtime processes, durable data ownership, required dependencies, optional
integrations, and consequential unavailable-service behavior.>

## Development and verification

<Repository map, canonical checks, and what those checks establish.>

## Documentation

<Existing usage, architecture, operations, release, license, and contribution links.>
```

Source project identity and services from `project.identity.json`, entry points
and dependencies from checked-in source and manifests, and supported workflows
from current operating documentation. The [catalog](project-catalog.md) owns
registry, lifecycle, checkout, and URL distinctions. Declared services do not
prove current availability; keep live health out of static documentation.

Keep capability qualifications close to their claims. Separate packaged runtime
requirements from source-build tools, and optional development integrations from
product dependencies. Projects without a server or database should say so. Do
not invent commands, ports, installation steps, licenses, or roadmap promises to
fill a section.

Keep the root focused on project understanding. Preserve detailed operating
recipes and references in linked documentation, rebasing relative links when
moving content. Use ordinary Markdown with headings, lists, links, and fenced
commands; essential meaning should not rely on badges, raw HTML, or diagrams.

When updating a README, verify the seven shared headings, source-grounded facts,
local links, and a representative rendering in SummitFlow. Unknown or unverified
behavior must remain explicit. Overview reads the registered checkout on request,
so documentation-only changes do not require rebuilding that project's services.
