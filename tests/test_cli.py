from typer.testing import CliRunner

from pipeline.cli import app
from pipeline.common.run_context import ensure_run_context

runner = CliRunner()


def test_cli_help_contains_name() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.stdout
    assert "health" in result.stdout
    assert "ingest" in result.stdout
    assert "validate" in result.stdout
    assert "run" in result.stdout


def test_health_json_output_contains_ai_readiness() -> None:
    result = runner.invoke(app, ["health", "--json-output"])
    assert result.exit_code == 0
    assert '"status": "ok"' in result.stdout
    assert '"provider"' in result.stdout


def test_validate_cli_rejects_llm_disable_without_explicit_override() -> None:
    result = runner.invoke(
        app,
        [
            "validate",
            "--run-id",
            "run-test",
            "--fact-check-profile",
            "warn",
            "--no-fact-check-enable-llm",
        ],
    )
    assert result.exit_code != 0
    assert "requires LLM adjudication" in result.output


def test_validate_cli_rejects_uppercase_warn_when_llm_disabled() -> None:
    result = runner.invoke(
        app,
        [
            "validate",
            "--run-id",
            "run-test",
            "--fact-check-profile",
            "WARN",
            "--no-fact-check-enable-llm",
        ],
    )
    assert result.exit_code != 0
    assert "requires LLM adjudication" in result.output


def test_run_cli_rejects_mixed_case_strict_when_llm_disabled() -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--fact-check-profile",
            "Strict",
            "--no-fact-check-enable-llm",
        ],
    )
    assert result.exit_code != 0
    assert "requires LLM adjudication" in result.output


def test_validate_cli_rejects_invalid_fact_check_profile() -> None:
    result = runner.invoke(
        app,
        [
            "validate",
            "--run-id",
            "run-test",
            "--fact-check-profile",
            "banana",
        ],
    )
    assert result.exit_code != 0
    assert "must be one of: off, warn, strict" in result.output


def test_run_cli_rejects_invalid_fact_check_profile() -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "--fact-check-profile",
            "banana",
        ],
    )
    assert result.exit_code != 0
    assert "must be one of: off, warn, strict" in result.output


def test_validate_cli_accepts_case_variant_profile_and_normalizes(
    tmp_path,
    monkeypatch,
) -> None:
    context = ensure_run_context("run-test-validate-case-profile", artifacts_root=tmp_path / "runs")
    observed: dict[str, str] = {}

    monkeypatch.setattr("pipeline.cli.ensure_run_context", lambda _run_id=None: context)

    def fake_validate(*_args, **kwargs):
        observed["profile"] = kwargs["fact_check_profile"]
        return {
            "passed": True,
            "validation_report_path": context.reports_dir / "validate" / "validation_report.json",
            "fact_check_report_path": context.reports_dir / "validate" / "fact_check_report.json",
            "fact_check_summary_path": context.reports_dir / "validate" / "fact_check_summary.md",
        }

    monkeypatch.setattr("pipeline.cli.run_validate_stage", fake_validate)
    result = runner.invoke(
        app,
        [
            "validate",
            "--run-id",
            context.run_id,
            "--fact-check-profile",
            "Strict",
        ],
    )
    assert result.exit_code == 0
    assert observed["profile"] == "strict"


def test_run_cli_accepts_case_variant_profile_and_normalizes(monkeypatch) -> None:
    observed: dict[str, str] = {}

    def fake_run_flow(**kwargs):
        observed["profile"] = kwargs["fact_check_profile"]
        return {
            "run_id": "run-test",
            "validate": {"passed": True},
        }

    monkeypatch.setattr("pipeline.cli.run_pipeline_flow", fake_run_flow)
    result = runner.invoke(
        app,
        [
            "run",
            "--fact-check-profile",
            "WARN",
        ],
    )
    assert result.exit_code == 0
    assert observed["profile"] == "warn"
