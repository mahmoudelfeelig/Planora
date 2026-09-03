from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import pytest

from benchmarks.itc2019_resource_controller import (
    CAPABILITY_EVIDENCE_SCHEMA,
    CleanupOutcome,
    ExecutionObservation,
    ResourceControllerError,
    ResourceProfile,
    SolverInvocation,
)
from scripts import benchmark_itc2019_competitors as harness
from scripts import summarize_itc2019_competitor_matrix as summarizer


TOY_PROBLEM = """\
<problem name="toy" nrDays="1" slotsPerDay="2" nrWeeks="1">
  <rooms><room id="R" capacity="1"/></rooms>
  <courses><course id="C"><config id="CFG"><subpart id="SP">
    <class id="CL" limit="10">
      <room id="R"/><time days="1" start="0" length="1" weeks="1"/>
    </class>
  </subpart></config></course></courses>
</problem>
"""

TOY_SOLUTION = """\
<solution name="toy" runtime="0">
  <class id="CL" days="1" start="0" weeks="1" room="R"/>
</solution>
"""


def _checkpoint_fixture(tmp_path: Path) -> tuple[Path, dict, dict, Path]:
    root = tmp_path / "matrix"
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    instance = input_root / "toy.xml"
    instance.write_text(TOY_PROBLEM, encoding="utf-8")
    identity = harness._run_identity(
        "toy",
        "planora",
        17,
        1,
        seeds=[17],
        repetitions=1,
    )
    manifest = {
        "schema": harness.MATRIX_SCHEMA,
        "cases": ["toy"],
        "instance_set": "public",
        "solvers": ["planora"],
        "seeds": [17],
        "repetitions": 1,
        "configured_solver_seconds": 10.0,
        "workers": 1,
        "cpu_affinity": 0,
        "input_root": str(input_root.resolve()),
        "host": {"test": True},
        "inputs": {"toy": harness._sha256(instance)},
        "tool_paths": {
            "gashi": str(tmp_path / "gashi.dll"),
            "cpsolver_root": str(tmp_path / "cpsolver"),
            "maxsat": str(tmp_path / "maxsat"),
            "maxsat_locale": str(tmp_path / "locale"),
        },
        "tools": {"test": True},
        "harness_sha256": harness._sha256(Path(harness.__file__).resolve()),
        "official_validator_helper_sha256": "helper-hash",
        "resource_policy": dict(harness.QUALITY_ONLY_RESOURCE_POLICY),
        "expected_runs": [identity],
    }
    run_dir = root / "runs" / identity["run_id"]
    run_dir.mkdir(parents=True)
    output = run_dir / "solution.xml"
    output.write_text(TOY_SOLUTION, encoding="utf-8")
    command, cwd, _supervisor, basis = harness._command_for(
        "planora",
        instance_path=instance.resolve(),
        run_dir=run_dir.resolve(),
        output_path=output.resolve(),
        seed=17,
        seconds=10.0,
        cpu=0,
        gashi=Path(manifest["tool_paths"]["gashi"]),
        cps_root=Path(manifest["tool_paths"]["cpsolver_root"]),
        maxsat=Path(manifest["tool_paths"]["maxsat"]),
        write_config=False,
    )
    record = {
        **identity,
        "configured_solver_seconds": 10.0,
        "configured_workers": 1,
        "cpu_affinity": 0,
        "budget_basis": basis,
        "equal_wall_time_claim": False,
        "equal_memory_limit_claim": False,
        "comparison_scope": harness.QUALITY_ONLY_RESOURCE_POLICY["comparison_scope"],
        "command": command,
        "command_sha256": harness._json_sha256(command),
        "run_configuration_sha256": None,
        "working_directory": str(cwd),
        "input_path": str(instance.resolve()),
        "input_sha256": harness._sha256(instance),
        "output_path": str(output.resolve()),
        "output_relative_path": f"runs/{identity['run_id']}/solution.xml",
        "output_sha256": harness._sha256(output),
        "resume_binding_sha256": harness._resume_binding_sha256(manifest),
        "orphan_lineage": None,
        "independent_validation": harness._score(instance, output),
        "parse_error": None,
        "official_validator_status": "agreement",
        "official_validator_agreement": True,
        "official_validation": {"response_sha256": "official-response"},
        "official_validated_output_sha256": harness._sha256(output),
    }
    record["artifact_binding_sha256"] = harness._artifact_binding(
        record,
        relative_path=record["output_relative_path"],
        output_sha256=record["output_sha256"],
    )
    result_path = run_dir / "result.json"
    harness._write_json_atomic(result_path, record)
    state = {
        "schema": "planora.itc2019.run-state.v1",
        **identity,
        "status": "complete",
        "run_directory": str(run_dir.resolve()),
        "input_path": str(instance.resolve()),
        "input_sha256": harness._sha256(instance),
        "configured_solver_seconds": 10.0,
        "configured_workers": 1,
        "cpu_affinity": 0,
        "command": command,
        "command_sha256": harness._json_sha256(command),
        "run_configuration_sha256": None,
        "resume_binding_sha256": harness._resume_binding_sha256(manifest),
        "orphan_lineage": None,
        "initial_result_sha256": harness._sha256(result_path),
    }
    harness._write_json_atomic(run_dir / "state.json", state)
    return root, manifest, record, output


def _rewrite_checkpoint_result(root: Path, record: dict, *, rebind_state: bool) -> None:
    result_path = next((root / "runs").glob("*/result.json"))
    harness._write_json_atomic(result_path, record)
    if rebind_state:
        state_path = result_path.parent / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["initial_result_sha256"] = harness._sha256(result_path)
        harness._write_json_atomic(state_path, state)


def test_maxsat_uses_unseeded_trial_identity_not_nominal_seed_pairing() -> None:
    rows = harness._expected_run_specs(
        ["toy"], ["planora", "lemos-maxsat"], [17, 23], 2
    )
    maxsat = [row for row in rows if row["solver"] == "lemos-maxsat"]

    assert [row["unseeded_trial"] for row in maxsat] == [1, 2, 3, 4]
    assert all(
        row["seed"] is None and row["seed_pairing_group"] is None for row in maxsat
    )
    assert len({row["run_id"] for row in rows}) == len(rows)
    assert harness.QUALITY_ONLY_RESOURCE_POLICY["equal_wall_time_claim"] is False
    assert harness.QUALITY_ONLY_RESOURCE_POLICY["equal_memory_limit_claim"] is False


def test_maxsat_supervisor_preserves_budget_basis_and_planora_sigterm(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    _command, _cwd, supervisor_seconds, basis = harness._command_for(
        "lemos-maxsat",
        instance_path=tmp_path / "instance.xml",
        run_dir=run_dir,
        output_path=run_dir / "solution.xml",
        seed=17,
        seconds=120.0,
        cpu=0,
        gashi=tmp_path / "gashi.dll",
        cps_root=tmp_path / "cpsolver",
        maxsat=tmp_path / "timetabler",
    )

    assert supervisor_seconds == (120.0 + harness.MAXSAT_COMPLETION_OVERHEAD_SECONDS)
    assert "student-allocation" in basis
    assert harness._overrun_signal("planora") == harness.signal.SIGTERM


@pytest.mark.skipif(
    not hasattr(harness.signal, "SIGKILL"),
    reason="SIGKILL is not available on this platform",
)
def test_maxsat_supervisor_avoids_broken_sigterm_handler() -> None:
    assert harness._overrun_signal("lemos-maxsat") == harness.signal.SIGKILL


def test_planora_supervisor_preserves_parse_and_serialization_overhead(
    tmp_path: Path,
) -> None:
    _command, _cwd, supervisor_seconds, basis = harness._command_for(
        "planora",
        instance_path=tmp_path / "instance.xml",
        run_dir=tmp_path,
        output_path=tmp_path / "solution.xml",
        seed=17,
        seconds=120.0,
        cpu=0,
        gashi=tmp_path / "gashi.dll",
        cps_root=tmp_path / "cpsolver",
        maxsat=tmp_path / "maxsat",
    )

    assert supervisor_seconds == (120.0 + harness.PLANORA_COMPLETION_OVERHEAD_SECONDS)
    assert "input parse" in basis
    assert "result handoff" in basis


def test_cpsolver_supervisor_preserves_standard_completion_pipeline(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    cps_root = tmp_path / "cpsolver"
    (cps_root / "configuration").mkdir(parents=True)
    (cps_root / "configuration" / "default.cfg").write_text(
        "Termination.TimeOut=7200\nParallel.NrSolvers=4\n",
        encoding="utf-8",
    )

    _command, _cwd, supervisor_seconds, basis = harness._command_for(
        "unitime-cpsolver",
        instance_path=tmp_path / "instance.xml",
        run_dir=run_dir,
        output_path=run_dir / "solution.xml",
        seed=17,
        seconds=10.0,
        cpu=0,
        gashi=tmp_path / "gashi.dll",
        cps_root=cps_root,
        maxsat=tmp_path / "maxsat",
    )

    assert supervisor_seconds == (10.0 + harness.CPSOLVER_COMPLETION_OVERHEAD_SECONDS)
    assert "student-switch" in basis
    config = (run_dir / "cpsolver.cfg").read_text(encoding="utf-8")
    assert "Termination.TimeOut=10" in config
    assert "Parallel.NrSolvers=1" in config


def test_planora_provenance_binds_every_auto_formulation_module() -> None:
    provenance = harness._planora_source_provenance()

    assert tuple(provenance["source_files"]) == harness.PLANORA_SOURCE_FILES
    assert provenance["source_sha256"] == harness._tree_digest(
        harness.ROOT / relative for relative in harness.PLANORA_SOURCE_FILES
    )
    assert all(
        digest == harness._sha256(harness.ROOT / relative)
        for relative, digest in provenance["source_files"].items()
    )


def test_corrected_middle_instances_are_bound_to_organizer_bytes() -> None:
    input_root = (
        harness.ROOT / "data/external/itc2019-mpp-c33d15797686/raw/data/input/ITC-2019"
    )

    assert (
        harness._corrected_input_hash_errors(
            input_root, harness.OFFICIAL_CORRECTED_INPUT_SHA256
        )
        == []
    )


def test_claim_grade_corpus_accepts_exact_effective_canonical_30() -> None:
    inputs = dict(harness.CANONICAL_COMPETITION_INPUT_SHA256)

    harness._validate_claim_grade_competition_corpus(
        list(harness.COMPETITION_CASES), inputs
    )

    assert len(harness.COMPETITION_CASES) == 30
    assert set(inputs) == set(harness.COMPETITION_CASES)


@pytest.mark.parametrize(
    "case",
    tuple(
        case
        for case in harness.COMPETITION_CASES
        if case not in harness.OFFICIAL_CORRECTED_INPUT_SHA256
    ),
)
def test_claim_grade_corpus_rejects_each_previously_unpinned_substitution(
    case: str,
) -> None:
    inputs = dict(harness.CANONICAL_COMPETITION_INPUT_SHA256)
    inputs[case] = "0" * 64 if inputs[case] != "0" * 64 else "1" * 64

    with pytest.raises(
        ResourceControllerError,
        match=f"claim-grade corpus substituted input: {case}",
    ):
        harness._validate_claim_grade_competition_corpus(
            list(harness.COMPETITION_CASES), inputs
        )


def test_claim_grade_corpus_substitution_matrix_covers_all_28_old_gaps() -> None:
    previously_unpinned = set(harness.COMPETITION_CASES) - set(
        harness.OFFICIAL_CORRECTED_INPUT_SHA256
    )

    assert len(previously_unpinned) == 28


def test_claim_grade_corpus_rejects_subset_missing_and_extra_manifests() -> None:
    canonical_cases = list(harness.COMPETITION_CASES)
    canonical_inputs = dict(harness.CANONICAL_COMPETITION_INPUT_SHA256)

    with pytest.raises(ResourceControllerError, match="case set mismatch"):
        harness._validate_claim_grade_competition_corpus(
            canonical_cases[:-1],
            {case: canonical_inputs[case] for case in canonical_cases[:-1]},
        )

    missing_inputs = dict(canonical_inputs)
    missing_inputs.pop(canonical_cases[-1])
    with pytest.raises(ResourceControllerError, match="input manifest key mismatch"):
        harness._validate_claim_grade_competition_corpus(
            canonical_cases, missing_inputs
        )

    extra_case = "not-an-itc2019-instance"
    with pytest.raises(ResourceControllerError, match="case set mismatch"):
        harness._validate_claim_grade_competition_corpus(
            [*canonical_cases, extra_case],
            {**canonical_inputs, extra_case: "f" * 64},
        )

    with pytest.raises(ResourceControllerError, match="input manifest key mismatch"):
        harness._validate_claim_grade_competition_corpus(
            canonical_cases,
            {**canonical_inputs, extra_case: "f" * 64},
        )


def test_descriptive_subset_binding_is_explicitly_non_claim_grade() -> None:
    cases = [harness.COMPETITION_CASES[0]]
    inputs = {
        cases[0]: harness.CANONICAL_COMPETITION_INPUT_SHA256[cases[0]],
    }

    binding = harness._corpus_admission_binding(
        cases,
        inputs,
        execution_mode=harness.EVIDENCE_ONLY_CONTROLLER_MODE,
    )

    assert binding["claim_grade_ready"] is False
    assert binding["scope"] == "descriptive-selected-corpus"
    assert binding["selected_instance_count"] == 1
    assert binding["readiness_blocker"] == (
        "Descriptive corpus selection does not authorize claim-grade comparison."
    )


def test_claim_grade_manifest_replay_requires_canonical_bound_corpus() -> None:
    cases = list(harness.COMPETITION_CASES)
    inputs = dict(harness.CANONICAL_COMPETITION_INPUT_SHA256)
    manifest = {
        "instance_set": "competition",
        "cases": cases,
        "inputs": inputs,
        "corpus_admission": harness._corpus_admission_binding(
            cases,
            inputs,
            execution_mode=harness.CLAIM_GRADE_CONTROLLER_MODE,
        ),
    }

    harness._validate_claim_grade_corpus_manifest(manifest, verify_files=False)

    subset = {**manifest, "cases": cases[:-1]}
    with pytest.raises(ResourceControllerError, match="case set mismatch"):
        harness._validate_claim_grade_corpus_manifest(subset, verify_files=False)

    missing = {**manifest, "inputs": dict(inputs)}
    missing["inputs"].pop(cases[-1])
    with pytest.raises(ResourceControllerError, match="input manifest key mismatch"):
        harness._validate_claim_grade_corpus_manifest(missing, verify_files=False)

    extra = {**manifest, "inputs": {**inputs, "extra": "f" * 64}}
    with pytest.raises(ResourceControllerError, match="input manifest key mismatch"):
        harness._validate_claim_grade_corpus_manifest(extra, verify_files=False)

    rebound = {**manifest, "corpus_admission": dict(manifest["corpus_admission"])}
    rebound["corpus_admission"]["claim_grade_ready"] = False
    with pytest.raises(ResourceControllerError, match="admission binding mismatch"):
        harness._validate_claim_grade_corpus_manifest(rebound, verify_files=False)


def test_manifest_completeness_requires_exact_unique_record_set() -> None:
    expected = harness._expected_run_specs(["toy"], ["planora"], [17], 1)
    manifest = {"expected_runs": expected}

    harness._assert_complete_record_set([dict(expected[0])], manifest)
    with pytest.raises(ValueError, match="does not match"):
        harness._assert_complete_record_set([], manifest)
    with pytest.raises(ValueError, match="does not match"):
        harness._assert_complete_record_set(
            [dict(expected[0]), dict(expected[0])], manifest
        )


def test_resume_preserves_bound_official_validation(tmp_path: Path) -> None:
    root, manifest, record, _output = _checkpoint_fixture(tmp_path)

    assert harness._resume_records(root, manifest) == [record]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda record, output: record.update(run_id="wrong"), "run_id"),
        (
            lambda record, output: record.update(configured_solver_seconds=11.0),
            "manifest mismatch",
        ),
        (
            lambda record, output: output.write_text("changed", encoding="utf-8"),
            "output hash drift",
        ),
        (
            lambda record, output: record.update(
                output_path=str(output.parent / "result.json")
            ),
            "output path mismatch",
        ),
    ],
)
def test_resume_fails_closed_on_identity_config_or_output_drift(
    tmp_path: Path, mutation, message: str
) -> None:
    root, manifest, record, output = _checkpoint_fixture(tmp_path)
    mutation(record, output)
    _rewrite_checkpoint_result(root, record, rebind_state=True)

    with pytest.raises((ValueError, FileNotFoundError), match=message):
        harness._resume_records(root, manifest)


@pytest.mark.parametrize("replacement", [None, {"tampered": True}])
def test_resume_requires_exact_completed_state(
    tmp_path: Path, replacement: dict | None
) -> None:
    root, manifest, _record, _output = _checkpoint_fixture(tmp_path)
    state_path = next((root / "runs").glob("*/state.json"))
    if replacement is None:
        state_path.unlink()
        message = "state is unavailable"
    else:
        harness._write_json_atomic(state_path, replacement)
        message = "state schema mismatch"

    with pytest.raises(ValueError, match=message):
        harness._resume_records(root, manifest)


def test_resume_requires_completed_state_status(tmp_path: Path) -> None:
    root, manifest, _record, _output = _checkpoint_fixture(tmp_path)
    state_path = next((root / "runs").glob("*/state.json"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["status"] = "running"
    harness._write_json_atomic(state_path, state)

    with pytest.raises(ValueError, match="state is not complete"):
        harness._resume_records(root, manifest)


def test_resume_rejects_semantically_replaced_completed_state(tmp_path: Path) -> None:
    root, manifest, _record, _output = _checkpoint_fixture(tmp_path)
    state_path = next((root / "runs").glob("*/state.json"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["cpu_affinity"] = 1
    harness._write_json_atomic(state_path, state)

    with pytest.raises(ValueError, match="completed state mismatch"):
        harness._resume_records(root, manifest)


def test_resume_rejects_exact_persisted_result_replacement(tmp_path: Path) -> None:
    root, manifest, record, _output = _checkpoint_fixture(tmp_path)
    record["independent_validation"]["objective"]["total"] = 999999
    _rewrite_checkpoint_result(root, record, rebind_state=False)

    with pytest.raises(ValueError, match="result hash drift"):
        harness._resume_records(root, manifest)


def test_resume_recomputes_validation_and_rejects_999999_tamper(
    tmp_path: Path,
) -> None:
    root, manifest, record, _output = _checkpoint_fixture(tmp_path)
    record["independent_validation"]["objective"]["total"] = 999999
    _rewrite_checkpoint_result(root, record, rebind_state=True)

    with pytest.raises(ValueError, match="independent validation mismatch"):
        harness._resume_records(root, manifest)


def test_producer_artifact_contract_matches_summarizer_canonical_binding(
    tmp_path: Path,
) -> None:
    root = tmp_path / "matrix"
    identity = harness._run_identity("toy", "planora", 17, 1, seeds=[17], repetitions=1)
    output = root / "runs" / identity["run_id"] / "solution.xml"
    output.parent.mkdir(parents=True)
    output.write_text(TOY_SOLUTION, encoding="utf-8")

    metadata = harness._output_artifact_metadata(root, identity, output.resolve())
    row = {**identity, **metadata}

    assert metadata["output_relative_path"] == (
        f"runs/{identity['run_id']}/solution.xml"
    )
    assert metadata["artifact_binding_sha256"] == summarizer._artifact_binding(
        row,
        relative_path=metadata["output_relative_path"],
        output_sha256=metadata["output_sha256"],
    )


@pytest.mark.parametrize("path_kind", ["absolute", "traversal"])
def test_producer_rejects_artifacts_outside_matrix_root(
    tmp_path: Path, path_kind: str
) -> None:
    root = tmp_path / "matrix"
    root.mkdir()
    outside = tmp_path / "outside.xml"
    outside.write_text(TOY_SOLUTION, encoding="utf-8")
    identity = harness._run_identity("toy", "planora", 17, 1, seeds=[17], repetitions=1)
    candidate = outside.resolve()
    if path_kind == "traversal":
        candidate = root / "runs" / ".." / ".." / outside.name

    with pytest.raises(ValueError, match="escapes the matrix root"):
        harness._output_artifact_metadata(root, identity, candidate)


@pytest.mark.parametrize("run_id", ["../escape", "..\\escape", "C:/escape"])
def test_producer_rejects_path_shaped_run_ids(run_id: str) -> None:
    with pytest.raises(ValueError, match="cannot name a path"):
        harness._expected_output_relative_path({"run_id": run_id})


@pytest.mark.parametrize(
    "relative_path",
    ["../solution.xml", "C:/outside/solution.xml"],
)
def test_resume_rejects_traversal_or_absolute_output_relative_path(
    tmp_path: Path, relative_path: str
) -> None:
    root, manifest, record, _output = _checkpoint_fixture(tmp_path)
    record["output_relative_path"] = relative_path
    _rewrite_checkpoint_result(root, record, rebind_state=True)

    with pytest.raises(ValueError, match="output relative path mismatch"):
        harness._resume_records(root, manifest)


def test_resume_rejects_artifact_binding_mismatch(tmp_path: Path) -> None:
    root, manifest, record, _output = _checkpoint_fixture(tmp_path)
    record["artifact_binding_sha256"] = "0" * 64
    _rewrite_checkpoint_result(root, record, rebind_state=True)

    with pytest.raises(ValueError, match="artifact binding mismatch"):
        harness._resume_records(root, manifest)


class _ImmediateProcess:
    def __init__(self, command, *, write_output: bool, returncode: int, **_kwargs):
        self.pid = 12345
        self._returncode = returncode
        if write_output:
            output_flag = command.index("--output")
            Path(command[output_flag + 1]).write_text(TOY_SOLUTION, encoding="utf-8")

    def poll(self) -> int:
        return self._returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return self._returncode


@pytest.mark.parametrize(
    ("write_output", "returncode"),
    [(True, 0), (False, 7)],
)
def test_legacy_production_path_emits_bound_output_or_explicit_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_output: bool,
    returncode: int,
) -> None:
    root = tmp_path / "matrix"
    instance = tmp_path / "toy.xml"
    instance.write_text(TOY_PROBLEM, encoding="utf-8")
    identity = harness._run_identity("toy", "planora", 17, 1, seeds=[17], repetitions=1)
    monkeypatch.setattr(
        harness.subprocess,
        "Popen",
        lambda command, **kwargs: _ImmediateProcess(
            command,
            write_output=write_output,
            returncode=returncode,
            **kwargs,
        ),
    )

    row = harness._run_one(
        "planora",
        identity=identity,
        case="toy",
        instance_path=instance,
        root=root,
        seed=17,
        repetition=1,
        seconds=10.0,
        cpu=0,
        gashi=tmp_path / "gashi.dll",
        cps_root=tmp_path / "cpsolver",
        maxsat=tmp_path / "maxsat",
        maxsat_locale=tmp_path / "locale",
        resume_binding_sha256="1" * 64,
    )

    if write_output:
        assert row["output_relative_path"] == (
            f"runs/{identity['run_id']}/solution.xml"
        )
        assert row["artifact_binding_sha256"] == summarizer._artifact_binding(
            row,
            relative_path=row["output_relative_path"],
            output_sha256=row["output_sha256"],
        )
        assert row["independent_validation"]["feasible"] is True
    else:
        assert row["exit_code"] == 7
        assert row["output_path"] is None
        assert row["output_relative_path"] is None
        assert row["output_sha256"] is None
        assert row["artifact_binding_sha256"] is None
        assert row["independent_validation"]["status"] == (
            harness._NO_ARTIFACT_VALIDATION_STATUS
        )
        assert row["independent_validation"]["feasible"] is None
        assert "unknown" in row["independent_validation"]["errors"][0]
        assert "independent feasible status is not Boolean" in (
            summarizer._local_validation_errors(row)
        )


def _controller_profile() -> ResourceProfile:
    return ResourceProfile(
        wall_time_seconds=10.0,
        artifact_grace_seconds=1.0,
        memory_bytes=128 * 1024 * 1024,
        memory_swap_bytes=128 * 1024 * 1024,
        cpuset_cpus="0",
        pids_limit=64,
    )


def _controller_binding(tmp_path: Path, profile: ResourceProfile) -> dict:
    supervisor = tmp_path / "supervisor"
    supervisor.write_bytes(b"trusted-supervisor")
    config_path = tmp_path / "controller.json"
    config_path.write_text("{}", encoding="utf-8")
    capabilities = {"bound": True}
    solver_argv = {
        "planora": list(harness.CLAIM_GRADE_ARGV_TEMPLATE_CONTRACTS["planora"])
    }
    return {
        "mode": harness.EVIDENCE_ONLY_CONTROLLER_MODE,
        "config_path": str(config_path.resolve()),
        "config_sha256": harness._sha256(config_path),
        "controller_version": harness.CONTROLLER_VERSION,
        "controller_source_sha256": harness._sha256(
            harness.ROOT / "benchmarks/itc2019_resource_controller.py"
        ),
        "profile": profile.to_canonical_dict(),
        "profile_sha256": profile.sha256,
        "capability_evidence": capabilities,
        "capability_sha256": harness._json_sha256(capabilities),
        "capability_refresh": None,
        "capability_refresh_sha256": None,
        "preflight_capability_snapshot": capabilities,
        "preflight_capability_snapshot_sha256": harness._json_sha256(capabilities),
        "post_exit_cgroup_probe": None,
        "post_exit_cgroup_probe_sha256": None,
        "supervisor_path": str(supervisor.resolve()),
        "supervisor_sha256": harness._sha256(supervisor),
        "solver_images": {"planora": "sha256:" + "4" * 64},
        "competitor_provenance": None,
        "competitor_provenance_binding_sha256": None,
        "solver_argv": solver_argv,
        "solver_argv_sha256": harness._json_sha256(solver_argv),
        "equal_wall_time_claim": False,
        "equal_memory_limit_claim": False,
        "claim_grade_ready": False,
        "execution_admission_ready": False,
        "claim_evidence_set_sha256": None,
        "readiness_blocker": "incomplete trusted evidence",
    }


def _test_competitor_provenance_binding(
    schema: str,
    *,
    manifest_path: Path,
    size_bytes: int | float | bool = 1,
) -> dict:
    file_attestation = {"path": "gashi-sa/source.tar", "sha256": "a" * 64}
    license_attestation = {
        "spdx": "MIT",
        "path": "gashi-sa/LICENSE",
        "sha256": "b" * 64,
    }
    build = {
        "recipe": {"path": "gashi-sa/Dockerfile", "sha256": "c" * 64},
        "adapter": {"path": "gashi-sa/adapter", "sha256": "d" * 64},
        "receipt": {"path": "gashi-sa/receipt.json", "sha256": "e" * 64},
        "receipt_payload_sha256": "f" * 64,
    }
    if schema == "planora.itc2019.competitor-provenance.v1":
        solver = {
            "upstream": {
                "repository_url": "https://github.com/example/gashi",
                "commit_sha": "1" * 40,
                "source_archive": file_attestation,
            },
            "license": license_attestation,
            "build": build,
            "image_digest": "sha256:" + "2" * 64,
        }
    else:
        solver = {
            "upstreams": [
                {
                    "repository_url": "https://github.com/example/gashi",
                    "commit_sha": "1" * 40,
                    "source_archive": {
                        **file_attestation,
                        "size_bytes": size_bytes,
                    },
                    "license": license_attestation,
                }
            ],
            "build": build,
            "image_digest": "sha256:" + "2" * 64,
        }
    canonical = {
        "schema": schema,
        "manifest_sha256": "3" * 64,
        "solvers": {"gashi-sa": solver},
    }
    return {
        **canonical,
        "binding_sha256": harness._json_sha256(canonical),
        "manifest_path": str(manifest_path),
    }


def _claim_reconciliation_fixture(schema: str) -> tuple[dict, object, dict]:
    argv = list(harness.CLAIM_GRADE_ARGV_TEMPLATE_CONTRACTS["gashi-sa"])
    provenance = _test_competitor_provenance_binding(
        schema,
        manifest_path=Path("C:/custody/manifest.json"),
    )
    controller = {
        "solver_images": {"gashi-sa": "sha256:" + "2" * 64},
        "solver_argv": {"gashi-sa": argv},
        "competitor_provenance": provenance,
        "competitor_provenance_binding_sha256": provenance["binding_sha256"],
    }
    runtime_binding = json.loads(json.dumps(controller))
    runtime = harness.ClaimGradeControllerRuntime(
        controller=object(),
        manifest_binding=runtime_binding,
        supervisor_path=Path("unused"),
        solver_argv_templates={"gashi-sa": tuple(argv)},
    )
    manifest = {
        "solvers": ["gashi-sa"],
        "expected_runs": [{"run_id": "gashi-run", "solver": "gashi-sa"}],
    }
    return controller, runtime, manifest


def _resume_external_binding(tmp_path: Path, schema: str) -> tuple[dict, dict]:
    binding = _controller_binding(tmp_path, _controller_profile())
    argv = {"gashi-sa": list(harness.CLAIM_GRADE_ARGV_TEMPLATE_CONTRACTS["gashi-sa"])}
    binding["solver_images"] = {"gashi-sa": "sha256:" + "2" * 64}
    binding["solver_argv"] = argv
    binding["solver_argv_sha256"] = harness._json_sha256(argv)
    manifest_path = tmp_path / f"competitor-{schema.rsplit('.', 1)[-1]}.json"
    manifest_path.write_text("{}\n", encoding="utf-8")
    provenance = _test_competitor_provenance_binding(
        schema,
        manifest_path=manifest_path.resolve(),
    )
    binding["competitor_provenance"] = provenance
    binding["competitor_provenance_binding_sha256"] = provenance["binding_sha256"]
    return binding, provenance


@pytest.mark.parametrize("solver", sorted(harness.EXPLICITLY_SEEDED_SOLVERS))
def test_claim_grade_controller_rejects_seeded_template_without_seed(
    solver: str,
) -> None:
    template = list(harness.CLAIM_GRADE_ARGV_TEMPLATE_CONTRACTS[solver])
    seed_index = template.index("--seed")
    del template[seed_index : seed_index + 2]
    payload = {solver: template}

    with pytest.raises(
        ResourceControllerError,
        match=f"pinned complete argv contract for solver: {solver}",
    ):
        harness._validate_controller_argv_templates(
            payload,
            [solver],
            require_seed_binding=True,
        )


@pytest.mark.parametrize(
    "solver",
    ("planora", "gashi-sa", "unitime-cpsolver"),
)
def test_claim_grade_controller_accepts_exact_adapter_seed_binding(
    solver: str,
) -> None:
    payload = {solver: list(harness.CLAIM_GRADE_ARGV_TEMPLATE_CONTRACTS[solver])}

    selected = harness._validate_controller_argv_templates(
        payload,
        [solver],
        require_seed_binding=True,
    )

    assert selected[solver] == harness.CLAIM_GRADE_ARGV_TEMPLATE_CONTRACTS[solver]


def test_claim_grade_controller_accepts_seeded_templates_and_unseeded_maxsat() -> None:
    payload = {
        solver: list(harness.CLAIM_GRADE_ARGV_TEMPLATE_CONTRACTS[solver])
        for solver in harness.DEFAULT_SOLVERS
    }
    solvers = list(harness.DEFAULT_SOLVERS)

    selected = harness._validate_controller_argv_templates(
        payload,
        solvers,
        require_seed_binding=True,
    )

    assert set(selected) == set(solvers)
    assert selected == {
        solver: harness.CLAIM_GRADE_ARGV_TEMPLATE_CONTRACTS[solver]
        for solver in solvers
    }
    assert "{seed}" not in selected["lemos-maxsat"]


@pytest.mark.parametrize(
    "shadow",
    (
        ("--seed", "999"),
        ("--seed=999",),
        ("--random-seed", "999"),
        ("--random-seed=999",),
        ("--seed-value", "999"),
        ("--seed-value=999",),
        ("--SEED", "999"),
        ("--Seed=999",),
        ("-s", "999"),
        ("-r=999",),
    ),
)
@pytest.mark.parametrize("position", ("before", "after"))
@pytest.mark.parametrize("solver", sorted(harness.EXPLICITLY_SEEDED_SOLVERS))
def test_claim_grade_controller_rejects_canonical_plus_shadow_seed_control(
    solver: str,
    position: str,
    shadow: tuple[str, ...],
) -> None:
    template = list(harness.CLAIM_GRADE_ARGV_TEMPLATE_CONTRACTS[solver])
    if position == "before":
        seed_index = template.index("--seed")
        template[seed_index:seed_index] = shadow
    else:
        template.extend(shadow)
    payload = {solver: template}

    with pytest.raises(
        ResourceControllerError,
        match=f"pinned complete argv contract for solver: {solver}",
    ):
        harness._validate_controller_argv_templates(
            payload,
            [solver],
            require_seed_binding=True,
        )


@pytest.mark.parametrize(
    "seed_control",
    (
        ("--seed", "999"),
        ("--seed=999",),
        ("--random-seed", "999"),
        ("--random-seed=999",),
        ("--seed-value", "999"),
        ("--seed-value=999",),
        ("--SEED", "999"),
        ("--Seed=999",),
        ("-s", "999"),
        ("-r=999",),
    ),
)
def test_claim_grade_controller_rejects_every_maxsat_seed_control(
    seed_control: tuple[str, ...],
) -> None:
    template = list(harness.CLAIM_GRADE_ARGV_TEMPLATE_CONTRACTS["lemos-maxsat"])
    template.extend(seed_control)
    payload = {"lemos-maxsat": template}

    with pytest.raises(
        ResourceControllerError,
        match="pinned complete argv contract for solver: lemos-maxsat",
    ):
        harness._validate_controller_argv_templates(
            payload,
            ["lemos-maxsat"],
            require_seed_binding=True,
        )


@pytest.mark.parametrize("solver", harness.DEFAULT_SOLVERS)
def test_claim_grade_controller_rejects_unknown_or_reordered_options(
    solver: str,
) -> None:
    canonical = list(harness.CLAIM_GRADE_ARGV_TEMPLATE_CONTRACTS[solver])
    invalid_templates = [
        [*canonical, "--unknown", "value"],
        [canonical[0], "--output", *canonical[2:]],
        ["unknown-adapter", *canonical[1:]],
    ]

    for template in invalid_templates:
        with pytest.raises(
            ResourceControllerError,
            match=f"pinned complete argv contract for solver: {solver}",
        ):
            harness._validate_controller_argv_templates(
                {solver: template},
                [solver],
                require_seed_binding=True,
            )


@pytest.mark.parametrize("solver", harness.DEFAULT_SOLVERS)
def test_claim_grade_executed_argv_must_match_expanded_contract(solver: str) -> None:
    template = harness.CLAIM_GRADE_ARGV_TEMPLATE_CONTRACTS[solver]
    rendered = harness._render_controller_argv(template, seed=17, seconds=10.0)

    harness._validate_claim_grade_executed_argv(
        rendered,
        solver,
        seed=17,
        seconds=10.0,
    )

    with pytest.raises(
        ResourceControllerError,
        match=f"rendered controller argv.*solver: {solver}",
    ):
        harness._validate_claim_grade_executed_argv(
            (*rendered, "--seed=999"),
            solver,
            seed=17,
            seconds=10.0,
        )


def test_evidence_only_controller_preserves_descriptive_seedless_template() -> None:
    payload = {"planora": ["solver", "--input", "{input}", "--output", "{output}"]}

    selected = harness._validate_controller_argv_templates(
        payload,
        ["planora"],
        require_seed_binding=False,
    )

    assert selected["planora"] == tuple(payload["planora"])


def test_claim_grade_preflight_rejects_missing_seed_before_capability_work(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "controller.json"
    config_path.write_text(
        json.dumps(
            {
                "schema": harness.CLAIM_GRADE_CONTROLLER_CONFIG_SCHEMA,
                "solver_argv": {
                    "planora": [
                        "solver",
                        "--input",
                        "{input}",
                        "--output",
                        "{output}",
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ResourceControllerError,
        match="pinned complete argv contract for solver: planora",
    ):
        harness._claim_grade_controller_preflight(
            config_path,
            solvers=["planora"],
            seconds=10.0,
            cpu=0,
        )


@pytest.mark.parametrize(
    "payload, error",
    [
        ('{"schema":"first","schema":"second"}', "duplicate JSON member"),
        ('{"value":NaN}', "non-standard JSON constant"),
    ],
)
def test_controller_json_reader_rejects_ambiguous_json(
    tmp_path: Path, payload: str, error: str
) -> None:
    config_path = tmp_path / "ambiguous-controller.json"
    config_path.write_text(payload, encoding="utf-8")

    with pytest.raises(ResourceControllerError, match=error):
        harness._read_json_object(config_path, "claim-grade controller config")


def test_claim_finalization_refreshes_external_competitor_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "provenance.json"
    manifest_path.write_text("{}\n", encoding="utf-8")
    expected = {
        "schema": "planora.itc2019.competitor-provenance.v1",
        "manifest_sha256": harness._sha256(manifest_path),
        "solvers": {"gashi-sa": {"verified": True}},
        "binding_sha256": "7" * 64,
        "manifest_path": str(manifest_path.resolve()),
    }
    controller = {
        "solver_images": {"gashi-sa": "sha256:" + "8" * 64},
        "competitor_provenance": expected,
        "competitor_provenance_binding_sha256": "7" * 64,
    }
    observed_calls: list[tuple[Path, list[str], dict[str, str]]] = []

    def fake_verify(
        path: Path,
        *,
        expected_solvers: list[str],
        selected_images: dict[str, str],
    ) -> dict:
        observed_calls.append((path, expected_solvers, selected_images))
        return expected

    monkeypatch.setattr(harness, "verify_competitor_provenance", fake_verify)
    harness._refresh_competitor_provenance_for_claims(controller)
    assert observed_calls == [
        (
            manifest_path.resolve(),
            ["gashi-sa"],
            {"gashi-sa": "sha256:" + "8" * 64},
        )
    ]

    monkeypatch.setattr(
        harness,
        "verify_competitor_provenance",
        lambda *_args, **_kwargs: {**expected, "manifest_sha256": "9" * 64},
    )
    with pytest.raises(ResourceControllerError, match="binding drift"):
        harness._refresh_competitor_provenance_for_claims(controller)


def test_claim_finalization_provenance_refresh_rejects_bool_int_coercion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "provenance-v2.json"
    manifest_path.write_text("{}\n", encoding="utf-8")
    expected = {
        "schema": "planora.itc2019.competitor-provenance.v2",
        "manifest_sha256": harness._sha256(manifest_path),
        "solvers": {
            "unitime-cpsolver": {"upstreams": [{"source_archive": {"size_bytes": 1}}]}
        },
        "binding_sha256": "7" * 64,
        "manifest_path": str(manifest_path.resolve()),
    }
    refreshed = json.loads(json.dumps(expected))
    refreshed["solvers"]["unitime-cpsolver"]["upstreams"][0]["source_archive"][
        "size_bytes"
    ] = True
    controller = {
        "solver_images": {"unitime-cpsolver": "sha256:" + "8" * 64},
        "competitor_provenance": expected,
        "competitor_provenance_binding_sha256": "7" * 64,
    }
    monkeypatch.setattr(
        harness,
        "verify_competitor_provenance",
        lambda *_args, **_kwargs: refreshed,
    )

    with pytest.raises(ResourceControllerError, match="binding drift"):
        harness._refresh_competitor_provenance_for_claims(controller)


def test_claim_finalization_rejects_external_solver_list_shrink() -> None:
    controller = {
        "solver_images": {
            "planora": "sha256:" + "1" * 64,
            "gashi-sa": "sha256:" + "2" * 64,
        },
        "solver_argv": {
            "planora": ["planora"],
            "gashi-sa": ["gashi"],
        },
    }
    runtime = harness.ClaimGradeControllerRuntime(
        controller=object(),
        manifest_binding=controller,
        supervisor_path=Path("unused"),
        solver_argv_templates={
            "planora": ("planora",),
            "gashi-sa": ("gashi",),
        },
    )
    manifest = {
        "solvers": ["planora"],
        "expected_runs": [
            {"run_id": "planora-run", "solver": "planora"},
            {"run_id": "gashi-run", "solver": "gashi-sa"},
        ],
    }

    with pytest.raises(ResourceControllerError, match="solver-set mismatch"):
        harness._claim_finalization_solver_set(manifest, controller, runtime)


def test_claim_finalization_rejects_runtime_image_value_divergence() -> None:
    controller = {
        "solver_images": {
            "planora": "sha256:" + "1" * 64,
            "gashi-sa": "sha256:" + "2" * 64,
        },
        "solver_argv": {
            "planora": ["planora"],
            "gashi-sa": ["gashi"],
        },
        "competitor_provenance": {"binding_sha256": "3" * 64},
        "competitor_provenance_binding_sha256": "3" * 64,
    }
    runtime_binding = json.loads(json.dumps(controller))
    runtime_binding["solver_images"]["gashi-sa"] = "sha256:" + "4" * 64
    runtime = harness.ClaimGradeControllerRuntime(
        controller=object(),
        manifest_binding=runtime_binding,
        supervisor_path=Path("unused"),
        solver_argv_templates={
            "planora": ("planora",),
            "gashi-sa": ("gashi",),
        },
    )
    manifest = {
        "solvers": ["planora", "gashi-sa"],
        "expected_runs": [
            {"run_id": "planora-run", "solver": "planora"},
            {"run_id": "gashi-run", "solver": "gashi-sa"},
        ],
    }

    with pytest.raises(ResourceControllerError, match="solver-set mismatch"):
        harness._claim_finalization_solver_set(manifest, controller, runtime)


@pytest.mark.parametrize(
    "schema",
    (
        "planora.itc2019.competitor-provenance.v1",
        "planora.itc2019.competitor-provenance.v2",
    ),
)
def test_claim_finalization_accepts_exact_controller_runtime_provenance(
    schema: str,
) -> None:
    controller, runtime, manifest = _claim_reconciliation_fixture(schema)

    assert harness._claim_finalization_solver_set(manifest, controller, runtime) == [
        "gashi-sa"
    ]


@pytest.mark.parametrize("runtime_size", (True, 1.0))
def test_claim_finalization_rejects_controller_runtime_numeric_coercion(
    runtime_size: bool | float,
) -> None:
    controller, runtime, manifest = _claim_reconciliation_fixture(
        "planora.itc2019.competitor-provenance.v2"
    )
    runtime.manifest_binding["competitor_provenance"]["solvers"]["gashi-sa"][
        "upstreams"
    ][0]["source_archive"]["size_bytes"] = runtime_size

    with pytest.raises(ResourceControllerError, match="solver-set mismatch"):
        harness._claim_finalization_solver_set(manifest, controller, runtime)


def test_controller_preflight_binds_config_and_stays_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = _controller_profile()
    supervisor = tmp_path / "supervisor"
    supervisor.write_bytes(b"trusted-supervisor")
    initial_captured_at = harness.time.time_ns() - 2_000_000_000
    capabilities = {
        "schema": CAPABILITY_EVIDENCE_SCHEMA,
        "docker_available": True,
        "server_os": "linux",
        "cgroup_version": 2,
        "supports_memory_limit": True,
        "supports_swap_limit": True,
        "supports_cpu_quota": True,
        "supports_cpuset": True,
        "supports_pids_limit": True,
        "supports_read_only_rootfs": True,
        "total_memory_bytes": 1024 * 1024 * 1024,
        "available_swap_bytes": 0,
        "available_cpuset_cpus": "0",
        "daemon_id": "6" * 64,
        "docker_context": "test-context",
        "captured_at_unix_ns": initial_captured_at,
    }
    refreshed = {**capabilities, "captured_at_unix_ns": harness.time.time_ns()}
    refresh_script = tmp_path / "refresh.py"
    refresh_script.write_text(
        "import json\nprint(json.dumps(" + repr(refreshed) + "))\n",
        encoding="utf-8",
    )
    cgroup_probe_script = tmp_path / "cgroup_probe.py"
    cgroup_probe_script.write_text("print('{}')\n", encoding="utf-8")
    config = {
        "schema": harness.CLAIM_GRADE_CONTROLLER_CONFIG_SCHEMA,
        "profile": profile.to_canonical_dict(),
        "capability_evidence": capabilities,
        "capability_refresh": {
            "schema": harness.CAPABILITY_REFRESH_CONFIG_SCHEMA,
            "argv": [harness.sys.executable, str(refresh_script)],
            "bound_files": [
                {
                    "path": str(refresh_script),
                    "sha256": harness._sha256(refresh_script),
                }
            ],
            "timeout_seconds": 5,
        },
        "post_exit_cgroup_probe": {
            "schema": harness.POST_EXIT_CGROUP_PROBE_CONFIG_SCHEMA,
            "argv": [
                harness.sys.executable,
                str(cgroup_probe_script),
                "{container_id}",
            ],
            "bound_files": [
                {
                    "path": str(cgroup_probe_script),
                    "sha256": harness._sha256(cgroup_probe_script),
                }
            ],
            "timeout_seconds": 5,
        },
        "supervisor_path": str(supervisor),
        "supervisor_sha256": harness._sha256(supervisor),
        "solver_images": {
            "planora": "sha256:" + "4" * 64,
            "gashi-sa": "sha256:" + "5" * 64,
        },
        "solver_argv": {
            "planora": list(harness.CLAIM_GRADE_ARGV_TEMPLATE_CONTRACTS["planora"]),
            "gashi-sa": list(harness.CLAIM_GRADE_ARGV_TEMPLATE_CONTRACTS["gashi-sa"]),
        },
    }
    provenance_manifest = tmp_path / "competitor-provenance.json"
    provenance_manifest.write_text("{}\n", encoding="utf-8")
    provenance_manifest_sha256 = harness._sha256(provenance_manifest)
    config["competitor_provenance"] = {
        "manifest_path": str(provenance_manifest),
        "manifest_sha256": provenance_manifest_sha256,
    }
    config_path = tmp_path / "controller.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    no_refresh = dict(config)
    no_refresh.pop("capability_refresh")
    no_refresh_path = tmp_path / "controller-no-refresh.json"
    no_refresh_path.write_text(json.dumps(no_refresh), encoding="utf-8")
    with pytest.raises(ResourceControllerError, match="requires capability refresh"):
        harness._claim_grade_controller_preflight(
            no_refresh_path, solvers=["planora"], seconds=10.0, cpu=0
        )
    no_cgroup = dict(config)
    no_cgroup.pop("post_exit_cgroup_probe")
    no_cgroup_path = tmp_path / "controller-no-cgroup.json"
    no_cgroup_path.write_text(json.dumps(no_cgroup), encoding="utf-8")
    with pytest.raises(ResourceControllerError, match="post-exit cgroup probe"):
        harness._claim_grade_controller_preflight(
            no_cgroup_path, solvers=["planora"], seconds=10.0, cpu=0
        )

    runtime = harness._claim_grade_controller_preflight(
        config_path, solvers=["planora"], seconds=10.0, cpu=0
    )

    binding = runtime.manifest_binding
    assert binding["mode"] == harness.CLAIM_GRADE_CONTROLLER_MODE
    assert binding["claim_grade_ready"] is False
    assert binding["execution_admission_ready"] is True
    assert binding["config_sha256"] == harness._sha256(config_path)
    assert binding["profile_sha256"] == profile.sha256
    assert binding["capability_evidence"] == runtime.controller.capability_evidence
    assert binding["supervisor_sha256"] == harness._sha256(supervisor)
    assert binding["solver_images"]["planora"].startswith("sha256:")
    assert binding["competitor_provenance"] is None

    expected_provenance = {
        "schema": "planora.itc2019.competitor-provenance.v1",
        "manifest_sha256": provenance_manifest_sha256,
        "solvers": {"gashi-sa": {"verified": True}},
        "binding_sha256": "6" * 64,
        "manifest_path": str(provenance_manifest.resolve()),
    }

    def fake_verify_competitor_provenance(
        path: Path,
        *,
        expected_solvers: list[str],
        selected_images: dict[str, str],
    ) -> dict:
        assert path == provenance_manifest.resolve()
        assert expected_solvers == ["gashi-sa"]
        assert selected_images == {"gashi-sa": "sha256:" + "5" * 64}
        return expected_provenance

    monkeypatch.setattr(
        harness,
        "verify_competitor_provenance",
        fake_verify_competitor_provenance,
    )
    external_runtime = harness._claim_grade_controller_preflight(
        config_path,
        solvers=["planora", "gashi-sa"],
        seconds=10.0,
        cpu=0,
    )
    assert external_runtime.manifest_binding["competitor_provenance"] == (
        expected_provenance
    )
    assert (
        external_runtime.manifest_binding["competitor_provenance_binding_sha256"]
        == "6" * 64
    )

    missing_provenance = dict(config)
    missing_provenance.pop("competitor_provenance")
    missing_provenance_path = tmp_path / "controller-missing-provenance.json"
    missing_provenance_path.write_text(json.dumps(missing_provenance), encoding="utf-8")
    with pytest.raises(ResourceControllerError, match="requires competitor provenance"):
        harness._claim_grade_controller_preflight(
            missing_provenance_path,
            solvers=["planora", "gashi-sa"],
            seconds=10.0,
            cpu=0,
        )

    evidence_runtime = harness._claim_grade_controller_preflight(
        config_path,
        solvers=["planora"],
        seconds=10.0,
        cpu=0,
        execution_mode=harness.EVIDENCE_ONLY_CONTROLLER_MODE,
    )
    assert evidence_runtime.manifest_binding["mode"] == (
        harness.EVIDENCE_ONLY_CONTROLLER_MODE
    )
    assert evidence_runtime.manifest_binding["claim_grade_ready"] is False

    refresh_script.write_text("print('{}')\n", encoding="utf-8")
    with pytest.raises(ResourceControllerError, match="bound file hash drift"):
        runtime.controller.refresh_capability_evidence()


def test_capability_refresh_config_requires_hash_bound_file_arguments(
    tmp_path: Path,
) -> None:
    script = tmp_path / "refresh.py"
    script.write_text("print('{}')\n", encoding="utf-8")
    config = {
        "schema": harness.CAPABILITY_REFRESH_CONFIG_SCHEMA,
        "argv": [harness.sys.executable, str(script)],
        "bound_files": [],
        "timeout_seconds": 5,
    }

    with pytest.raises(ResourceControllerError, match="must be hash-bound"):
        harness._capability_refresh_provider(config, config_directory=tmp_path)

    cgroup_config = {
        "schema": harness.POST_EXIT_CGROUP_PROBE_CONFIG_SCHEMA,
        "argv": [harness.sys.executable, str(script), "{container_id}"],
        "bound_files": [],
        "timeout_seconds": 5,
    }
    with pytest.raises(ResourceControllerError, match="must be hash-bound"):
        harness._post_exit_cgroup_probe_provider(
            cgroup_config, config_directory=tmp_path
        )

    config["bound_files"] = [{"path": str(script), "sha256": "0" * 64}]
    with pytest.raises(ResourceControllerError, match="bound file hash mismatch"):
        harness._capability_refresh_provider(config, config_directory=tmp_path)


def test_post_exit_cgroup_probe_renders_only_bound_identity_placeholders(
    tmp_path: Path,
) -> None:
    script = tmp_path / "cgroup_probe.py"
    script.write_text(
        "import json, sys\nprint(json.dumps({'args': sys.argv[1:]}))\n",
        encoding="utf-8",
    )
    config = {
        "schema": harness.POST_EXIT_CGROUP_PROBE_CONFIG_SCHEMA,
        "argv": [
            harness.sys.executable,
            str(script),
            "{run_id}",
            "{container_id}",
            "{container_name}",
            "{image_id}",
        ],
        "bound_files": [{"path": str(script), "sha256": harness._sha256(script)}],
        "timeout_seconds": 5,
    }
    provider, binding = harness._post_exit_cgroup_probe_provider(
        config, config_directory=tmp_path
    )
    invocation = SolverInvocation(
        run_id="run-a",
        solver="planora",
        image="sha256:" + "4" * 64,
        argv=("solver",),
        host_run_directory=str(tmp_path),
    )
    inspect = {
        "Id": "7" * 64,
        "Name": "/container-a",
        "Image": "sha256:" + "4" * 64,
    }

    assert provider is not None
    assert binding is not None
    assert provider(invocation, inspect) == {
        "args": [
            "run-a",
            "7" * 64,
            "container-a",
            "sha256:" + "4" * 64,
        ]
    }


def _allow_synthetic_claim_corpus(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep non-corpus controller tests focused on their original boundary."""

    monkeypatch.setattr(
        harness,
        "_validate_claim_grade_corpus_manifest",
        lambda *_args, **_kwargs: None,
    )


def test_claim_finalization_refuses_partial_or_descriptive_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_synthetic_claim_corpus(monkeypatch)
    manifest = {
        "resource_controller": {"mode": harness.CLAIM_GRADE_CONTROLLER_MODE},
        "expected_runs": [{"run_id": "run-a"}],
    }
    record = {
        "run_id": "run-a",
        "resource_evidence": {
            "schema": harness.DESCRIPTIVE_RESOURCE_EVIDENCE_SCHEMA,
            "claim_grade_ready": False,
        },
        "resource_evidence_sha256": "0" * 64,
        "equal_wall_time_claim": False,
        "equal_memory_limit_claim": False,
    }

    with pytest.raises(ResourceControllerError, match="authoritative evidence"):
        harness._finalize_controller_claims(manifest, [record], root=tmp_path)


def test_claim_finalization_rejects_deserialized_claim_without_live_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_synthetic_claim_corpus(monkeypatch)
    manifest = {
        "resource_controller": {"mode": harness.CLAIM_GRADE_CONTROLLER_MODE},
        "expected_runs": [{"run_id": "run-a"}],
    }
    evidence = {
        "schema": harness.RESOURCE_EVIDENCE_SCHEMA,
        "run_id": "run-a",
        "claim_grade_ready": True,
    }
    record = {
        "run_id": "run-a",
        "resource_evidence": evidence,
        "resource_evidence_sha256": harness.resource_evidence_sha256(evidence),
        "equal_wall_time_claim": True,
        "equal_memory_limit_claim": True,
    }

    class RejectingController:
        @staticmethod
        def authorizes_claim_grade_evidence(_evidence):
            return False

    runtime = harness.ClaimGradeControllerRuntime(
        controller=RejectingController(),
        manifest_binding=manifest["resource_controller"],
        supervisor_path=Path("unused"),
        solver_argv_templates={},
    )

    with pytest.raises(ResourceControllerError, match="authoritative evidence"):
        harness._finalize_controller_claims(
            manifest, [record], root=tmp_path, controller_runtime=runtime
        )


def _claim_finalization_replay_fixture(tmp_path: Path):
    root = tmp_path / "matrix"
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    profile = _controller_profile()
    binding = _controller_binding(tmp_path, profile)
    binding.update(
        {
            "mode": harness.CLAIM_GRADE_CONTROLLER_MODE,
            "execution_admission_ready": True,
        }
    )
    identities = []
    for run_id, case in (("run-a", "toy-a"), ("run-b", "toy-b")):
        instance = (input_root / f"{case}.xml").resolve()
        instance.write_text(TOY_PROBLEM, encoding="utf-8")
        identity = {
            "run_id": run_id,
            "case": case,
            "solver": "planora",
            "seed": 17,
            "effective_seed": 17,
            "seed_control": "explicit",
            "seed_pairing_group": 17,
            "repetition": 1,
            "unseeded_trial": None,
        }
        identities.append(identity)
        (root / "runs" / run_id).mkdir(parents=True)

    manifest = {
        "resource_controller": binding,
        "expected_runs": identities,
        "input_root": str(input_root.resolve()),
        "inputs": {
            identity["case"]: harness._sha256(input_root / f"{identity['case']}.xml")
            for identity in identities
        },
        "seeds": [17],
        "repetitions": 1,
        "configured_solver_seconds": 10.0,
    }

    class AuthorizingController:
        def __init__(self):
            self.authorized = set()

        def authorizes_claim_grade_evidence(self, evidence):
            return harness.resource_evidence_sha256(evidence) in self.authorized

        @staticmethod
        def container_name(invocation):
            return f"container-{invocation.run_id}"

    controller = AuthorizingController()
    runtime = harness.ClaimGradeControllerRuntime(
        controller=controller,
        manifest_binding=binding,
        supervisor_path=Path(binding["supervisor_path"]),
        solver_argv_templates={"planora": tuple(binding["solver_argv"]["planora"])},
    )
    records = []
    for index, identity in enumerate(identities, start=1):
        run_dir = (root / "runs" / identity["run_id"]).resolve()
        invocation = harness._controller_invocation(
            runtime,
            identity=identity,
            solver="planora",
            instance_path=input_root / f"{identity['case']}.xml",
            run_dir=run_dir,
            seed=17,
            seconds=10.0,
            capability_snapshot_sha256=str(index) * 64,
        )
        evidence = {
            "schema": harness.RESOURCE_EVIDENCE_SCHEMA,
            "run_id": identity["run_id"],
            "invocation": invocation.to_canonical_dict(),
            "invocation_sha256": invocation.sha256,
            "execution": {"run_id": identity["run_id"]},
            "capability_snapshot_sha256": str(index) * 64,
            "container_id": str(index + 2) * 64,
            "container_name": f"container-{identity['run_id']}",
            "cgroup_path": f"/docker/{str(index + 2) * 64}",
            "cgroup_identity": str(index + 4) * 64,
            "claim_grade_ready": True,
        }
        evidence_sha256 = harness.resource_evidence_sha256(evidence)
        controller.authorized.add(evidence_sha256)
        records.append(
            {
                **identity,
                "controller_invocation": invocation.to_canonical_dict(),
                "controller_invocation_sha256": invocation.sha256,
                "resource_evidence_path": str(run_dir / "resource-evidence.json"),
                "resource_evidence": evidence,
                "resource_evidence_sha256": evidence_sha256,
                "equal_wall_time_claim": True,
                "equal_memory_limit_claim": True,
            }
        )
    return root, manifest, runtime, records


@pytest.mark.parametrize(
    "swap",
    ("run_id", "invocation", "invocation_sha256", "whole_evidence"),
)
def test_claim_finalization_rejects_cross_run_evidence_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, swap: str
) -> None:
    _allow_synthetic_claim_corpus(monkeypatch)
    root, manifest, runtime, records = _claim_finalization_replay_fixture(tmp_path)
    run_a = records[0]["resource_evidence"]
    run_b = records[1]["resource_evidence"]
    if swap == "whole_evidence":
        forged = json.loads(json.dumps(run_a))
    else:
        forged = json.loads(json.dumps(run_b))
        forged[swap] = json.loads(json.dumps(run_a[swap]))
    records[1]["resource_evidence"] = forged
    records[1]["resource_evidence_sha256"] = harness.resource_evidence_sha256(forged)
    runtime.controller.authorized.add(records[1]["resource_evidence_sha256"])

    with pytest.raises(ResourceControllerError, match="run|invocation|duplicate"):
        harness._finalize_controller_claims(
            manifest, records, root=root, controller_runtime=runtime
        )


@pytest.mark.parametrize(
    "field", ("container_id", "container_name", "cgroup_path", "cgroup_identity")
)
def test_claim_finalization_rejects_reused_controller_run_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    _allow_synthetic_claim_corpus(monkeypatch)
    root, manifest, runtime, records = _claim_finalization_replay_fixture(tmp_path)
    forged = json.loads(json.dumps(records[1]["resource_evidence"]))
    forged[field] = records[0]["resource_evidence"][field]
    records[1]["resource_evidence"] = forged
    records[1]["resource_evidence_sha256"] = harness.resource_evidence_sha256(forged)
    runtime.controller.authorized.add(records[1]["resource_evidence_sha256"])

    with pytest.raises(ResourceControllerError, match="identity"):
        harness._finalize_controller_claims(
            manifest, records, root=root, controller_runtime=runtime
        )


def test_claim_finalization_accepts_distinct_manifest_bound_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_synthetic_claim_corpus(monkeypatch)
    root, manifest, runtime, records = _claim_finalization_replay_fixture(tmp_path)

    harness._finalize_controller_claims(
        manifest, records, root=root, controller_runtime=runtime
    )

    assert manifest["resource_controller"]["claim_grade_ready"] is True
    assert manifest["resource_controller"]["equal_wall_time_claim"] is True
    assert manifest["resource_controller"]["equal_memory_limit_claim"] is True


def test_claim_finalization_rejects_duplicate_evidence_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_synthetic_claim_corpus(monkeypatch)
    root, manifest, runtime, records = _claim_finalization_replay_fixture(tmp_path)
    collision = "f" * 64
    monkeypatch.setattr(harness, "resource_evidence_sha256", lambda _value: collision)
    runtime.controller.authorized = {collision}
    for row in records:
        row["resource_evidence_sha256"] = collision

    with pytest.raises(ResourceControllerError, match="duplicate.*evidence"):
        harness._finalize_controller_claims(
            manifest, records, root=root, controller_runtime=runtime
        )


def test_claim_finalization_rejects_duplicate_invocation_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _allow_synthetic_claim_corpus(monkeypatch)
    root, manifest, runtime, records = _claim_finalization_replay_fixture(tmp_path)
    collision = "e" * 64
    monkeypatch.setattr(SolverInvocation, "sha256", property(lambda _self: collision))
    runtime.controller.authorized.clear()
    for row in records:
        row["controller_invocation_sha256"] = collision
        row["resource_evidence"]["invocation_sha256"] = collision
        row["resource_evidence_sha256"] = harness.resource_evidence_sha256(
            row["resource_evidence"]
        )
        runtime.controller.authorized.add(row["resource_evidence_sha256"])

    with pytest.raises(ResourceControllerError, match="duplicate.*invocation"):
        harness._finalize_controller_claims(
            manifest, records, root=root, controller_runtime=runtime
        )


def test_main_strict_controller_mode_refuses_incomplete_guarantees(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class IncompleteRuntime:
        manifest_binding = {
            "claim_grade_ready": False,
            "execution_admission_ready": False,
            "readiness_blocker": "incomplete trusted evidence",
        }

    monkeypatch.setattr(
        harness,
        "_claim_grade_controller_preflight",
        lambda *_args, **_kwargs: IncompleteRuntime(),
    )
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    for case in harness.COMPETITION_CASES:
        (input_root / f"{case}.xml").write_bytes(b"synthetic-test-input")
    real_sha256 = harness._sha256

    def canonical_test_input_sha256(path: Path) -> str:
        case = Path(path).stem
        if case in harness.CANONICAL_COMPETITION_INPUT_SHA256:
            return harness.CANONICAL_COMPETITION_INPUT_SHA256[case]
        return real_sha256(path)

    monkeypatch.setattr(harness, "_sha256", canonical_test_input_sha256)
    monkeypatch.setattr(
        harness.sys,
        "argv",
        [
            "benchmark_itc2019_competitors.py",
            "--claim-grade-controller-config",
            "controller.json",
            "--instance-set",
            "competition",
            "--input-root",
            str(input_root),
        ],
    )

    with pytest.raises(SystemExit, match="2"):
        harness.main()

    assert "claim-grade controller preflight failed closed" in capsys.readouterr().err


def test_main_rejects_claim_grade_subset_before_controller_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = harness.COMPETITION_CASES[0]
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    instance = input_root / f"{case}.xml"
    instance.write_bytes(b"synthetic-test-input")
    controller_preflight_called = False

    def forbidden_controller_preflight(*_args, **_kwargs):
        nonlocal controller_preflight_called
        controller_preflight_called = True
        raise AssertionError("controller preflight must not run for a subset corpus")

    monkeypatch.setattr(
        harness,
        "_claim_grade_controller_preflight",
        forbidden_controller_preflight,
    )
    monkeypatch.setattr(
        harness,
        "_sha256",
        lambda _path: harness.CANONICAL_COMPETITION_INPUT_SHA256[case],
    )
    monkeypatch.setattr(
        harness.sys,
        "argv",
        [
            "benchmark_itc2019_competitors.py",
            "--claim-grade-controller-config",
            "controller.json",
            "--instance-set",
            "competition",
            "--instances",
            case,
            "--input-root",
            str(input_root),
        ],
    )

    with pytest.raises(SystemExit, match="2"):
        harness.main()

    assert controller_preflight_called is False
    assert "claim-grade corpus case set mismatch" in capsys.readouterr().err


@pytest.mark.parametrize("manifest_kind", ("malformed", "noncanonical"))
def test_main_rejects_bad_resume_manifest_before_controller_or_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    manifest_kind: str,
) -> None:
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    for case in harness.COMPETITION_CASES:
        (input_root / f"{case}.xml").write_bytes(b"synthetic-test-input")
    real_sha256 = harness._sha256

    def canonical_test_input_sha256(path: Path) -> str:
        case = Path(path).stem
        if case in harness.CANONICAL_COMPETITION_INPUT_SHA256:
            return harness.CANONICAL_COMPETITION_INPUT_SHA256[case]
        return real_sha256(path)

    monkeypatch.setattr(harness, "_sha256", canonical_test_input_sha256)
    controller_preflight_called = False

    def forbidden_controller_preflight(*_args, **_kwargs):
        nonlocal controller_preflight_called
        controller_preflight_called = True
        raise AssertionError(
            "controller construction and capability refresh must not be reached"
        )

    monkeypatch.setattr(
        harness,
        "_claim_grade_controller_preflight",
        forbidden_controller_preflight,
    )
    output_root = tmp_path / "resume"
    output_root.mkdir()
    manifest_path = output_root / "manifest.json"
    if manifest_kind == "malformed":
        manifest_path.write_text("{", encoding="utf-8")
    else:
        cases = list(harness.COMPETITION_CASES[:-1])
        inputs = {
            case: harness.CANONICAL_COMPETITION_INPUT_SHA256[case] for case in cases
        }
        manifest_path.write_text(
            json.dumps(
                {
                    "schema": harness.MATRIX_SCHEMA,
                    "instance_set": "competition",
                    "cases": cases,
                    "inputs": inputs,
                    "corpus_admission": {},
                }
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(
        harness.sys,
        "argv",
        [
            "benchmark_itc2019_competitors.py",
            "--claim-grade-controller-config",
            str(tmp_path / "controller.json"),
            "--instance-set",
            "competition",
            "--input-root",
            str(input_root),
            "--output-root",
            str(output_root),
            "--resume",
        ],
    )

    with pytest.raises(SystemExit, match="2"):
        harness.main()

    assert controller_preflight_called is False
    assert "resume manifest preflight failed" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("config_sha256", "config hash drift"),
        ("controller_source_sha256", "source hash drift"),
        ("profile_sha256", "profile hash drift"),
        ("capability_sha256", "capability hash drift"),
        ("supervisor_sha256", "supervisor hash drift"),
        ("solver_argv_sha256", "argv hash drift"),
    ],
)
def test_resume_rehashes_every_controller_manifest_binding(
    tmp_path: Path, field: str, message: str
) -> None:
    binding = _controller_binding(tmp_path, _controller_profile())
    binding[field] = "0" * 64

    with pytest.raises(ValueError, match=message):
        harness._validate_controller_manifest_binding(binding)


@pytest.mark.parametrize(
    "schema",
    (
        "planora.itc2019.competitor-provenance.v1",
        "planora.itc2019.competitor-provenance.v2",
    ),
)
def test_resume_accepts_exact_live_competitor_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    schema: str,
) -> None:
    binding, provenance = _resume_external_binding(tmp_path, schema)
    monkeypatch.setattr(
        harness,
        "verify_competitor_provenance",
        lambda *_args, **_kwargs: json.loads(json.dumps(provenance)),
    )

    assert harness._validate_controller_manifest_binding(binding) is binding


@pytest.mark.parametrize("refreshed_size", (True, 1.0))
def test_resume_rejects_live_provenance_numeric_coercion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    refreshed_size: bool | float,
) -> None:
    binding, provenance = _resume_external_binding(
        tmp_path,
        "planora.itc2019.competitor-provenance.v2",
    )
    refreshed = json.loads(json.dumps(provenance))
    refreshed["solvers"]["gashi-sa"]["upstreams"][0]["source_archive"]["size_bytes"] = (
        refreshed_size
    )
    monkeypatch.setattr(
        harness,
        "verify_competitor_provenance",
        lambda *_args, **_kwargs: refreshed,
    )

    with pytest.raises(ValueError, match="provenance binding drift"):
        harness._validate_controller_manifest_binding(binding)


def test_long_resume_binding_accepts_fresh_same_identity_snapshots(
    tmp_path: Path,
) -> None:
    profile = _controller_profile()
    binding = _controller_binding(tmp_path, profile)
    capability = {
        "daemon_id": "6" * 64,
        "docker_context": "test",
        "supports_memory_limit": True,
        "captured_at_unix_ns": 1,
    }
    binding["capability_evidence"] = dict(capability)
    binding["capability_sha256"] = harness._json_sha256(
        harness._capability_identity_payload(capability)
    )
    binding["preflight_capability_snapshot"] = dict(capability)
    binding["preflight_capability_snapshot_sha256"] = harness._json_sha256(capability)
    manifest = {
        "schema": harness.MATRIX_SCHEMA,
        "resource_policy": dict(harness.QUALITY_ONLY_RESOURCE_POLICY),
        "resource_controller": binding,
    }
    expected_resume_sha256 = harness._resume_binding_sha256(manifest)

    for captured_at in range(2, 258):
        fresh = {**capability, "captured_at_unix_ns": captured_at}
        binding["preflight_capability_snapshot"] = fresh
        binding["preflight_capability_snapshot_sha256"] = harness._json_sha256(fresh)
        assert harness._resume_binding_sha256(manifest) == expected_resume_sha256
        assert harness._validate_controller_manifest_binding(binding) is binding


@pytest.mark.parametrize("seam", ("post_exit_probe", "refresh", "parse", "artifact"))
def test_every_post_create_failure_seam_cleans_and_records_primary_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seam: str,
) -> None:
    class PrimaryFault(RuntimeError):
        pass

    root = tmp_path / "matrix"
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    instance = (input_root / "toy.xml").resolve()
    instance.write_text("<problem name='toy'/>", encoding="utf-8")
    identity = harness._run_identity("toy", "planora", 17, 1, seeds=[17], repetitions=1)
    profile = _controller_profile()
    binding = _controller_binding(tmp_path, profile)
    binding["mode"] = harness.CLAIM_GRADE_CONTROLLER_MODE
    primary = PrimaryFault(seam)

    class FakeController:
        def __init__(self) -> None:
            self.profile = profile
            self.cleanup_calls = 0
            self.last_cleanup_outcomes = (
                CleanupOutcome("absence-verification", 1, None, True),
            )
            self.last_final_inspect = {"direct": True}
            self.last_post_exit_cgroup_evidence = {}

        def refresh_capability_evidence(self):
            return dict(binding["capability_evidence"])

        def execute(self, invocation, *, capability_snapshot=None):
            if seam == "post_exit_probe":
                raise primary
            run_dir = Path(invocation.host_run_directory)
            (run_dir / "solution.xml").write_text("solution", encoding="utf-8")
            (run_dir / harness.SUPERVISOR_EVIDENCE_RELATIVE_PATH).write_text(
                "{}", encoding="utf-8"
            )
            return ExecutionObservation(
                run_id=invocation.run_id,
                container_id="7" * 64,
                image_id="sha256:" + "4" * 64,
                host_started_monotonic_ns=1,
                host_solver_deadline_monotonic_ns=11_000_000_001,
                host_artifact_deadline_monotonic_ns=12_000_000_001,
                host_finished_monotonic_ns=2,
                host_started_wall_ns=1,
                host_artifact_deadline_wall_ns=12_000_000_001,
                attach_returncode=0,
                timed_out=False,
                cleanup_complete=True,
                residual_processes=0,
            )

        def parse_evidence(self, *_args, **_kwargs):
            if seam in {"refresh", "parse"}:
                raise primary
            pytest.fail("parse should not be reached for this injected seam")

        def cleanup_after_failure(self, _invocation):
            self.cleanup_calls += 1
            return True

    controller = FakeController()
    runtime = harness.ClaimGradeControllerRuntime(
        controller=controller,
        manifest_binding=binding,
        supervisor_path=Path(binding["supervisor_path"]),
        solver_argv_templates={"planora": tuple(binding["solver_argv"]["planora"])},
    )
    if seam == "artifact":
        monkeypatch.setattr(
            harness,
            "_output_artifact_metadata",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(primary),
        )

    with pytest.raises(PrimaryFault) as captured:
        harness._run_one_controller(
            runtime,
            "planora",
            identity=identity,
            case="toy",
            instance_path=instance,
            root=root,
            seed=17,
            repetition=1,
            seconds=10.0,
            cpu=0,
            resume_binding_sha256="1" * 64,
        )

    assert captured.value is primary
    assert controller.cleanup_calls == 1
    state_path = root / "runs" / str(identity["run_id"]) / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "failed"
    assert state["failure_type"] == "PrimaryFault"
    assert state["failure"] == seam
    assert state["cleanup_complete"] is True
    assert state["cleanup_outcomes"][0]["absence_verified"] is True
    assert not (state_path.parent / "result.json").exists()


@pytest.mark.parametrize(
    ("write_output", "returncode"),
    [(True, 0), (False, 7)],
)
def test_controller_execution_never_uses_legacy_host_and_resume_binds_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_output: bool,
    returncode: int,
) -> None:
    root = tmp_path / "matrix"
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    instance = (input_root / "toy.xml").resolve()
    instance.write_text("<problem name='toy'/>", encoding="utf-8")
    identity = harness._run_identity("toy", "planora", 17, 1, seeds=[17], repetitions=1)
    profile = _controller_profile()
    binding = _controller_binding(tmp_path, profile)

    class FakeController:
        def __init__(self) -> None:
            self.profile = profile
            self.last_cleanup_outcomes = (
                CleanupOutcome("remove", 0, None),
                CleanupOutcome("absence-verification", 1, None, True),
            )

        def refresh_capability_evidence(self):
            return dict(binding["capability_evidence"])

        def execute(self, invocation, *, capability_snapshot=None):
            if write_output:
                Path(invocation.host_run_directory, "solution.xml").write_text(
                    "<solution name='toy'/>", encoding="utf-8"
                )
            return ExecutionObservation(
                run_id=invocation.run_id,
                container_id="7" * 64,
                image_id="sha256:" + "4" * 64,
                host_started_monotonic_ns=1_000_000_000,
                host_solver_deadline_monotonic_ns=11_000_000_000,
                host_artifact_deadline_monotonic_ns=12_000_000_000,
                host_finished_monotonic_ns=2_000_000_000,
                host_started_wall_ns=1_000_000_000,
                host_artifact_deadline_wall_ns=12_000_000_000,
                attach_returncode=returncode,
                timed_out=False,
                cleanup_complete=True,
                residual_processes=0,
            )

    runtime = harness.ClaimGradeControllerRuntime(
        controller=FakeController(),
        manifest_binding=binding,
        supervisor_path=Path(binding["supervisor_path"]),
        solver_argv_templates={"planora": tuple(binding["solver_argv"]["planora"])},
    )
    manifest = {
        "schema": harness.MATRIX_SCHEMA,
        "cases": ["toy"],
        "instance_set": "public",
        "solvers": ["planora"],
        "seeds": [17],
        "repetitions": 1,
        "configured_solver_seconds": 10.0,
        "workers": 1,
        "cpu_affinity": 0,
        "input_root": str(input_root.resolve()),
        "host": {"test": True},
        "inputs": {"toy": harness._sha256(instance)},
        "tool_paths": {
            "gashi": str(tmp_path / "gashi.dll"),
            "cpsolver_root": str(tmp_path / "cpsolver"),
            "maxsat": str(tmp_path / "maxsat"),
            "maxsat_locale": str(tmp_path / "locale"),
        },
        "tools": {"test": True},
        "harness_sha256": harness._sha256(Path(harness.__file__).resolve()),
        "official_validator_helper_sha256": "helper-hash",
        "resource_policy": dict(harness.QUALITY_ONLY_RESOURCE_POLICY),
        "resource_controller": binding,
        "expected_runs": [identity],
    }
    binding_sha256 = harness._resume_binding_sha256(manifest)
    monkeypatch.setattr(
        harness,
        "_run_one",
        lambda *args, **kwargs: pytest.fail("legacy host launcher was reached"),
    )
    monkeypatch.setattr(
        harness,
        "_score",
        lambda *_args: {"feasible": True, "objective": {"total": 0}},
    )

    row = harness._run_one_controller(
        runtime,
        "planora",
        identity=identity,
        case="toy",
        instance_path=instance,
        root=root,
        seed=17,
        repetition=1,
        seconds=10.0,
        cpu=0,
        resume_binding_sha256=binding_sha256,
    )

    assert row["execution_mode"] == harness.EVIDENCE_ONLY_CONTROLLER_MODE
    evidence_path = Path(row["resource_evidence_path"])
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert row["resource_evidence"] == evidence
    assert row["resource_evidence_sha256"] == harness.resource_evidence_sha256(evidence)
    assert evidence["config_sha256"] == binding["config_sha256"]
    assert evidence["profile_sha256"] == binding["profile_sha256"]
    assert evidence["capability_sha256"] == binding["capability_sha256"]
    assert evidence["supervisor_sha256"] == binding["supervisor_sha256"]
    assert evidence["image_reference"] == binding["solver_images"]["planora"]
    assert evidence["claim_grade_ready"] is False
    if write_output:
        assert row["output_relative_path"] == (
            f"runs/{identity['run_id']}/solution.xml"
        )
        assert row["artifact_binding_sha256"] == summarizer._artifact_binding(
            row,
            relative_path=row["output_relative_path"],
            output_sha256=row["output_sha256"],
        )
    else:
        assert row["exit_code"] == 7
        assert evidence["artifact_sha256"] is None
        assert row["output_path"] is None
        assert row["output_relative_path"] is None
        assert row["output_sha256"] is None
        assert row["artifact_binding_sha256"] is None
        assert row["independent_validation"]["status"] == (
            harness._NO_ARTIFACT_VALIDATION_STATUS
        )
        assert row["independent_validation"]["feasible"] is None
        assert "independent feasible status is not Boolean" in (
            summarizer._local_validation_errors(row)
        )
    assert harness._resume_records(root, manifest) == [row]

    evidence["capability_sha256"] = "8" * 64
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(ValueError, match="evidence file hash drift"):
        harness._resume_records(root, manifest)


@pytest.mark.parametrize("write_output", (True, False))
def test_claim_controller_uses_authoritative_parser_and_resume_rechecks_direct_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_output: bool,
) -> None:
    _allow_synthetic_claim_corpus(monkeypatch)
    root = tmp_path / "matrix"
    input_root = tmp_path / "inputs"
    input_root.mkdir()
    instance = (input_root / "toy.xml").resolve()
    instance.write_text("<problem name='toy'/>", encoding="utf-8")
    identity = harness._run_identity("toy", "planora", 17, 1, seeds=[17], repetitions=1)
    profile = _controller_profile()
    binding = _controller_binding(tmp_path, profile)
    refresh_binding = {
        "schema": harness.CAPABILITY_REFRESH_CONFIG_SCHEMA,
        "argv": [harness.sys.executable],
        "executable_sha256": harness._sha256(Path(harness.sys.executable)),
        "bound_files": [],
        "timeout_seconds": 5.0,
    }
    cgroup_probe_binding = {
        "schema": harness.POST_EXIT_CGROUP_PROBE_CONFIG_SCHEMA,
        "argv": [harness.sys.executable, "{container_id}"],
        "executable_sha256": harness._sha256(Path(harness.sys.executable)),
        "bound_files": [],
        "timeout_seconds": 5.0,
    }
    binding.update(
        {
            "mode": harness.CLAIM_GRADE_CONTROLLER_MODE,
            "capability_refresh": refresh_binding,
            "capability_refresh_sha256": harness._json_sha256(refresh_binding),
            "post_exit_cgroup_probe": cgroup_probe_binding,
            "post_exit_cgroup_probe_sha256": harness._json_sha256(cgroup_probe_binding),
            "execution_admission_ready": True,
            "readiness_blocker": (
                "Claim readiness is pending authoritative direct evidence for every run."
            ),
        }
    )
    parse_calls = []

    class ParsedEvidence:
        def __init__(self, payload):
            self._payload = payload

        def to_canonical_dict(self):
            return dict(self._payload)

    class FakeController:
        def __init__(self) -> None:
            self.profile = profile
            self.last_cleanup_outcomes = (
                CleanupOutcome("remove", 0, None),
                CleanupOutcome("absence-verification", 1, None, True),
            )
            self.last_final_inspect = {"direct": True}
            self.last_post_exit_cgroup_evidence = {}
            self._authorized = set()
            self.cleanup_calls = 0

        def refresh_capability_evidence(self):
            return dict(binding["capability_evidence"])

        @staticmethod
        def container_name(_invocation):
            return "container"

        def execute(self, invocation, *, capability_snapshot=None):
            run_dir = Path(invocation.host_run_directory)
            if write_output:
                (run_dir / "solution.xml").write_text(
                    "<solution name='toy'/>", encoding="utf-8"
                )
            (run_dir / harness.CGROUP_EVIDENCE_RELATIVE_PATH).write_text(
                "{}", encoding="utf-8"
            )
            (run_dir / harness.SUPERVISOR_EVIDENCE_RELATIVE_PATH).write_text(
                "{}", encoding="utf-8"
            )
            return ExecutionObservation(
                run_id=invocation.run_id,
                container_id="7" * 64,
                image_id="sha256:" + "4" * 64,
                host_started_monotonic_ns=1_000_000_000,
                host_solver_deadline_monotonic_ns=11_000_000_000,
                host_artifact_deadline_monotonic_ns=12_000_000_000,
                host_finished_monotonic_ns=2_000_000_000,
                host_started_wall_ns=1_000_000_000,
                host_artifact_deadline_wall_ns=12_000_000_000,
                attach_returncode=0,
                timed_out=False,
                cleanup_complete=True,
                residual_processes=0,
            )

        def parse_evidence(self, invocation, **evidence):
            parse_calls.append(evidence)
            assert evidence["inspect"] == {"direct": True}
            assert evidence["cgroup"] == {}
            assert evidence["supervisor"] == {}
            output = Path(invocation.host_run_directory, "solution.xml")
            output_sha256 = harness._sha256(output) if output.is_file() else None
            execution = evidence["execution"]
            execution_payload = (
                dict(execution) if isinstance(execution, dict) else asdict(execution)
            )
            payload = {
                "schema": harness.RESOURCE_EVIDENCE_SCHEMA,
                "run_id": invocation.run_id,
                "container_id": execution_payload["container_id"],
                "container_name": "container",
                "image_reference": invocation.image,
                "image_id": execution_payload["image_id"],
                "profile_sha256": profile.sha256,
                "invocation_sha256": invocation.sha256,
                "invocation": invocation.to_canonical_dict(),
                "execution": execution_payload,
                "capability_sha256": binding["capability_sha256"],
                "capability_snapshot_sha256": invocation.capability_snapshot_sha256,
                "capability_snapshot": dict(evidence["capability_snapshot"]),
                "supervisor_sha256": binding["supervisor_sha256"],
                "daemon_id": "6" * 64,
                "docker_context": "test",
                "cgroup_path": "/docker/" + "7" * 64,
                "cgroup_identity": "8" * 64,
                "post_exit_cgroup_sampled_monotonic_ns": 2_100_000_000,
                "exit_code": 0,
                "elapsed_monotonic_ns": 1_000_000_000,
                "artifact_committed": output.is_file(),
                "artifact_sha256": output_sha256,
                "artifact_relative_path": "solution.xml" if output.is_file() else None,
                "artifact_size_bytes": output.stat().st_size
                if output.is_file()
                else None,
                "artifact_file_identity": "9" * 64 if output.is_file() else None,
                "memory_current_bytes": 1,
                "memory_peak_bytes": 2,
                "memory_swap_current_bytes": 0,
                "memory_swap_peak_bytes": 0,
                "memory_events": {"oom": 0},
                "memory_swap_events": {"fail": 0},
                "cpu_stat": {"usage_usec": 1},
                "pids_current": 0,
                "pids_peak": 1,
                "effective_memory_max": profile.memory_bytes,
                "effective_memory_swap_max": (
                    profile.memory_swap_bytes - profile.memory_bytes
                ),
                "effective_cpu_max": (
                    f"{profile.cpu_quota_us} {profile.cpu_period_us}"
                ),
                "effective_cpuset_cpus": profile.cpuset_cpus,
                "effective_pids_max": profile.pids_limit,
                "deadline_exceeded": False,
                "cleanup_complete": True,
                "residual_processes": 0,
                "cleanup_outcomes": [
                    {
                        "operation": "absence-verification",
                        "returncode": 1,
                        "error": None,
                        "absence_verified": True,
                    }
                ],
                "claim_grade_ready": True,
            }
            self._authorized.add(harness.resource_evidence_sha256(payload))
            return ParsedEvidence(payload)

        def authorizes_claim_grade_evidence(self, evidence):
            return harness.resource_evidence_sha256(evidence) in self._authorized

        def cleanup_after_failure(self, _invocation):
            self.cleanup_calls += 1
            return True

    runtime = harness.ClaimGradeControllerRuntime(
        controller=FakeController(),
        manifest_binding=binding,
        supervisor_path=Path(binding["supervisor_path"]),
        solver_argv_templates={"planora": tuple(binding["solver_argv"]["planora"])},
    )
    manifest = {
        "schema": harness.MATRIX_SCHEMA,
        "cases": ["toy"],
        "instance_set": "public",
        "solvers": ["planora"],
        "seeds": [17],
        "repetitions": 1,
        "configured_solver_seconds": 10.0,
        "workers": 1,
        "cpu_affinity": 0,
        "input_root": str(input_root.resolve()),
        "host": {"test": True},
        "inputs": {"toy": harness._sha256(instance)},
        "tool_paths": {
            "gashi": str(tmp_path / "gashi.dll"),
            "cpsolver_root": str(tmp_path / "cpsolver"),
            "maxsat": str(tmp_path / "maxsat"),
            "maxsat_locale": str(tmp_path / "locale"),
        },
        "tools": {"test": True},
        "harness_sha256": harness._sha256(Path(harness.__file__).resolve()),
        "official_validator_helper_sha256": "helper-hash",
        "resource_policy": dict(harness.QUALITY_ONLY_RESOURCE_POLICY),
        "resource_controller": binding,
        "expected_runs": [identity],
    }
    binding_sha256 = harness._resume_binding_sha256(manifest)
    monkeypatch.setattr(
        harness,
        "_score",
        lambda *_args: {"feasible": True, "objective": {"total": 0}},
    )

    row = harness._run_one_controller(
        runtime,
        "planora",
        identity=identity,
        case="toy",
        instance_path=instance,
        root=root,
        seed=17,
        repetition=1,
        seconds=10.0,
        cpu=0,
        resume_binding_sha256=binding_sha256,
    )

    assert len(parse_calls) == 1
    assert row["resource_evidence"]["claim_grade_ready"] is True
    assert row["equal_wall_time_claim"] is True
    assert row["equal_memory_limit_claim"] is True
    if write_output:
        assert row["artifact_binding_sha256"] is not None
    else:
        assert row["artifact_binding_sha256"] is None
        assert row["independent_validation"]["status"] == "not_run_no_artifact"
    harness._finalize_controller_claims(
        manifest, [row], root=root, controller_runtime=runtime
    )
    assert manifest["resource_controller"]["claim_grade_ready"] is True
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert harness._resume_records(root, manifest, controller_runtime=runtime) == [row]

    expected_claim_set_sha256 = manifest["resource_controller"][
        "claim_evidence_set_sha256"
    ]
    manifest["resource_controller"]["claim_evidence_set_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="claim evidence set hash mismatch"):
        harness._resume_records(root, manifest, controller_runtime=runtime)
    manifest["resource_controller"]["claim_evidence_set_sha256"] = (
        expected_claim_set_sha256
    )

    evidence_path = Path(row["resource_evidence_path"])
    tampered = json.loads(evidence_path.read_text(encoding="utf-8"))
    tampered["effective_memory_max"] -= 1
    evidence_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="evidence file hash drift"):
        harness._resume_records(root, manifest, controller_runtime=runtime)

    original_evidence = json.loads(json.dumps(row["resource_evidence"]))
    forged_time = json.loads(json.dumps(original_evidence))
    forged_time["post_exit_cgroup_sampled_monotonic_ns"] = 1_999_999_999
    harness._write_json_atomic(evidence_path, forged_time)
    row["resource_evidence"] = forged_time
    row["resource_evidence_sha256"] = harness.resource_evidence_sha256(forged_time)
    row["resource_evidence_file_sha256"] = harness._sha256(evidence_path)
    result_path = root / "runs" / str(identity["run_id"]) / "result.json"
    harness._write_json_atomic(result_path, row)
    state_path = result_path.with_name("state.json")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["initial_result_sha256"] = harness._sha256(result_path)
    harness._write_json_atomic(state_path, state)
    harness._write_json_atomic(
        root / "report.json", {"manifest": manifest, "records": [row]}
    )
    with pytest.raises(ValueError, match="differs from raw parse"):
        harness._resume_records(root, manifest, controller_runtime=runtime)

    forged = json.loads(json.dumps(original_evidence))
    forged_snapshot = dict(forged["capability_snapshot"])
    forged_snapshot["captured_at_unix_ns"] = 1
    forged["capability_snapshot"] = forged_snapshot
    harness._write_json_atomic(evidence_path, forged)
    row["resource_evidence"] = forged
    row["resource_evidence_sha256"] = harness.resource_evidence_sha256(forged)
    row["resource_evidence_file_sha256"] = harness._sha256(evidence_path)
    harness._write_json_atomic(result_path, row)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["initial_result_sha256"] = harness._sha256(result_path)
    harness._write_json_atomic(state_path, state)
    with pytest.raises(ValueError, match="differs from raw parse"):
        harness._resume_records(root, manifest, controller_runtime=runtime)
