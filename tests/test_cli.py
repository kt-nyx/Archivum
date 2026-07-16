import json

from typer.testing import CliRunner

from pipeline.cli import app
from pipeline.common.run_context import (
    RunArtifactsExistError,
    ensure_run_context,
    write_stage_manifest,
)

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
            "release_gate": kwargs.get("release_gate", False),
            "fact_check_profile": kwargs["fact_check_profile"],
            "release_certified": False,
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
            "validate": {"passed": True, "release_certified": False},
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


def test_validate_cli_passes_release_gate_flag(tmp_path, monkeypatch) -> None:
    context = ensure_run_context("run-test-validate-release-gate", artifacts_root=tmp_path / "runs")
    observed: dict[str, bool] = {}

    monkeypatch.setattr("pipeline.cli.ensure_run_context", lambda _run_id=None: context)

    def fake_validate(*_args, **kwargs):
        observed["release_gate"] = kwargs["release_gate"]
        return {
            "passed": True,
            "release_gate": kwargs["release_gate"],
            "fact_check_profile": "off",
            "release_certified": False,
            "validation_report_path": context.reports_dir / "validate" / "validation_report.json",
            "fact_check_report_path": context.reports_dir / "validate" / "fact_check_report.json",
            "fact_check_summary_path": context.reports_dir / "validate" / "fact_check_summary.md",
        }

    monkeypatch.setattr("pipeline.cli.run_validate_stage", fake_validate)
    result = runner.invoke(
        app,
        ["validate", "--run-id", context.run_id, "--fact-check-profile", "off", "--release-gate"],
    )
    assert result.exit_code == 0
    assert observed["release_gate"] is True
    assert "release_gate=True" in result.stdout


def test_run_cli_passes_release_gate_flag(monkeypatch) -> None:
    observed: dict[str, bool] = {}

    def fake_run_flow(**kwargs):
        observed["release_gate"] = kwargs["release_gate"]
        return {
            "run_id": "run-test",
            "validate": {"passed": True, "release_certified": False},
        }

    monkeypatch.setattr("pipeline.cli.run_pipeline_flow", fake_run_flow)
    result = runner.invoke(
        app,
        ["run", "--fact-check-profile", "off", "--release-gate"],
    )
    assert result.exit_code == 0
    assert observed["release_gate"] is True
    assert "release_gate=True" in result.stdout


def test_run_cli_passes_force_new_suffix_flag(monkeypatch) -> None:
    observed: dict[str, bool] = {}

    def fake_run_flow(**kwargs):
        observed["force_new_suffix"] = kwargs["force_new_suffix"]
        return {
            "run_id": "run-test-2",
            "validate": {"passed": True, "release_certified": False},
        }

    monkeypatch.setattr("pipeline.cli.run_pipeline_flow", fake_run_flow)
    result = runner.invoke(
        app,
        ["run", "--fact-check-profile", "off", "--force-new-suffix"],
    )
    assert result.exit_code == 0
    assert observed["force_new_suffix"] is True

    result = runner.invoke(app, ["run", "--fact-check-profile", "off"])
    assert result.exit_code == 0
    assert observed["force_new_suffix"] is False


def test_run_cli_reports_immutable_run_conflict_cleanly(monkeypatch) -> None:
    def fake_run_flow(**_kwargs):
        raise RunArtifactsExistError(
            "run 'run-test' already contains stage artifacts (ingest) and runs are immutable"
        )

    monkeypatch.setattr("pipeline.cli.run_pipeline_flow", fake_run_flow)
    result = runner.invoke(app, ["run", "--fact-check-profile", "off"])
    assert result.exit_code == 1
    assert "runs are immutable" in result.output


def test_single_stage_cli_traces_reexecution_over_existing_outputs(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("WOW_LORE_ARTIFACTS_ROOT", str(tmp_path / "runs"))
    context = ensure_run_context("run-test-cli-reexec", artifacts_root=tmp_path / "runs")
    write_stage_manifest(
        context,
        "discovery",
        status="ok",
        inputs=[],
        outputs=["discovery/zone_graph.json"],
    )

    monkeypatch.setattr("pipeline.cli.run_discovery_stage", lambda _context, _manifest: {})
    result = runner.invoke(app, ["discovery", "--run-id", context.run_id])
    assert result.exit_code == 0

    events = [
        json.loads(line)
        for line in context.trace_log_path().read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    reexec_events = [e for e in events if e["status"] == "reexecute"]
    assert len(reexec_events) == 1
    assert reexec_events[0]["stage"] == "discovery"
    assert reexec_events[0]["details"]["replaced_outputs"] == ["discovery/zone_graph.json"]
