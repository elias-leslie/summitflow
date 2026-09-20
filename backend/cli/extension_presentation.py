"""ST-owned presentation compatibility, without owner product behavior."""

import typer

from .details import current_root, display_path, summary_hint, write_details


def present_web(argv: list[str], code: int, stdout: str, stderr: str) -> None:
    if code == 2:
        typer.echo(stdout, nl=False)
        typer.echo(stderr.replace("web-research", "st web"), err=True, nl=False)
        return
    output = "\n".join(part for part in (stdout, stderr) if part)
    options = argv[:argv.index("--")] if "--" in argv else argv
    if "--raw" in options:
        print(output)
        return
    command = argv[0] if argv else "web"
    root = current_root()
    details = write_details(root, f"web-{command}", output)
    print(f"WEB:{command}:{'OK' if code == 0 else 'FAIL'}:{code}|"
          f"details:{display_path(root, details)}|hint:{summary_hint(output)}")
