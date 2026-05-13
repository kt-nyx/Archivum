"""Baseline CLI entrypoint for staged pipeline commands."""

import typer

app = typer.Typer(help="WoW Lore Companion pipeline CLI.")


@app.callback()
def cli() -> None:
    """CLI command group."""


@app.command()
def health() -> None:
    """Return a simple status for bootstrap verification."""
    typer.echo("ok")


def main() -> None:
    """Script entrypoint used by `lore-pipeline`."""
    app()


if __name__ == "__main__":
    main()
