from typer.testing import CliRunner

from pipeline.cli import app

runner = CliRunner()


def test_cli_help_contains_name() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.stdout
    assert "health" in result.stdout
