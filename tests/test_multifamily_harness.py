from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from unittest.mock import patch
import zipfile

import pytest

from benchmarks.multifamily_harness import (
    BenchmarkCaseSpec,
    BenchmarkPlan,
    BenchmarkSolverSpec,
    CorpusInstanceSpec,
    CorpusManifestSpec,
    DEFAULT_SOURCE_ROOTS,
    SCORE_AUTHORITY_INDEPENDENT,
    SCORE_AUTHORITY_NATIVE,
    SCORE_AUTHORITY_OFFICIAL,
    _attach_official_validation,
    _child_environment,
    expand_plan,
    invalidate_for_source_drift,
    make_replicated_plan,
    make_corpus_manifest,
    make_smoke_plan,
    run_worker_request,
    sha256_file,
    sha256_json,
    source_snapshot,
    summarize_records,
    snapshot_command_tools,
    tool_snapshot_matches,
)


_TEST_SOURCE_SHA256: str | None = None


def _current_test_source_sha256() -> str:
    global _TEST_SOURCE_SHA256
    if _TEST_SOURCE_SHA256 is None:
        configured = os.environ.get("PLANORA_TEST_SOURCE_SHA256")
        if configured and re.fullmatch(r"[0-9a-f]{64}", configured):
            _TEST_SOURCE_SHA256 = configured
        else:
            _TEST_SOURCE_SHA256, _ = source_snapshot(Path.cwd(), DEFAULT_SOURCE_ROOTS)
    return _TEST_SOURCE_SHA256


def _instance(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_text(f"synthetic {name}\n", encoding="utf-8")
    return path


def _jar(path: Path, *, manifest: str = "Manifest-Version: 1.0\n\n") -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", manifest)
        archive.writestr("Pinned.class", b"bytecode")
    return path


def _case(
    tmp_path: Path,
    *,
    case_id: str = "case",
    family_id: str = "itc2019",
    seeds: tuple[int, ...] = (7,),
    repetitions: int = 1,
) -> BenchmarkCaseSpec:
    return BenchmarkCaseSpec(
        case_id=case_id,
        family_id=family_id,
        instance_path=str(_instance(tmp_path, f"{case_id}.dat")),
        time_limit_seconds=2.5,
        seeds=seeds,
        repetitions=repetitions,
        options={"solver": {"max_pair_matrix_cells": 1234}},
    )


def test_smoke_and_replicated_plans_expand_deterministically(tmp_path: Path) -> None:
    smoke = make_smoke_plan([_case(tmp_path)])
    smoke_runs = expand_plan(smoke)
    assert smoke.mode == "smoke"
    assert smoke.minimum_effective_runs_per_condition == 1
    assert len(smoke_runs) == 1
    assert smoke_runs[0].execution_id == "case__seed-7__rep-001"

    comparator = BenchmarkSolverSpec(
        solver_id="cpsolver",
        model="external_command",
        role="comparator",
        command=(
            str(Path("/bin/true")),
            "{instance_path}",
            "{output_path}",
            "{seed}",
            "{time_limit_seconds}",
        ),
    )
    replicated_case = BenchmarkCaseSpec(
        case_id="replicated",
        family_id="itc2019",
        instance_path=str(_instance(tmp_path, "replicated.dat")),
        time_limit_seconds=2.5,
        seeds=(11, 13, 17),
        repetitions=2,
        workers=1,
        cpu_affinity=0,
        options={"solver": {"max_pair_matrix_cells": 1234}},
        solvers=(BenchmarkSolverSpec.planora(), comparator),
    )
    diagnostic = make_smoke_plan(
        [replicated_case],
        corpus_manifest=make_corpus_manifest(
            [replicated_case], corpus_id="synthetic-itc2019"
        ),
    )
    assert diagnostic.cases[0].solvers[1].evidence_classification == (
        "diagnostic_unverified"
    )
    with pytest.raises(ValueError, match="diagnostic_unverified"):
        make_replicated_plan(
            [replicated_case],
            corpus_manifest=make_corpus_manifest(
                [replicated_case], corpus_id="synthetic-itc2019"
            ),
        )

    native_case = BenchmarkCaseSpec(
        case_id="replicated-native",
        family_id="itc2019",
        instance_path=str(_instance(tmp_path, "replicated-native.dat")),
        time_limit_seconds=2.5,
        seeds=(11, 13, 17),
        repetitions=2,
        workers=1,
        cpu_affinity=0,
    )
    replicated = make_replicated_plan(
        [native_case],
        corpus_manifest=make_corpus_manifest(
            [native_case], corpus_id="synthetic-native-itc2019"
        ),
    )
    executions = expand_plan(replicated)
    assert replicated.mode == "replicated"
    assert replicated.minimum_effective_runs_per_condition == 6
    assert replicated.require_official_validator_agreement is True
    assert len(executions) == 6
    assert len({row.execution_id for row in executions}) == 6
    assert len({row.config_sha256 for row in executions}) == 6
    assert {row.case.condition_id for row in executions} == {native_case.condition_id}
    assert [row.solver.solver_id for row in executions] == ["planora"] * 6
    assert [row.pair_order_position for row in executions] == [1] * 6

    roundtrip = BenchmarkPlan.from_dict(
        json.loads(json.dumps(replicated.to_dict())),
        base_directory=tmp_path,
    )
    assert roundtrip.plan_sha256 == replicated.plan_sha256
    assert [row.execution_id for row in expand_plan(roundtrip)] == [
        row.execution_id for row in executions
    ]


def test_plan_rejects_ambiguous_or_non_json_configuration(tmp_path: Path) -> None:
    path = _instance(tmp_path, "instance.dat")
    with pytest.raises(ValueError, match="unknown option groups"):
        BenchmarkCaseSpec(
            case_id="bad",
            family_id="xhstt",
            instance_path=str(path),
            time_limit_seconds=1.0,
            options={"silently_ignored": {}},
        )
    with pytest.raises(ValueError, match="finite JSON"):
        BenchmarkCaseSpec(
            case_id="bad-json",
            family_id="xhstt",
            instance_path=str(path),
            time_limit_seconds=1.0,
            options={"solver": {"value": float("nan")}},
        )
    with pytest.raises(ValueError, match="cannot omit"):
        BenchmarkPlan(
            mode="smoke",
            cases=(_case(tmp_path, case_id="narrow-source"),),
            minimum_effective_runs_per_condition=1,
            source_roots=("benchmarks",),
        )
    valid = make_smoke_plan([_case(tmp_path, case_id="strict-fields")]).to_dict()
    valid["misspelled_target"] = 30
    with pytest.raises(ValueError, match="unknown benchmark plan fields"):
        BenchmarkPlan.from_dict(valid)


def test_replicated_plan_rejects_seed_repetition_substitution_and_corpus_drift(
    tmp_path: Path,
) -> None:
    repeated_seed = _case(
        tmp_path,
        case_id="one-seed-six-times",
        seeds=(17,),
        repetitions=6,
    )
    manifest = make_corpus_manifest([repeated_seed], corpus_id="declared-corpus")
    with pytest.raises(ValueError, match="three unique prespecified seeds"):
        make_replicated_plan([repeated_seed], corpus_manifest=manifest)

    valid = _case(
        tmp_path,
        case_id="three-seeds",
        seeds=(11, 13, 17),
        repetitions=2,
    )
    incomplete = CorpusManifestSpec(
        corpus_id="wrong-corpus",
        instances=(
            CorpusInstanceSpec(
                case_id="different-case",
                family_id=valid.family_id,
                input_sha256=valid.input_sha256,
            ),
        ),
    )
    with pytest.raises(ValueError, match="does not exactly match"):
        make_replicated_plan([valid], corpus_manifest=incomplete)

    too_few_expected_runs = _case(
        tmp_path,
        case_id="three-seeds-once",
        seeds=(11, 13, 17),
        repetitions=1,
    )
    with pytest.raises(ValueError, match="at least two repetitions"):
        make_replicated_plan(
            [too_few_expected_runs],
            corpus_manifest=make_corpus_manifest(
                [too_few_expected_runs], corpus_id="insufficient-replication"
            ),
        )
    with pytest.raises(ValueError, match="at least two repetitions"):
        make_replicated_plan(
            [too_few_expected_runs],
            corpus_manifest=make_corpus_manifest(
                [too_few_expected_runs], corpus_id="caller-lowered-replication"
            ),
            minimum_effective_runs_per_condition=3,
        )


def test_command_tool_snapshot_hashes_interpreter_script_but_not_data(
    tmp_path: Path,
) -> None:
    script = tmp_path / "solver.py"
    script.write_text("print('solver')\n", encoding="utf-8")
    instance_data = tmp_path / "instance.dat"
    instance_data.write_text("benchmark input\n", encoding="utf-8")

    command, manifest, digest = snapshot_command_tools(
        (sys.executable, str(script), str(instance_data), "{output_path}"),
        base_directory=tmp_path,
    )

    paths = {row["path"] for row in manifest}
    assert command[0] == str(Path(sys.executable).resolve())
    assert str(script.resolve()) in paths
    assert str(instance_data.resolve()) in paths
    assert (
        next(row for row in manifest if row["path"] == str(instance_data.resolve()))[
            "kind"
        ]
        == "auxiliary_input"
    )
    assert len(digest) == 64
    assert tool_snapshot_matches(manifest) is True
    script.write_text("print('changed solver')\n", encoding="utf-8")
    assert tool_snapshot_matches(manifest) is False


def test_command_tool_snapshot_hashes_explicit_java_classpath_and_rejects_wildcards(
    tmp_path: Path,
) -> None:
    java = tmp_path / "java"
    java.write_bytes(b"synthetic java executable")
    solver_jar = _jar(tmp_path / "cpsolver.jar")
    classes = tmp_path / "classes"
    classes.mkdir()
    (classes / "Main.class").write_bytes(b"bytecode")
    (classes / "Main.java").write_text("class Main {}\n", encoding="utf-8")
    classpath = os.pathsep.join((str(solver_jar), str(classes)))

    _command, manifest, _digest = snapshot_command_tools(
        (
            str(java),
            "-cp",
            classpath,
            "org.cpsolver.Main",
            "{instance_path}",
        ),
        base_directory=tmp_path,
    )

    by_path = {row["path"]: row for row in manifest}
    assert by_path[str(solver_jar.resolve())]["kind"] == "classpath"
    assert by_path[str(classes.resolve())]["artifact_type"] == "directory"
    assert by_path[str(classes.resolve())]["file_count"] == 2
    assert len(manifest) == 3
    for wildcard in ("*.jar", "classes/*", "src/*.java"):
        with pytest.raises(ValueError, match="classpath wildcards"):
            snapshot_command_tools(
                (str(java), "-cp", wildcard, "org.cpsolver.Main"),
                base_directory=tmp_path,
            )


def test_command_tool_snapshot_rejects_java_argfiles_even_when_absolute(
    tmp_path: Path,
) -> None:
    java = tmp_path / "java"
    java.write_bytes(b"synthetic java executable")
    solver_jar = _jar(tmp_path / "cpsolver.jar")
    plugin = tmp_path / "solver.plugin"
    plugin.write_bytes(b"pinned plugin")
    argfile = tmp_path / "solver.args"
    argfile.write_text(
        f"-Xmx1g\n-cp {solver_jar}\n--plugin={plugin}\norg.cpsolver.Main\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="command @response files are unsupported"):
        snapshot_command_tools(
            (str(java), f"@{argfile}", "{instance_path}"),
            base_directory=tmp_path,
        )

    with pytest.raises(ValueError, match="command @response files are unsupported"):
        snapshot_command_tools(
            (str(java), f"@{tmp_path / 'missing.args'}", "{instance_path}"),
            base_directory=tmp_path,
        )


@pytest.mark.parametrize(
    "argfile_contents",
    (
        "-cp cpsolver.jar\norg.cpsolver.Main\n",
        "-classpath=classes\norg.cpsolver.Main\n",
        "-jar cpsolver.jar\n",
        "--plugin=solver.plugin\norg.cpsolver.Main\n",
        "--plugin solver.plugin\norg.cpsolver.Main\n",
        "-Djava.library.path=native/lib\norg.cpsolver.Main\n",
    ),
)
def test_command_tool_snapshot_rejects_relative_java_argfile_dependencies(
    tmp_path: Path,
    argfile_contents: str,
) -> None:
    java = tmp_path / "java"
    java.write_bytes(b"synthetic java executable")
    _jar(tmp_path / "cpsolver.jar")
    (tmp_path / "classes").mkdir()
    (tmp_path / "solver.plugin").write_bytes(b"pinned plugin")
    (tmp_path / "native" / "lib").mkdir(parents=True)
    argfile = tmp_path / "relative.args"
    argfile.write_text(argfile_contents, encoding="utf-8")

    with pytest.raises(ValueError, match="command @response files are unsupported"):
        snapshot_command_tools(
            (str(java), f"@{argfile}", "{instance_path}"),
            base_directory=tmp_path,
        )


def test_command_tool_snapshot_rejects_nested_java_argfiles(tmp_path: Path) -> None:
    java = tmp_path / "java"
    java.write_bytes(b"synthetic java executable")
    nested = tmp_path / "nested.args"
    nested.write_text("org.cpsolver.Main\n", encoding="utf-8")
    outer = tmp_path / "outer.args"
    outer.write_text(f"@{nested}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="command @response files are unsupported"):
        snapshot_command_tools(
            (str(java), f"@{outer}", "{instance_path}"),
            base_directory=tmp_path,
        )


@pytest.mark.parametrize(
    "argfile_contents",
    (
        "-p late-modules\norg.cpsolver.Main\n",
        "--module-path=late-modules\norg.cpsolver.Main\n",
        "--upgrade-module-path late-modules\norg.cpsolver.Main\n",
        "--upgrade-module-path=late-modules\norg.cpsolver.Main\n",
        "--patch-module app=late-patches\norg.cpsolver.Main\n",
        "--patch-module=app=late-patches\norg.cpsolver.Main\n",
        "-DpluginPath=late.plugin\norg.cpsolver.Main\n",
        "-agentpath:late-agent\norg.cpsolver.Main\n",
        "-javaagent:late-agent.jar\norg.cpsolver.Main\n",
        "-Xbootclasspath/a:late-boot\norg.cpsolver.Main\n",
        "-Xbootclasspath late-boot\norg.cpsolver.Main\n",
    ),
)
def test_java_argfile_rejects_relative_launcher_loading_paths(
    tmp_path: Path,
    argfile_contents: str,
) -> None:
    java = tmp_path / "java"
    java.write_bytes(b"synthetic java executable")
    for directory in (
        "late-modules",
        "late-patches",
        "late-boot",
    ):
        (tmp_path / directory).mkdir()
    for filename in ("late.plugin", "late-agent", "late-agent.jar"):
        (tmp_path / filename).write_bytes(b"late mutable logic")
    argfile = tmp_path / "launcher-relative.args"
    argfile.write_text(argfile_contents, encoding="utf-8")

    with pytest.raises(ValueError, match="command @response files are unsupported"):
        snapshot_command_tools(
            (str(java), f"@{argfile}", "{instance_path}"),
            base_directory=tmp_path,
        )


def test_java_argfile_rejects_absolute_launcher_loading_paths(
    tmp_path: Path,
) -> None:
    java = tmp_path / "java"
    java.write_bytes(b"synthetic java executable")
    artifacts: dict[str, Path] = {}
    for name in ("modules", "upgrades", "patch-a", "patch-b", "native"):
        path = tmp_path / name
        path.mkdir()
        artifacts[name] = path
    for name in ("agent.jar", "agent.so", "boot.jar", "plugin.bin", "cp.jar"):
        path = tmp_path / name
        path.write_bytes(f"frozen {name}".encode())
        artifacts[name] = path
    argfile = tmp_path / "launcher-absolute.args"
    argfile.write_text(
        "\n".join(
            (
                f"-p {artifacts['modules']}",
                f"--upgrade-module-path={artifacts['upgrades']}",
                "--patch-module "
                f"app={artifacts['patch-a']}{os.pathsep}{artifacts['patch-b']}",
                f"-javaagent:{artifacts['agent.jar']}",
                f"-agentpath:{artifacts['agent.so']}",
                f"-Xbootclasspath/a:{artifacts['boot.jar']}",
                f"-DpluginPath={artifacts['plugin.bin']}",
                f"-Djava.library.path={artifacts['native']}",
                f"-cp {artifacts['cp.jar']}",
                "org.cpsolver.Main",
            )
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="command @response files are unsupported"):
        snapshot_command_tools(
            (str(java), f"@{argfile}", "{instance_path}"),
            base_directory=tmp_path,
        )


def test_java_argfile_relative_classpath_has_real_cwd_divergence(
    tmp_path: Path,
) -> None:
    java = shutil.which("java")
    if java is None:
        pytest.skip("Java executable is unavailable")
    plan_directory = tmp_path / "plan"
    run_directory = tmp_path / "run"
    plan_directory.mkdir()
    run_directory.mkdir()
    (plan_directory / "marker.txt").write_text("FROZEN", encoding="utf-8")
    (run_directory / "marker.txt").write_text("RUNTIME", encoding="utf-8")
    source = plan_directory / "CwdProbe.java"
    source.write_text(
        "public class CwdProbe { public static void main(String[] a) throws Exception { "
        'try (var in = ClassLoader.getSystemResourceAsStream("marker.txt")) { '
        "System.out.print(new String(in.readAllBytes())); } } }\n",
        encoding="utf-8",
    )
    argfile = plan_directory / "cwd.args"
    argfile.write_text(f"-cp .\n{source}\n", encoding="utf-8")

    execution = subprocess.run(
        (java, f"@{argfile}"),
        cwd=run_directory,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if execution.returncode != 0:
        pytest.skip("installed Java does not support source-file execution")
    assert execution.stdout.strip().endswith("RUNTIME")
    with pytest.raises(ValueError, match="command @response files are unsupported"):
        snapshot_command_tools(
            (java, f"@{argfile}", "{instance_path}"),
            base_directory=plan_directory,
        )


def test_direct_java_module_path_has_real_cwd_divergence(tmp_path: Path) -> None:
    java = shutil.which("java")
    javac = shutil.which("javac")
    if java is None or javac is None:
        pytest.skip("Java toolchain is unavailable")

    def build_module(root: Path, label: str) -> None:
        source = root / "source"
        source.mkdir(parents=True)
        (source / "module-info.java").write_text("module app {}\n", encoding="utf-8")
        package = source / "probe"
        package.mkdir()
        (package / "Main.java").write_text(
            "package probe; public class Main { public static void main(String[] a) { "
            f'System.out.print("{label}"); }} }}\n',
            encoding="utf-8",
        )
        subprocess.run(
            (
                javac,
                "-d",
                str(root / "late-modules"),
                str(source / "module-info.java"),
                str(package / "Main.java"),
            ),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )

    plan_directory = tmp_path / "plan"
    run_directory = tmp_path / "run"
    build_module(plan_directory, "FROZEN")
    build_module(run_directory, "RUNTIME")
    command = (java, "-p", "late-modules", "-m", "app/probe.Main")

    execution = subprocess.run(
        command,
        cwd=run_directory,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert execution.stdout.strip().endswith("RUNTIME")
    with pytest.raises(ValueError, match="unsupported Java launcher option"):
        snapshot_command_tools(command, base_directory=plan_directory)


@pytest.mark.parametrize(
    "unsafe_tokens",
    (
        ("-p", "late-modules", "-m", "app"),
        ("--module-path=late-modules", "-m", "app"),
        ("--upgrade-module-path", "late-modules", "org.cpsolver.Main"),
        ("--patch-module", "app=late-patches", "org.cpsolver.Main"),
        ("--patch-module=app=late-patches", "org.cpsolver.Main"),
        ("-agentpath:late-agent", "org.cpsolver.Main"),
        ("-agentpath:/absolute/agent=payload", "org.cpsolver.Main"),
        ("-javaagent:late-agent=payload", "org.cpsolver.Main"),
        ("-javaagent:late-agent.jar=payload", "org.cpsolver.Main"),
        ("-agentlib:jdwp=transport=dt_socket", "org.cpsolver.Main"),
        ("-splash:late.png", "org.cpsolver.Main"),
        ("-Xbootclasspath:late-boot", "org.cpsolver.Main"),
        ("-Xbootclasspath/a:late-boot", "org.cpsolver.Main"),
        ("-Xbootclasspath/p:late-boot", "org.cpsolver.Main"),
        ("-Djava.ext.dirs=late-ext", "org.cpsolver.Main"),
        ("-Djava.endorsed.dirs=late-endorsed", "org.cpsolver.Main"),
        ("-Djava.security.properties==file:late.security", "org.cpsolver.Main"),
        ("-Djava.security.policy=late.policy", "org.cpsolver.Main"),
        ("-Djava.security.krb5.conf=late.conf", "org.cpsolver.Main"),
        ("-Djavax.net.ssl.keyStore=late.keys", "org.cpsolver.Main"),
        ("-Djavax.net.ssl.trustStore=late.trust", "org.cpsolver.Main"),
        ("-DpluginPath=late.plugin", "org.cpsolver.Main"),
        ("-DunknownScalar=17", "org.cpsolver.Main"),
        ("-Djava.security.policy==file:late.policy", "org.cpsolver.Main"),
        ("-XX:SharedArchiveFile=late.jsa", "org.cpsolver.Main"),
        ("-XX:ArchiveClassesAtExit=late.jsa", "org.cpsolver.Main"),
        ("-XX:SharedClassListFile=late.lst", "org.cpsolver.Main"),
        ("-XX:DumpLoadedClassList=late.lst", "org.cpsolver.Main"),
        ("-XX:VMOptionsFile=late.options", "org.cpsolver.Main"),
        ("-XX:Flags=late.flags", "org.cpsolver.Main"),
        ("-XX:CompilerDirectivesFile=late.json", "org.cpsolver.Main"),
        ("-XX:CompileCommandFile=late.commands", "org.cpsolver.Main"),
        ("-XX:ReplayDataFile=late.replay", "org.cpsolver.Main"),
        ("-XX:OnError=touch late", "org.cpsolver.Main"),
        ("-XX:OnOutOfMemoryError=touch late", "org.cpsolver.Main"),
        ("-XX:StartFlightRecording=settings=late.jfc", "org.cpsolver.Main"),
        ("-XX:FlightRecorderOptions=repository=late-jfr", "org.cpsolver.Main"),
        ("-XX:CRaCRestoreFrom=late-crac", "org.cpsolver.Main"),
        ("-XX:UnknownScalar=1", "org.cpsolver.Main"),
    ),
)
def test_direct_java_argv_rejects_unsafe_loading_and_execution_options(
    tmp_path: Path,
    unsafe_tokens: tuple[str, ...],
) -> None:
    java = tmp_path / "java"
    java.write_bytes(b"synthetic java executable")
    classpath = _jar(tmp_path / "base.jar")

    with pytest.raises(ValueError, match="unsupported Java launcher option"):
        snapshot_command_tools(
            (
                str(java),
                "-cp",
                str(classpath),
                *unsafe_tokens,
                "{instance_path}",
            ),
            base_directory=tmp_path,
        )


def test_direct_java_argv_allows_pinned_cpsolver_scalar_contract(
    tmp_path: Path,
) -> None:
    java = tmp_path / "java"
    java.write_bytes(b"synthetic java executable")
    classpath = _jar(tmp_path / "cpsolver.jar")

    command, manifest, _digest = snapshot_command_tools(
        (
            str(java),
            "-Xmx2g",
            "-XX:ActiveProcessorCount=1",
            "-DTermination.TimeOut={time_limit_seconds}",
            "-DGeneral.Seed={seed}",
            "-DParallel.NrSolvers={workers}",
            "-cp",
            str(classpath),
            "org.cpsolver.Main",
            "{instance_path}",
            "{output_path}",
        ),
        base_directory=tmp_path,
    )

    assert command[0] == str(java.resolve())
    assert str(classpath.resolve()) in {row["path"] for row in manifest}

    scalar_jar = _jar(tmp_path / "scalar.jar")
    _command, scalar_manifest, _digest = snapshot_command_tools(
        (
            str(java),
            "-Xms256m",
            "-DTermination.TimeOut=10",
            "-DGeneral.Seed=17",
            "-DParallel.NrSolvers=1",
            "-jar",
            str(scalar_jar),
            "{instance_path}",
        ),
        base_directory=tmp_path,
    )
    assert str(scalar_jar.resolve()) in {row["path"] for row in scalar_manifest}


@pytest.mark.parametrize("launcher", ("classpath", "jar"))
def test_java_jar_manifest_external_classpath_is_rejected(
    tmp_path: Path,
    launcher: str,
) -> None:
    java = tmp_path / "java"
    java.write_bytes(b"synthetic java executable")
    dependency = _jar(tmp_path / "dep.jar")
    main = _jar(
        tmp_path / "main.jar",
        manifest="Manifest-Version: 1.0\nClass-Path: dep.jar\n\n",
    )
    command = (
        (str(java), "-jar", str(main), "{instance_path}")
        if launcher == "jar"
        else (
            str(java),
            "-cp",
            str(main),
            "org.cpsolver.Main",
            "{instance_path}",
        )
    )

    with pytest.raises(ValueError, match="manifest declares external loading"):
        snapshot_command_tools(command, base_directory=tmp_path)

    before = sha256_file(dependency)
    _jar(dependency, manifest="Manifest-Version: 1.0\nCreated-By: mutation\n\n")
    assert sha256_file(dependency) != before


def test_java_jar_manifest_dependency_mutation_changes_actual_execution(
    tmp_path: Path,
) -> None:
    java = shutil.which("java")
    javac = shutil.which("javac")
    if java is None or javac is None:
        pytest.skip("Java toolchain is unavailable")
    dependency_source = tmp_path / "Dependency.java"
    main_source = tmp_path / "Main.java"
    dependency_classes = tmp_path / "dependency-classes"
    main_classes = tmp_path / "main-classes"
    dependency_classes.mkdir()
    main_classes.mkdir()

    def build_dependency(label: str) -> Path:
        dependency_source.write_text(
            "public class Dependency { static String value() { "
            f'return "{label}"; }} }}\n',
            encoding="utf-8",
        )
        subprocess.run(
            (javac, "-d", str(dependency_classes), str(dependency_source)),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        path = tmp_path / "dep.jar"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n\n")
            archive.write(dependency_classes / "Dependency.class", "Dependency.class")
        return path

    dependency = build_dependency("FROZEN")
    main_source.write_text(
        "public class Main { public static void main(String[] a) { "
        "System.out.print(Dependency.value()); } }\n",
        encoding="utf-8",
    )
    subprocess.run(
        (
            javac,
            "-cp",
            str(dependency),
            "-d",
            str(main_classes),
            str(main_source),
        ),
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    main = tmp_path / "main.jar"
    with zipfile.ZipFile(main, "w") as archive:
        archive.writestr(
            "META-INF/MANIFEST.MF",
            "Manifest-Version: 1.0\nMain-Class: Main\nClass-Path: dep.jar\n\n",
        )
        archive.write(main_classes / "Main.class", "Main.class")

    first = subprocess.run(
        (java, "-jar", str(main)),
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    dependency = build_dependency("RUNTIME")
    second = subprocess.run(
        (java, "-jar", str(main)),
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert first.stdout == "FROZEN"
    assert second.stdout.strip().endswith("RUNTIME")
    assert dependency.is_file()
    with pytest.raises(ValueError, match="manifest declares external loading"):
        snapshot_command_tools(
            (java, "-jar", str(main), "{instance_path}"),
            base_directory=tmp_path,
        )


def test_declared_java_jar_manifest_external_loading_is_rejected(
    tmp_path: Path,
) -> None:
    script = tmp_path / "solver.py"
    script.write_text("print('solver')\n", encoding="utf-8")
    agent = _jar(
        tmp_path / "agent.jar",
        manifest="Manifest-Version: 1.0\nBoot-Class-Path: dep.jar\n\n",
    )

    with pytest.raises(ValueError, match="manifest declares external loading"):
        snapshot_command_tools(
            (sys.executable, str(script)),
            base_directory=tmp_path,
            declared_artifacts=(str(agent),),
        )


@pytest.mark.parametrize(
    "command,error",
    [
        ((sys.executable, "missing-solver.py"), "cannot be resolved"),
        ((sys.executable, "-m", "unresolved.module"), "module execution"),
        (("/bin/sh", "-c", "echo unresolved"), "unresolved benchmark logic"),
    ],
)
def test_command_tool_snapshot_fails_closed_on_unresolved_logic(
    tmp_path: Path,
    command: tuple[str, ...],
    error: str,
) -> None:
    with pytest.raises(ValueError, match=error):
        snapshot_command_tools(command, base_directory=tmp_path)


def test_command_tool_snapshot_rejects_launchers_and_templated_behavior(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "plugin-17.py"
    plugin.write_text("print('plugin')\n", encoding="utf-8")

    for command in (
        ("/bin/sh", "-ce", "echo unresolved"),
        ("/usr/bin/env", "sh", "-c", "echo unresolved"),
        (sys.executable, str(tmp_path / "plugin-{seed}.py")),
    ):
        with pytest.raises(ValueError, match="launcher|templated behavior"):
            snapshot_command_tools(command, base_directory=tmp_path)


def test_command_tool_snapshot_hashes_static_runtime_models(tmp_path: Path) -> None:
    script = tmp_path / "solver.py"
    script.write_text("print('solver')\n", encoding="utf-8")
    model = tmp_path / "quality.onnx"
    model.write_bytes(b"frozen-model")

    _command, manifest, _digest = snapshot_command_tools(
        (sys.executable, str(script), f"--model={model}"),
        base_directory=tmp_path,
    )

    assert str(model.resolve()) in {row["path"] for row in manifest}
    model.write_bytes(b"mutated-model")
    assert tool_snapshot_matches(manifest) is False


def test_command_tool_snapshot_hashes_unknown_suffix_existing_behavior_path(
    tmp_path: Path,
) -> None:
    script = tmp_path / "solver.py"
    script.write_text("print('solver')\n", encoding="utf-8")
    plugin = tmp_path / "solver.plugin"
    plugin.write_bytes(b"frozen-plugin")

    _command, manifest, _digest = snapshot_command_tools(
        (sys.executable, str(script), "--plugin", str(plugin)),
        base_directory=tmp_path,
    )

    assert str(plugin.resolve()) in {row["path"] for row in manifest}
    inline_command, inline_manifest, _inline_digest = snapshot_command_tools(
        (sys.executable, str(script), f"--plugin={plugin}"),
        base_directory=tmp_path,
    )
    assert inline_command[-1] == f"--plugin={plugin.resolve()}"
    assert str(plugin.resolve()) in {row["path"] for row in inline_manifest}
    plugin.write_bytes(b"mutated-plugin")
    assert tool_snapshot_matches(manifest) is False


def test_command_tool_snapshot_rejects_missing_path_like_assignments(
    tmp_path: Path,
) -> None:
    script = tmp_path / "solver.py"
    script.write_text("print('solver')\n", encoding="utf-8")

    for missing in (
        tmp_path / "late.plugin",
        Path("plugins") / "late.plugin",
        Path("late.plugin"),
    ):
        with pytest.raises(ValueError, match="cannot be resolved"):
            snapshot_command_tools(
                (sys.executable, str(script), f"--plugin={missing}"),
                base_directory=tmp_path,
            )

    command, _manifest, _digest = snapshot_command_tools(
        (sys.executable, str(script), "--temperature=0.5", "--strategy=fast"),
        base_directory=tmp_path,
    )
    assert command[-2:] == ("--temperature=0.5", "--strategy=fast")

    with pytest.raises(ValueError, match="cannot be resolved"):
        snapshot_command_tools(
            (sys.executable, str(script), "--plugin", "late.plugin"),
            base_directory=tmp_path,
        )


def test_command_tool_snapshot_rejects_all_generic_response_files(
    tmp_path: Path,
) -> None:
    script = tmp_path / "solver.py"
    script.write_text("print('solver')\n", encoding="utf-8")
    existing = tmp_path / "existing.args"
    existing.write_text("--mode=frozen\n", encoding="utf-8")
    nested = tmp_path / "nested.args"
    nested.write_text("--mode=nested\n", encoding="utf-8")
    outer = tmp_path / "outer.args"
    outer.write_text(f"@{nested}\n", encoding="utf-8")

    for response_token in (
        f"@{existing}",
        "@existing.args",
        f"@{tmp_path / 'missing.args'}",
        "@missing-relative.args",
        f"@{outer}",
        "@",
    ):
        with pytest.raises(ValueError, match="command @response files are unsupported"):
            snapshot_command_tools(
                (sys.executable, str(script), response_token),
                base_directory=tmp_path,
            )
    with pytest.raises(ValueError, match="command @response files are unsupported"):
        snapshot_command_tools(("@executable.args",), base_directory=tmp_path)


def test_solver_and_validator_specs_reject_generic_response_files(
    tmp_path: Path,
) -> None:
    script = tmp_path / "tool.py"
    script.write_text("print('tool')\n", encoding="utf-8")
    response = tmp_path / "tool.args"
    response.write_text("--plugin=solver.plugin\n", encoding="utf-8")

    with pytest.raises(ValueError, match="command @response files are unsupported"):
        BenchmarkSolverSpec(
            solver_id="unsafe-comparator",
            model="external_command",
            role="comparator",
            command=(
                sys.executable,
                str(script),
                f"@{response}",
                "{instance_path}",
                "{output_path}",
                "{seed}",
                "{time_limit_seconds}",
            ),
            artifact_base_directory=tmp_path,
        )

    with pytest.raises(ValueError, match="command @response files are unsupported"):
        BenchmarkCaseSpec(
            case_id="unsafe-validator",
            family_id="itc2019",
            instance_path=str(_instance(tmp_path, "unsafe-validator.xml")),
            time_limit_seconds=1.0,
            official_validator_command=(
                sys.executable,
                str(script),
                f"@{response}",
            ),
            artifact_base_directory=tmp_path,
        )


def test_generic_response_file_plugin_has_real_hidden_mutation(
    tmp_path: Path,
) -> None:
    script = tmp_path / "response_solver.py"
    script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "response = Path(sys.argv[1][1:])\n"
        "plugin_arg = next(line for line in response.read_text().splitlines() "
        "if line.startswith('--plugin='))\n"
        "print(Path(plugin_arg.split('=', 1)[1]).read_text(), end='')\n",
        encoding="utf-8",
    )
    plugin = tmp_path / "solver.plugin"
    plugin.write_text("FROZEN", encoding="utf-8")
    response = tmp_path / "solver.args"
    response.write_text(f"--plugin={plugin}\n", encoding="utf-8")
    command = (sys.executable, str(script), f"@{response}")

    frozen = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    plugin.write_text("MUTATED", encoding="utf-8")
    mutated = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert frozen.stdout == "FROZEN"
    assert mutated.stdout == "MUTATED"
    with pytest.raises(ValueError, match="command @response files are unsupported"):
        snapshot_command_tools(command, base_directory=tmp_path)


def test_child_environment_is_allowlisted_and_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLANORA_SOLVER_PLUGIN", "/tmp/evil.plugin")
    monkeypatch.setenv("LD_PRELOAD", "/tmp/evil.so")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/evil-libs")
    monkeypatch.setenv("PYTHONPATH", "/tmp/evil-python")
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-leak")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("SYSTEMROOT", "C:\\Windows")

    environment = _child_environment()

    fixed = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.defpath,
        "PYTHONHASHSEED": "0",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "TZ": "UTC",
    }
    assert {name: environment[name] for name in fixed} == fixed
    assert environment["SYSTEMROOT"] == "C:\\Windows"
    assert set(environment) <= set(fixed) | {"SYSTEMROOT", "WINDIR"}
    assert not any(name.startswith("PLANORA_") for name in environment)


def test_official_validator_adapter_runs_under_same_clean_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PLANORA_VALIDATOR_PLUGIN", "/tmp/evil.plugin")
    monkeypatch.setenv("LD_PRELOAD", "/tmp/evil.so")
    captured: dict[str, str] = {}

    def capture_validator(record: dict[str, object], **_kwargs: object) -> None:
        captured.update(os.environ)
        record["official_validator_status"] = "agreement"
        record["official_validator_agreement"] = True

    monkeypatch.setattr(
        "benchmarks.multifamily_harness.resolve_benchmark_entrypoint",
        lambda _reference: object(),
    )
    monkeypatch.setattr(
        "benchmarks.multifamily_harness._execute_official_validator",
        capture_validator,
    )
    output = tmp_path / "solution.out"
    output.write_text("solution\n", encoding="utf-8")
    record: dict[str, object] = {}

    _attach_official_validation(
        record,
        family_id="itc2007-cbctt",
        command=("/bin/true",),
        command_tool_manifest=(),
        instance_path=_instance(tmp_path, "validator.ctt"),
        output_path=output,
        independent_validation=None,
        timeout_seconds=1.0,
    )

    assert "PLANORA_VALIDATOR_PLUGIN" not in captured
    assert "LD_PRELOAD" not in captured
    assert captured == _child_environment()
    assert os.environ["PLANORA_VALIDATOR_PLUGIN"] == "/tmp/evil.plugin"


def _record(
    *,
    condition: str,
    family: str,
    case: str,
    effective: bool,
    feasible: bool,
    authority: str,
    score: float | None,
    vector: list[int | float] | None,
    official_configured: bool = False,
    official_agreement: bool | None = None,
    source_match: bool = True,
) -> dict[str, object]:
    return {
        "condition_id": condition,
        "family_id": family,
        "case_id": case,
        "status": "COMPLETED",
        "effective": effective,
        "feasible": feasible,
        "score_authority": authority,
        "score_total": score,
        "score_vector": vector,
        "official_validator_configured": official_configured,
        "official_validator_agreement": official_agreement,
        "source_snapshot_match": source_match,
    }


def test_aggregation_keeps_families_and_score_authorities_separate() -> None:
    records: list[dict[str, object]] = []
    for index in range(30):
        records.append(
            _record(
                condition="ctt-condition",
                family="itc2007-cbctt",
                case="ctt",
                effective=True,
                feasible=True,
                authority=SCORE_AUTHORITY_OFFICIAL,
                score=float(100 + index),
                vector=[100 + index],
                official_configured=True,
                official_agreement=True,
            )
        )
        records.append(
            _record(
                condition="xhstt-condition",
                family="xhstt",
                case="school",
                effective=True,
                feasible=index != 0,
                authority=SCORE_AUTHORITY_INDEPENDENT,
                score=None if index == 0 else float(index),
                vector=[1, 0] if index == 0 else [0, index],
            )
        )
    records.append(
        _record(
            condition="unitime-condition",
            family="unitime-native",
            case="unitime",
            effective=True,
            feasible=True,
            authority=SCORE_AUTHORITY_NATIVE,
            score=4.5,
            vector=[0, 4.5],
        )
    )

    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=30,
    )
    assert summary["conditions"]["ctt-condition"]["best_score_vector"] == [100]
    assert (
        summary["conditions"]["ctt-condition"]["official_validator_agreement_complete"]
        is True
    )
    assert summary["families"]["itc2007-cbctt"]["score_authorities"] == {
        SCORE_AUTHORITY_OFFICIAL: 30
    }
    assert summary["families"]["xhstt"]["score_authorities"] == {
        SCORE_AUTHORITY_INDEPENDENT: 30
    }
    assert summary["families"]["unitime-native"]["score_authorities"] == {
        SCORE_AUTHORITY_NATIVE: 1
    }
    assert summary["conditions"]["unitime-condition"]["effective_target_met"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False
    assert "no cross-family" in summary["comparison_scope"]


def _paired_itc2019_plan(tmp_path: Path) -> BenchmarkPlan:
    comparator = BenchmarkSolverSpec(
        solver_id="cpsolver",
        model="external_command",
        role="comparator",
        command=(
            "/bin/true",
            "{instance_path}",
            "{output_path}",
            "{seed}",
            "{time_limit_seconds}",
        ),
    )
    case = BenchmarkCaseSpec(
        case_id="paired-itc2019",
        family_id="itc2019",
        instance_path=str(_instance(tmp_path, "paired-itc2019.xml")),
        time_limit_seconds=10.0,
        seeds=(11, 13, 17),
        repetitions=2,
        workers=1,
        cpu_affinity=0,
        solvers=(BenchmarkSolverSpec.planora(), comparator),
    )
    return make_smoke_plan(
        [case],
        corpus_manifest=make_corpus_manifest([case], corpus_id="itc2019-complete"),
    )


def _paired_record(execution: object) -> dict[str, object]:
    row = execution.to_dict()
    config = row["config"]
    solver = config["solver"]
    seed = int(config["seed"])
    planora_score = 10
    comparator_scores = {11: 11, 13: 10, 17: 9}
    score = planora_score if solver["role"] == "planora" else comparator_scores[seed]
    run_directory = (
        Path(row["instance_path"]).parent / "runs" / str(row["execution_id"])
    ).resolve()
    run_directory.mkdir(parents=True, exist_ok=True)
    request_path = run_directory / "request.json"
    result_path = run_directory / "result.json"
    solution_suffix = {
        "itc2007-cbctt": ".out",
        "itc2007-pe": ".sln",
        "itc2007-exam": ".sln",
        "cbctt-extended": ".out",
        "itc2019": ".xml",
        "unitime-native": ".xml",
        "xhstt": ".xml",
    }[str(config["family_id"])]
    output_path = run_directory / f"solution{solution_suffix}"
    if config["family_id"] == "itc2019":
        output_path.write_text(
            '<solution name="native-toy" runtime="0">\n'
            '  <class id="CL" days="1" start="0" weeks="1" room="R"/>\n'
            "</solution>\n",
            encoding="utf-8",
        )
    else:
        output_path.write_text(f"score={score}\n", encoding="utf-8")
    source_sha256 = _current_test_source_sha256()
    plan_sha256 = "e" * 64
    record: dict[str, object] = {
        "execution_id": row["execution_id"],
        "pair_cell_id": row["pair_cell_id"],
        "pair_order_position": row["pair_order_position"],
        "condition_id": row["condition_id"],
        "config_sha256": row["config_sha256"],
        "family_id": config["family_id"],
        "case_id": config["case_id"],
        "input_sha256": row["input_sha256"],
        "input_sha256_expected": row["input_sha256"],
        "seed": seed,
        "repetition": int(config["repetition"]),
        "solver_id": solver["solver_id"],
        "solver_model": solver["model"],
        "solver_role": solver["role"],
        "solver_command_sha256": solver["command_sha256"],
        "solver_tool_snapshot_sha256": solver["tool_snapshot_sha256"],
        "evidence_classification": solver["evidence_classification"],
        "official_validator_tool_snapshot_sha256": config[
            "official_validator_tool_snapshot_sha256"
        ],
        "official_validator_evidence_classification": config[
            "official_validator_evidence_classification"
        ],
        "configured_solver_time_scope": solver["timing_scope"],
        "configured_solver_time_limit_seconds": config["time_limit_seconds"],
        "configured_solver_elapsed_seconds": 9.0,
        "configured_solver_budget_tolerance_seconds": 1e-6,
        "status": "COMPLETED",
        "effective": True,
        "feasible": True,
        "solution_complete": True,
        "score_authority": SCORE_AUTHORITY_INDEPENDENT,
        "score_total": score,
        "score_vector": [score],
        "score_components": {
            "time": score,
            "room": 0,
            "distribution": 0,
            "student": 0,
            "weighted_time": score,
            "weighted_room": 0,
            "weighted_distribution": 0,
            "weighted_student": 0,
            "total": score,
        },
        "independent_validation": {"errors": [], "feasible": True},
        "official_validator_configured": False,
        "official_validator_agreement": None,
        "independent_validator_status": "completed",
        "solver_deadline_overrun_seconds": 0.0,
        "configured_solver_budget_compliant": True,
        "configured_solver_budget_compliance_basis": (
            "native_reported_overrun_and_harness_observed_solver_elapsed"
            if solver["model"] == "planora_native"
            else "required_configured_limit_argv_and_bounded_process_completion"
        ),
        "source_snapshot_match": True,
        "source_sha256_expected": source_sha256,
        "source_sha256_worker_start": source_sha256,
        "source_sha256_worker_end": source_sha256,
        "source_sha256_supervisor_after": source_sha256,
        "input_snapshot_match": True,
        "input_sha256_worker_start": row["input_sha256"],
        "input_sha256_worker_end": row["input_sha256"],
        "input_sha256_supervisor_after": row["input_sha256"],
        "tool_snapshot_match": True,
        "official_validator_tool_snapshot_match": True,
        "output_path": str(output_path),
        "output_sha256": sha256_file(output_path),
        "solve_wall_time_seconds": 9.0,
        "worker_wall_time_seconds": 9.25,
        "supervisor_wall_time_seconds": 9.5,
        "worker_pid": 1234,
        "plan_sha256": plan_sha256,
        "timed_out": False,
        "exit_code": 0,
        "command": [
            str(Path(sys.executable).resolve()),
            "-m",
            "benchmarks.multifamily_harness",
            "worker",
            "--request",
            str(request_path),
            "--result",
            str(result_path),
        ],
    }
    if solver["model"] == "external_command":
        record["external_solver_process"] = {
            "timed_out": False,
            "exit_code": 0,
        }
    request_payload = {
        "schema_version": "planora.multifamily-benchmark.v2",
        "repo_root": str(Path.cwd().resolve()),
        "run_directory": str(run_directory),
        "plan_sha256": plan_sha256,
        "expected_source_sha256": source_sha256,
        "source_roots": list(DEFAULT_SOURCE_ROOTS),
        "execution": row,
    }
    request_path.write_text(
        json.dumps(request_payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    supervisor_only = {
        "command",
        "timed_out",
        "exit_code",
        "supervisor_wall_time_seconds",
    }
    worker_payload = {
        key: value for key, value in record.items() if key not in supervisor_only
    }
    result_path.write_text(
        json.dumps(worker_payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    record.update(
        worker_request_path=str(request_path),
        worker_request_sha256=sha256_file(request_path),
        worker_result_path=str(result_path),
        worker_result_sha256=sha256_file(result_path),
        supervisor_python_path=str(Path(sys.executable).resolve()),
        supervisor_python_sha256=sha256_file(Path(sys.executable).resolve()),
    )
    return record


def _reseal_paired_worker_result(record: dict[str, object]) -> None:
    """Keep synthetic worker evidence aligned after a fixture changes its result."""

    result_path = Path(str(record["worker_result_path"]))
    supervisor_only = {
        "command",
        "timed_out",
        "exit_code",
        "supervisor_wall_time_seconds",
        "worker_request_path",
        "worker_request_sha256",
        "worker_result_path",
        "worker_result_sha256",
        "supervisor_python_path",
        "supervisor_python_sha256",
    }
    worker_payload = {
        key: value for key, value in record.items() if key not in supervisor_only
    }
    result_path.write_text(
        json.dumps(worker_payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    record["worker_result_sha256"] = sha256_file(result_path)


def _native_replicated_itc2019_plan(tmp_path: Path) -> BenchmarkPlan:
    instance = tmp_path / "native-itc2019.xml"
    instance.write_text(
        '<problem name="native-toy" nrDays="1" slotsPerDay="2" nrWeeks="1">\n'
        '  <optimization time="1" room="1" distribution="1" student="1"/>\n'
        '  <rooms><room id="R" capacity="1"/></rooms>\n'
        '  <courses><course id="C"><config id="CFG"><subpart id="SP">\n'
        '    <class id="CL" limit="10">\n'
        '      <room id="R" penalty="0"/>'
        '<time days="1" start="0" length="1" weeks="1" penalty="10"/>\n'
        "    </class>\n"
        "  </subpart></config></course></courses>\n"
        "</problem>\n",
        encoding="utf-8",
    )
    case = BenchmarkCaseSpec(
        case_id="native-itc2019",
        family_id="itc2019",
        instance_path=str(instance),
        time_limit_seconds=10.0,
        seeds=(11, 13, 17),
        repetitions=2,
        workers=1,
        cpu_affinity=0,
    )
    return make_replicated_plan(
        [case],
        corpus_manifest=make_corpus_manifest([case], corpus_id="native-itc2019"),
    )


def _native_itc2019_summary_inputs(
    tmp_path: Path,
) -> tuple[BenchmarkPlan, tuple[object, ...], list[dict[str, object]]]:
    plan = _native_replicated_itc2019_plan(tmp_path)
    executions = expand_plan(plan)
    records = [_paired_record(execution) for execution in executions]
    return plan, executions, records


def _summarize_native_itc2019(
    plan: BenchmarkPlan,
    executions: tuple[object, ...],
    records: list[dict[str, object]],
    *,
    use_cached_source_snapshot: bool = True,
) -> dict[str, object]:
    kwargs = {
        "minimum_effective_runs_per_condition": 6,
        "expected_executions": tuple(
            execution.to_dict() for execution in executions
        ),
        "corpus_manifest": plan.corpus_manifest,
        "plan_mode": "replicated",
    }
    if not use_cached_source_snapshot:
        return summarize_records(records, **kwargs)
    expected_source = str(records[0]["source_sha256_expected"])
    with patch(
        "benchmarks.multifamily_harness.source_snapshot",
        return_value=(expected_source, []),
    ):
        return summarize_records(records, **kwargs)


def test_native_artifacts_are_independently_reparsed_for_replicated_evidence(
    tmp_path: Path,
) -> None:
    plan, executions, records = _native_itc2019_summary_inputs(tmp_path)

    summary = _summarize_native_itc2019(plan, executions, records)

    assert summary["gates"]["native_artifact_revalidation_complete"] is True
    assert all(
        row["status"] == "passed" for row in summary["native_artifact_revalidation"]
    )
    assert summary["gates"]["benchmark_evidence_ready"] is True


def test_native_artifact_revalidation_rejects_output_rewrite_and_record_rehash(
    tmp_path: Path,
) -> None:
    plan, executions, records = _native_itc2019_summary_inputs(tmp_path)
    output = Path(str(records[0]["output_path"]))
    output.write_text(
        '<solution name="native-toy"><class id="missing" days="1" start="0" weeks="1"/></solution>',
        encoding="utf-8",
    )
    records[0]["output_sha256"] = sha256_file(output)

    summary = _summarize_native_itc2019(plan, executions, records)

    assert summary["gates"]["native_artifact_revalidation_complete"] is False
    assert summary["gates"]["native_result_integrity_complete"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False


def test_native_artifact_revalidation_rejects_forged_score_and_validation_row(
    tmp_path: Path,
) -> None:
    plan, executions, records = _native_itc2019_summary_inputs(tmp_path)
    forged = 11
    records[0].update(
        score_vector=[forged],
        score_total=forged,
        score_components={
            "time": forged,
            "room": 0,
            "distribution": 0,
            "student": 0,
            "weighted_time": forged,
            "weighted_room": 0,
            "weighted_distribution": 0,
            "weighted_student": 0,
            "total": forged,
        },
        independent_validation={"errors": [], "feasible": True},
    )

    summary = _summarize_native_itc2019(plan, executions, records)

    assert summary["gates"]["native_artifact_revalidation_complete"] is False
    assert summary["native_artifact_revalidation"][0]["reason"].startswith(
        (
            "canonical_record_mismatch:",
            "revalidation_error:ValueError:native supervisor result field",
        )
    )
    assert summary["gates"]["benchmark_evidence_ready"] is False


def test_native_artifact_revalidation_rehashes_current_input_bytes(
    tmp_path: Path,
) -> None:
    plan, executions, records = _native_itc2019_summary_inputs(tmp_path)
    input_path = Path(str(executions[0].to_dict()["instance_path"]))
    input_path.write_text(
        input_path.read_text(encoding="utf-8") + "<!-- changed after plan -->\n",
        encoding="utf-8",
    )

    summary = _summarize_native_itc2019(plan, executions, records)

    assert summary["gates"]["native_artifact_revalidation_complete"] is False
    assert summary["native_artifact_revalidation"][0]["reason"] == (
        "input_sha256_mismatch"
    )
    assert summary["gates"]["benchmark_evidence_ready"] is False


def test_native_artifact_revalidation_rehashes_current_source_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from benchmarks import multifamily_harness

    plan, executions, records = _native_itc2019_summary_inputs(tmp_path)
    monkeypatch.setattr(
        multifamily_harness,
        "source_snapshot",
        lambda *_args, **_kwargs: ("f" * 64, []),
    )

    summary = _summarize_native_itc2019(
        plan,
        executions,
        records,
        use_cached_source_snapshot=False,
    )

    assert summary["gates"]["native_artifact_revalidation_complete"] is False
    assert summary["native_artifact_revalidation"][0]["reason"] == (
        "source_sha256_mismatch"
    )
    assert summary["gates"]["benchmark_evidence_ready"] is False


@pytest.mark.parametrize("command_mutation", ("missing", "evil", "substitute"))
def test_native_result_integrity_binds_supervisor_command_and_output_layout(
    tmp_path: Path,
    command_mutation: str,
) -> None:
    plan, executions, records = _native_itc2019_summary_inputs(tmp_path)
    if command_mutation == "missing":
        records[0].pop("command")
    elif command_mutation == "evil":
        records[0]["command"] = ["/bin/false"]
    else:
        records[0]["output_path"] = records[1]["output_path"]
        records[0]["output_sha256"] = records[1]["output_sha256"]

    summary = _summarize_native_itc2019(plan, executions, records)

    assert summary["gates"]["native_artifact_revalidation_complete"] is False
    assert summary["gates"]["native_result_integrity_complete"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False


@pytest.mark.parametrize("mutation", ("python", "request", "result"))
def test_native_result_integrity_binds_supervisor_provenance_files(
    tmp_path: Path,
    mutation: str,
) -> None:
    plan, executions, records = _native_itc2019_summary_inputs(tmp_path)
    command = list(records[0]["command"])
    if mutation == "python":
        command[0] = "/bin/true"
        records[0]["command"] = command
    elif mutation == "request":
        request_path = Path(str(records[0]["worker_request_path"]))
        request_path.write_text("{}\n", encoding="utf-8")
        records[0]["worker_request_sha256"] = sha256_file(request_path)
    else:
        result_path = Path(str(records[0]["worker_result_path"]))
        result_path.write_text("{}\n", encoding="utf-8")
        records[0]["worker_result_sha256"] = sha256_file(result_path)

    summary = _summarize_native_itc2019(plan, executions, records)

    assert summary["gates"]["native_artifact_revalidation_complete"] is False
    assert summary["gates"]["native_result_integrity_complete"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False


def test_native_result_integrity_rejects_unexpected_supervisor_error_key(
    tmp_path: Path,
) -> None:
    plan, executions, records = _native_itc2019_summary_inputs(tmp_path)
    records[0]["supervisor_error"] = "forged successful row"

    summary = _summarize_native_itc2019(plan, executions, records)

    assert summary["gates"]["native_result_integrity_complete"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False


@pytest.mark.parametrize(
    "link_kind", ("leaf_symlink", "parent_symlink", "hardlink", "fifo")
)
def test_native_artifact_snapshot_rejects_links(
    tmp_path: Path,
    link_kind: str,
) -> None:
    plan, executions, records = _native_itc2019_summary_inputs(tmp_path)
    output = Path(str(records[0]["output_path"]))
    other = Path(str(records[1]["output_path"]))
    if link_kind == "leaf_symlink":
        output.unlink()
        output.symlink_to(other)
        records[0]["output_sha256"] = records[1]["output_sha256"]
    elif link_kind == "hardlink":
        output.unlink()
        os.link(other, output)
        records[0]["output_sha256"] = records[1]["output_sha256"]
    elif link_kind == "fifo":
        output.unlink()
        os.mkfifo(output)
        records[0]["output_sha256"] = "0" * 64
    else:
        run_directory = output.parent
        relocated_parent = tmp_path / "relocated"
        relocated_parent.mkdir()
        relocated = relocated_parent / run_directory.name
        shutil.move(str(run_directory), str(relocated))
        run_directory.symlink_to(relocated, target_is_directory=True)

    summary = _summarize_native_itc2019(plan, executions, records)

    assert summary["gates"]["native_artifact_revalidation_complete"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False


def test_native_artifact_snapshot_detects_mutation_during_descriptor_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from benchmarks import multifamily_harness

    artifact = tmp_path / "stable.bin"
    artifact.write_bytes(b"A" * (1024 * 1024 + 1))
    real_read = os.read
    mutated = False

    def mutating_read(descriptor: int, count: int) -> bytes:
        nonlocal mutated
        payload = real_read(descriptor, count)
        if payload and not mutated:
            mutated = True
            artifact.write_bytes(b"B" * (1024 * 1024 + 1))
        return payload

    monkeypatch.setattr(os, "read", mutating_read)

    with pytest.raises(ValueError, match="artifact"):
        multifamily_harness._snapshot_regular_file_no_follow(
            artifact.resolve(), reject_hardlinks=False
        )


def test_native_artifact_revalidation_requires_unique_output_paths_and_inodes(
    tmp_path: Path,
) -> None:
    plan, executions, records = _native_itc2019_summary_inputs(tmp_path)
    records[1]["output_path"] = records[0]["output_path"]
    records[1]["output_sha256"] = records[0]["output_sha256"]
    records[1]["command"] = list(records[0]["command"])

    summary = _summarize_native_itc2019(plan, executions, records)

    assert summary["gates"]["native_artifact_revalidation_complete"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False


@pytest.mark.parametrize(
    "external_signal",
    (
        {"external_solver_process": {"timed_out": False, "exit_code": 0}},
        {"external_process_timeout_seconds": 11.0},
        {"external_process_wall_time_seconds": 1.0},
        {"solver_result": {"model": "external_command"}},
        {"evidence_classification": "unknown"},
        {"evidence_classification": None},
        {
            "configured_solver_budget_compliance_basis": (
                "required_configured_limit_argv_and_bounded_process_completion"
            )
        },
        {"score_authority": SCORE_AUTHORITY_OFFICIAL},
        {"solver_command_sha256": "b" * 64},
        {"solver_tool_snapshot_sha256": "c" * 64},
        {"official_validator_tool_snapshot_sha256": "a" * 64},
        {"official_validator_status": "agreement"},
        {"official_validator_agreement": True},
        {"official_validator_error": None},
        {"official_validation": {}},
        {"official_validation": {"feasible": True}},
    ),
)
def test_summary_external_signals_fail_closed_from_native_expected_context(
    tmp_path: Path,
    external_signal: dict[str, object],
) -> None:
    plan = _native_replicated_itc2019_plan(tmp_path)
    executions = expand_plan(plan)
    records = [_paired_record(execution) for execution in executions]
    expected = tuple(execution.to_dict() for execution in executions)

    baseline = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=expected,
        corpus_manifest=plan.corpus_manifest,
        plan_mode="replicated",
    )
    assert baseline["gates"]["claim_grade_tooling"] is True
    assert baseline["gates"]["benchmark_evidence_ready"] is True

    records[0].update(external_signal)
    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=expected,
        corpus_manifest=plan.corpus_manifest,
        allow_equal_wall_time_claim=True,
        plan_mode="replicated",
    )

    assert summary["gates"]["external_tooling_present"] is True
    assert summary["gates"]["claim_grade_tooling"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False
    assert summary["gates"]["superiority_claim_ready"] is False
    assert summary["gates"]["equal_wall_time_claim_permitted"] is False


def test_summary_rejects_forged_native_expected_config_with_external_command(
    tmp_path: Path,
) -> None:
    plan = _native_replicated_itc2019_plan(tmp_path)
    executions = expand_plan(plan)
    records = [_paired_record(execution) for execution in executions]
    expected = json.loads(json.dumps([execution.to_dict() for execution in executions]))
    expected[0]["config"]["solver"]["command"] = ["/tmp/unfrozen-solver"]

    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=expected,
        corpus_manifest=plan.corpus_manifest,
        plan_mode="replicated",
    )

    assert summary["gates"]["expected_configs_self_consistent"] is False
    assert summary["gates"]["execution_identity_exact"] is False
    assert summary["gates"]["external_tooling_present"] is True
    assert summary["gates"]["benchmark_evidence_ready"] is False


@pytest.mark.parametrize(
    "timing_mutation",
    (
        {"configured_solver_budget_compliant": False},
        {"configured_solver_elapsed_seconds": 11.0},
        {"solver_deadline_overrun_seconds": 1.0},
        {"configured_solver_elapsed_seconds": float("nan")},
        {"configured_solver_elapsed_seconds": float("inf")},
        {"solver_deadline_overrun_seconds": float("nan")},
        {"solver_deadline_overrun_seconds": float("inf")},
        {"configured_solver_budget_tolerance_seconds": float("nan")},
        {"configured_solver_budget_tolerance_seconds": 0.1},
        {"configured_solver_budget_compliance_basis": "unverified"},
        {"configured_solver_time_scope": "whole_solver_process_wall"},
        {"timed_out": True},
        {"exit_code": 1},
        {"status": "WORKER_PROCESS_ERROR"},
        {"worker_result_error": "synthetic failure"},
    ),
)
def test_native_replicated_evidence_requires_exact_timing_budget_contract(
    tmp_path: Path,
    timing_mutation: dict[str, object],
) -> None:
    plan = _native_replicated_itc2019_plan(tmp_path)
    executions = expand_plan(plan)
    records = [_paired_record(execution) for execution in executions]
    records[0].update(timing_mutation)

    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=plan.corpus_manifest,
        allow_equal_wall_time_claim=True,
        plan_mode="replicated",
    )

    assert summary["gates"]["native_timing_budget_compliant"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False
    assert summary["gates"]["superiority_claim_ready"] is False
    assert summary["gates"]["equal_wall_time_claim_permitted"] is False


@pytest.mark.parametrize(
    "missing_field",
    (
        "configured_solver_budget_compliant",
        "configured_solver_elapsed_seconds",
        "configured_solver_budget_tolerance_seconds",
        "configured_solver_budget_compliance_basis",
        "configured_solver_time_scope",
        "solver_deadline_overrun_seconds",
        "timed_out",
        "exit_code",
    ),
)
def test_native_replicated_timing_gate_fails_closed_on_missing_fields(
    tmp_path: Path,
    missing_field: str,
) -> None:
    plan = _native_replicated_itc2019_plan(tmp_path)
    executions = expand_plan(plan)
    records = [_paired_record(execution) for execution in executions]
    records[0].pop(missing_field)

    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=plan.corpus_manifest,
        plan_mode="replicated",
    )

    assert summary["gates"]["native_timing_budget_compliant"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False


@pytest.mark.parametrize(
    "integrity_mutation",
    (
        {"effective": False},
        {"feasible": False},
        {"solution_complete": False},
        {"score_authority": "garbage"},
        {"score_vector": None},
        {"score_vector": [10.5]},
        {"score_vector": [True]},
        {"score_vector": [-1]},
        {"score_total": None},
        {"score_total": 10.0},
        {"score_total": float("nan")},
        {"score_total": float("inf")},
        {"score_components": {}},
        {"score_components": {"total": 10}},
        {
            "score_components": {
                "time": 10.0,
                "room": 0,
                "distribution": 0,
                "student": 0,
                "weighted_time": 10,
                "weighted_room": 0,
                "weighted_distribution": 0,
                "weighted_student": 0,
                "total": 10,
            }
        },
        {"independent_validator_status": "not_run"},
        {"independent_validator_status": "error"},
        {"independent_validation": None},
        {"independent_validation": {}},
        {"independent_validation": {"errors": [], "feasible": False}},
        {"independent_validation": {"errors": ["bad"], "feasible": True}},
        {"output_path": None},
        {"output_path": "relative.solution"},
        {"output_sha256": None},
        {"output_sha256": "0" * 64},
        {"adapter_error": "synthetic"},
        {"solve_wall_time_seconds": 9.1},
        {"solve_wall_time_seconds": float("nan")},
        {"worker_wall_time_seconds": 8.0},
        {"supervisor_wall_time_seconds": 8.0},
        {"input_sha256_expected": "0" * 64},
        {"input_sha256_worker_start": "0" * 64},
        {"input_sha256_worker_end": "0" * 64},
        {"input_sha256_supervisor_after": "0" * 64},
        {"source_sha256_expected": "0" * 64},
        {"source_sha256_worker_start": "0" * 64},
        {"source_sha256_worker_end": "0" * 64},
        {"source_sha256_supervisor_after": "0" * 64},
        {"worker_pid": 0},
        {"worker_pid": True},
    ),
)
def test_native_replicated_evidence_requires_complete_result_integrity(
    tmp_path: Path,
    integrity_mutation: dict[str, object],
) -> None:
    plan = _native_replicated_itc2019_plan(tmp_path)
    executions = expand_plan(plan)
    records = [_paired_record(execution) for execution in executions]
    records[0].update(integrity_mutation)

    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=plan.corpus_manifest,
        allow_equal_wall_time_claim=True,
        plan_mode="replicated",
    )

    assert summary["gates"]["native_result_integrity_complete"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False
    assert summary["gates"]["superiority_claim_ready"] is False
    assert summary["gates"]["equal_wall_time_claim_permitted"] is False


@pytest.mark.parametrize(
    "missing_field",
    (
        "effective",
        "feasible",
        "solution_complete",
        "score_authority",
        "score_vector",
        "score_total",
        "score_components",
        "independent_validator_status",
        "independent_validation",
        "output_path",
        "output_sha256",
        "input_sha256_expected",
        "input_sha256_worker_start",
        "input_sha256_worker_end",
        "input_sha256_supervisor_after",
        "source_sha256_expected",
        "source_sha256_worker_start",
        "source_sha256_worker_end",
        "source_sha256_supervisor_after",
        "solve_wall_time_seconds",
        "worker_wall_time_seconds",
        "supervisor_wall_time_seconds",
        "worker_pid",
    ),
)
def test_native_result_integrity_fails_closed_on_missing_fields(
    tmp_path: Path,
    missing_field: str,
) -> None:
    plan = _native_replicated_itc2019_plan(tmp_path)
    executions = expand_plan(plan)
    records = [_paired_record(execution) for execution in executions]
    records[0].pop(missing_field)

    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=plan.corpus_manifest,
        plan_mode="replicated",
    )

    assert summary["gates"]["native_result_integrity_complete"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False


def test_native_result_integrity_rehashes_current_output(tmp_path: Path) -> None:
    plan = _native_replicated_itc2019_plan(tmp_path)
    executions = expand_plan(plan)
    records = [_paired_record(execution) for execution in executions]
    Path(str(records[0]["output_path"])).write_text("mutated\n", encoding="utf-8")

    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=plan.corpus_manifest,
        plan_mode="replicated",
    )

    assert summary["gates"]["native_result_integrity_complete"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False


@pytest.mark.parametrize("family_id", ("itc2007-cbctt", "itc2007-pe"))
def test_replicated_native_lane_is_unavailable_when_validator_is_external(
    tmp_path: Path,
    family_id: str,
) -> None:
    case = BenchmarkCaseSpec(
        case_id=f"unavailable-{family_id}",
        family_id=family_id,
        instance_path=str(_instance(tmp_path, f"unavailable-{family_id}.dat")),
        time_limit_seconds=10.0,
        seeds=(11, 13, 17),
        repetitions=2,
        workers=1,
        cpu_affinity=0,
    )

    with pytest.raises(ValueError, match="replicated native evidence is unavailable"):
        make_replicated_plan(
            [case],
            corpus_manifest=make_corpus_manifest(
                [case], corpus_id=f"unavailable-{family_id}"
            ),
        )


def _canonical_native_score_payload(
    family_id: str,
) -> tuple[str, list[int | float], int | float, dict[str, object], dict[str, object]]:
    if family_id == "itc2007-exam":
        validation = {
            "feasible": True,
            "hard": {"total": 0},
            "objective": {"total": 7},
            "errors": [],
        }
        return SCORE_AUTHORITY_INDEPENDENT, [0, 7], 7, validation, validation
    if family_id == "cbctt-extended":
        score = {"total": 7}
        validation = {
            "feasible": True,
            "hard_violations": 0,
            "errors": [],
            "score": score,
        }
        return SCORE_AUTHORITY_INDEPENDENT, [0, 7], 7, score, validation
    if family_id == "itc2019":
        score = {
            "time": 7,
            "room": 0,
            "distribution": 0,
            "student": 0,
            "weighted_time": 7,
            "weighted_room": 0,
            "weighted_distribution": 0,
            "weighted_student": 0,
            "total": 7,
        }
        return (
            SCORE_AUTHORITY_INDEPENDENT,
            [7],
            7,
            score,
            {"errors": [], "feasible": True},
        )
    if family_id == "unitime-native":
        score = {
            "hard_violations": 0,
            "native_total": 7.5,
            "scheme": "planora-unitime-native-v1",
        }
        validation = {
            "feasible": True,
            "errors": [],
            "unsupported_features": [],
            "score": score,
        }
        return SCORE_AUTHORITY_NATIVE, [0, 7.5], 7.5, score, validation
    if family_id == "xhstt":
        score = {
            "hard_cost": 0,
            "soft_cost": 7,
            "lexicographic": [0, 7],
            "constraint_costs": [],
        }
        validation = {
            "feasible": True,
            "errors": [],
            "unsupported_features": [],
            "score": score,
        }
        return SCORE_AUTHORITY_INDEPENDENT, [0, 7], 7, score, validation
    raise AssertionError(f"unhandled family {family_id}")


def _native_claim_artifacts(
    tmp_path: Path,
    family_id: str,
) -> tuple[
    Path,
    bytes,
    tuple[str, list[int | float], int | float, dict[str, object], dict[str, object]],
]:
    input_path = tmp_path / f"claim-{family_id}.input"
    output_path = tmp_path / f"claim-{family_id}.output"

    if family_id == "itc2007-exam":
        from benchmarks.itc2007_exam import (
            ITC2007ExamAssignment,
            parse_itc2007_exam,
            validate_itc2007_exam_solution,
            write_itc2007_exam_solution,
        )

        input_path = input_path.with_suffix(".exam")
        output_path = output_path.with_suffix(".sln")
        input_path.write_text(
            """[Exams:1]
60, 0
[Periods:1]
01:06:2026, 09:00:00, 120, 0
[Rooms:1]
10, 0
[PeriodHardConstraints]
[RoomHardConstraints]
[InstitutionalWeightings]
TWOINAROW, 0
TWOINADAY, 0
PERIODSPREAD, 0
NONMIXEDDURATIONS, 0
FRONTLOAD, 0, 0, 0
""",
            encoding="utf-8",
        )
        problem = parse_itc2007_exam(input_path)
        assignments = (ITC2007ExamAssignment(0, 0, 0),)
        write_itc2007_exam_solution(output_path, assignments, problem=problem)
        validation = validate_itc2007_exam_solution(problem, assignments)
        payload = (
            SCORE_AUTHORITY_INDEPENDENT,
            [validation.hard.total, validation.objective.total],
            validation.objective.total,
            validation.to_dict(),
            validation.to_dict(),
        )
    elif family_id == "cbctt-extended":
        from benchmarks.cbctt import parse_cbctt_ectt
        from benchmarks.cbctt_native import (
            CBCTTAssignment,
            validate_cbctt_assignments,
            write_cbctt_solution,
        )

        input_path = input_path.with_suffix(".ectt")
        output_path = output_path.with_suffix(".sol")
        input_path.write_text(
            """Name: claim-ectt
Courses: 1
Rooms: 1
Days: 1
Periods_per_day: 1
Curricula: 1
Min_Max_Daily_Lectures: 0 1
UnavailabilityConstraints: 0
RoomConstraints: 0

COURSES:
c t 1 1 10 0

ROOMS:
r 20 0

CURRICULA:
q 1 c

UNAVAILABILITY_CONSTRAINTS:

ROOM_CONSTRAINTS:

END.
""",
            encoding="utf-8",
        )
        problem = parse_cbctt_ectt(input_path)
        assignments = (CBCTTAssignment("c", "r", 0, 0),)
        write_cbctt_solution(output_path, assignments)
        validation = validate_cbctt_assignments(problem, assignments, formulation="UD2")
        payload = (
            SCORE_AUTHORITY_INDEPENDENT,
            [validation.hard_violations, validation.score.total],
            validation.score.total,
            validation.score.to_dict(),
            validation.to_dict(),
        )
    elif family_id == "itc2019":
        from benchmarks.itc2019 import (
            ITC2019ClassPlacement,
            parse_itc2019_xml,
            score_itc2019_solution,
            write_itc2019_solution,
        )

        input_path = tmp_path / "claim-itc2019-instance.xml"
        output_path = tmp_path / "claim-itc2019-solution.xml"
        input_path.write_text(
            """<problem name="claim-itc2019" nrDays="1" slotsPerDay="2" nrWeeks="1">
  <optimization time="1" room="1" distribution="1" student="1"/>
  <rooms><room id="R" capacity="1"/></rooms>
  <courses><course id="C"><config id="CFG"><subpart id="SP">
    <class id="CL" limit="10"><room id="R" penalty="0"/><time days="1" start="0" length="1" weeks="1" penalty="7"/></class>
  </subpart></config></course></courses>
</problem>
""",
            encoding="utf-8",
        )
        problem = parse_itc2019_xml(input_path)
        placements = (ITC2019ClassPlacement("CL", "1", 0, "1", "R"),)
        write_itc2019_solution(problem, placements, {}, output_path)
        score = score_itc2019_solution(problem, placements, {})
        components = score.to_dict()
        payload = (
            SCORE_AUTHORITY_INDEPENDENT,
            [score.total],
            score.total,
            components,
            {"errors": [], "feasible": True},
        )
    elif family_id == "unitime-native":
        from benchmarks.unitime_native import (
            parse_unitime_xml,
            validate_unitime_solution,
            write_unitime_solution_xml,
        )

        input_path = tmp_path / "claim-unitime-instance.xml"
        output_path = tmp_path / "claim-unitime-solution.xml"
        input_path.write_text(
            """<timetable version="2.4" term="claim" nrDays="1" slotsPerDay="12">
  <rooms><room id="R" capacity="30"/></rooms>
  <instructors><instructor id="I"/></instructors>
  <classes><class id="A" offering="O" config="G" subpart="L" committed="false" classLimit="20">
    <instructor id="I"/><room id="R" pref="0" solution="true"/><time days="1" start="0" length="2" pref="0" solution="true"/>
  </class></classes>
  <groupConstraints/><students/>
</timetable>
""",
            encoding="utf-8",
        )
        problem = parse_unitime_xml(input_path)
        assert problem.embedded_solution is not None
        write_unitime_solution_xml(output_path, problem, problem.embedded_solution)
        validation = validate_unitime_solution(problem, problem.embedded_solution)
        score = validation.score
        payload = (
            SCORE_AUTHORITY_NATIVE,
            [score.hard_violations, score.native_total],
            score.native_total,
            score.to_dict(),
            validation.to_dict(),
        )
    elif family_id == "xhstt":
        from benchmarks.xhstt import (
            XHSTTMeet,
            XHSTTSolution,
            parse_xhstt,
            validate_xhstt_solution,
            write_xhstt_solution,
        )

        input_path = tmp_path / "claim-xhstt-instance.xml"
        output_path = tmp_path / "claim-xhstt-solution.xml"
        input_path.write_text(
            """<HighSchoolTimetableArchive><Instances><Instance Id="claim-xhstt">
  <MetaData><Name>Claim XHSTT</Name></MetaData>
  <Times><Time Id="T"><Name>T</Name></Time></Times>
  <Resources><ResourceTypes/><ResourceGroups/></Resources>
  <Events><EventGroups><EventGroup Id="All"><Name>All</Name></EventGroup></EventGroups>
    <Event Id="E"><Name>E</Name><Duration>1</Duration><EventGroups><EventGroup Reference="All"/></EventGroups></Event>
  </Events>
  <Constraints><AssignTimeConstraint Id="assign"><Name>assign</Name><Required>true</Required><Weight>1</Weight><CostFunction>Linear</CostFunction><AppliesTo><EventGroups><EventGroup Reference="All"/></EventGroups></AppliesTo></AssignTimeConstraint></Constraints>
</Instance></Instances></HighSchoolTimetableArchive>
""",
            encoding="utf-8",
        )
        problem = parse_xhstt(input_path)
        solution = XHSTTSolution(
            instance_id=problem.id,
            meets=(XHSTTMeet("E", 1, "T"),),
        )
        write_xhstt_solution(output_path, solution)
        validation = validate_xhstt_solution(problem, solution)
        score = validation.score
        payload = (
            SCORE_AUTHORITY_INDEPENDENT,
            list(score.lexicographic),
            score.soft_cost,
            score.to_dict(),
            validation.to_dict(),
        )
    else:
        raise AssertionError(f"unhandled family {family_id}")

    assert payload[4]["feasible"] is True
    return input_path, output_path.read_bytes(), payload


@pytest.mark.parametrize(
    "family_id",
    ("itc2007-exam", "cbctt-extended", "itc2019", "unitime-native", "xhstt"),
)
def test_native_replicated_family_score_contract_is_canonical(
    tmp_path: Path,
    family_id: str,
) -> None:
    instance_path, output_payload, canonical = _native_claim_artifacts(
        tmp_path, family_id
    )
    case = BenchmarkCaseSpec(
        case_id=f"canonical-{family_id}",
        family_id=family_id,
        instance_path=str(instance_path),
        time_limit_seconds=10.0,
        seeds=(11, 13, 17),
        repetitions=2,
        workers=1,
        cpu_affinity=0,
        options=(
            {"parser": {"instance_id": "claim-xhstt"}} if family_id == "xhstt" else {}
        ),
    )
    plan = make_replicated_plan(
        [case],
        corpus_manifest=make_corpus_manifest(
            [case], corpus_id=f"canonical-{family_id}"
        ),
    )
    executions = expand_plan(plan)
    authority, vector, total, components, validation = canonical
    records = [_paired_record(execution) for execution in executions]
    for record in records:
        output_path = Path(str(record["output_path"]))
        output_path.write_bytes(output_payload)
        record.update(
            {
                "score_authority": authority,
                "score_vector": vector,
                "score_total": total,
                "score_components": components,
                "independent_validation": validation,
                "output_sha256": sha256_file(output_path),
            }
        )
        _reseal_paired_worker_result(record)

    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=plan.corpus_manifest,
        plan_mode="replicated",
    )

    assert summary["gates"]["native_result_integrity_complete"] is True, summary[
        "native_artifact_revalidation"
    ]
    assert summary["gates"]["benchmark_evidence_ready"] is True

    records[0]["score_authority"] = "wrong"
    rejected = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=plan.corpus_manifest,
        plan_mode="replicated",
    )
    assert rejected["gates"]["native_result_integrity_complete"] is False
    assert rejected["gates"]["benchmark_evidence_ready"] is False


def test_native_cbctt_revalidation_rejects_conflicting_validator_formulation(
    tmp_path: Path,
) -> None:
    instance_path, output_payload, canonical = _native_claim_artifacts(
        tmp_path, "cbctt-extended"
    )
    case = BenchmarkCaseSpec(
        case_id="conflicting-cbctt-formulations",
        family_id="cbctt-extended",
        instance_path=str(instance_path),
        time_limit_seconds=10.0,
        seeds=(11, 13, 17),
        repetitions=2,
        workers=1,
        cpu_affinity=0,
        options={
            "solver": {"formulation": "UD2"},
            "validator": {"formulation": "UD3"},
        },
    )
    plan = make_replicated_plan(
        [case],
        corpus_manifest=make_corpus_manifest([case], corpus_id="conflicting-cbctt"),
    )
    executions = expand_plan(plan)
    authority, vector, total, components, validation = canonical
    records = [_paired_record(execution) for execution in executions]
    for record in records:
        output_path = Path(str(record["output_path"]))
        output_path.write_bytes(output_payload)
        record.update(
            score_authority=authority,
            score_vector=vector,
            score_total=total,
            score_components=components,
            independent_validation=validation,
            output_sha256=sha256_file(output_path),
        )
        _reseal_paired_worker_result(record)

    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=plan.corpus_manifest,
        plan_mode="replicated",
    )

    assert summary["gates"]["native_artifact_revalidation_complete"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False


def test_native_unitime_revalidation_uses_nondefault_sectioning_writer_mode(
    tmp_path: Path,
) -> None:
    from benchmarks.unitime_native import (
        UniTimeAssignment,
        UniTimeSolution,
        parse_unitime_xml,
        validate_unitime_solution,
        write_unitime_solution_xml,
    )

    instance = tmp_path / "unitime-sectioning-instance.xml"
    artifact = tmp_path / "unitime-sectioning-solution.xml"
    instance.write_text(
        """<sectioning version="1.0" initiative="claim" term="Fall" year="2026" nrDays="1" slotsPerDay="12">
  <offerings><offering id="O"><course id="C"/><config id="G" limit="1"><subpart id="S" itype="10">
    <section id="L" limit="1"><time days="1" start="0" length="2" dates="1"/></section>
  </subpart></config></offering></offerings>
  <students><student id="student"><course id="Q" priority="0" course="C"/></student></students>
</sectioning>
""",
        encoding="utf-8",
    )
    problem = parse_unitime_xml(instance, sectioning_solution_mode="current")
    solution = UniTimeSolution(
        kind="sectioning",
        assignments=(UniTimeAssignment("Q", section_ids=("L",)),),
    )
    validation = validate_unitime_solution(problem, solution)
    assert validation.feasible
    write_unitime_solution_xml(
        artifact,
        problem,
        solution,
        sectioning_solution_mode="current",
    )
    case = BenchmarkCaseSpec(
        case_id="unitime-sectioning-current",
        family_id="unitime-native",
        instance_path=str(instance),
        time_limit_seconds=10.0,
        seeds=(11, 13, 17),
        repetitions=2,
        workers=1,
        cpu_affinity=0,
        options={
            "parser": {"sectioning_solution_mode": "current"},
            "writer": {"sectioning_solution_mode": "current"},
        },
    )
    plan = make_replicated_plan(
        [case],
        corpus_manifest=make_corpus_manifest([case], corpus_id="unitime-current"),
    )
    executions = expand_plan(plan)
    records = [_paired_record(execution) for execution in executions]
    score = validation.score
    for record in records:
        output_path = Path(str(record["output_path"]))
        output_path.write_bytes(artifact.read_bytes())
        record.update(
            score_authority=SCORE_AUTHORITY_NATIVE,
            score_vector=[score.hard_violations, score.native_total],
            score_total=score.native_total,
            score_components=score.to_dict(),
            independent_validation=validation.to_dict(),
            output_sha256=sha256_file(output_path),
        )
        _reseal_paired_worker_result(record)

    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=plan.corpus_manifest,
        plan_mode="replicated",
    )

    assert summary["gates"]["native_artifact_revalidation_complete"] is True
    assert summary["gates"]["benchmark_evidence_ready"] is True

    course_dir = tmp_path / "wrong-kind"
    course_dir.mkdir()
    _, wrong_kind_payload, _ = _native_claim_artifacts(course_dir, "unitime-native")
    wrong_output = Path(str(records[0]["output_path"]))
    wrong_output.write_bytes(wrong_kind_payload)
    records[0]["output_sha256"] = sha256_file(wrong_output)
    rejected = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=plan.corpus_manifest,
        plan_mode="replicated",
    )
    assert rejected["gates"]["native_artifact_revalidation_complete"] is False
    assert rejected["gates"]["benchmark_evidence_ready"] is False


def test_native_xhstt_revalidation_honors_expected_instance_id(
    tmp_path: Path,
) -> None:
    instance, output_payload, canonical = _native_claim_artifacts(tmp_path, "xhstt")
    document = instance.read_text(encoding="utf-8")
    match = re.search(
        r'(<Instance Id="claim-xhstt">.*?</Instance>)', document, re.DOTALL
    )
    assert match is not None
    second = match.group(1).replace('Id="claim-xhstt"', 'Id="ignored-xhstt"', 1)
    instance.write_text(
        document.replace("</Instances>", second + "</Instances>"),
        encoding="utf-8",
    )

    def summary_for(instance_id: str) -> dict[str, object]:
        case = BenchmarkCaseSpec(
            case_id=f"xhstt-selection-{instance_id}",
            family_id="xhstt",
            instance_path=str(instance),
            time_limit_seconds=10.0,
            seeds=(11, 13, 17),
            repetitions=2,
            workers=1,
            cpu_affinity=0,
            options={"parser": {"instance_id": instance_id}},
        )
        plan = make_replicated_plan(
            [case],
            corpus_manifest=make_corpus_manifest(
                [case], corpus_id=f"xhstt-selection-{instance_id}"
            ),
        )
        executions = expand_plan(plan)
        authority, vector, total, components, validation = canonical
        records = [_paired_record(execution) for execution in executions]
        for record in records:
            output_path = Path(str(record["output_path"]))
            output_path.write_bytes(output_payload)
            record.update(
                score_authority=authority,
                score_vector=vector,
                score_total=total,
                score_components=components,
                independent_validation=validation,
                output_sha256=sha256_file(output_path),
            )
            _reseal_paired_worker_result(record)
        return summarize_records(
            records,
            minimum_effective_runs_per_condition=6,
            expected_executions=tuple(execution.to_dict() for execution in executions),
            corpus_manifest=plan.corpus_manifest,
            plan_mode="replicated",
        )

    selected = summary_for("claim-xhstt")
    wrong_instance = summary_for("ignored-xhstt")

    assert selected["gates"]["native_artifact_revalidation_complete"] is True
    assert selected["gates"]["benchmark_evidence_ready"] is True
    assert wrong_instance["gates"]["native_artifact_revalidation_complete"] is False
    assert wrong_instance["gates"]["benchmark_evidence_ready"] is False


@pytest.mark.parametrize(
    "family_id",
    ("itc2007-exam", "cbctt-extended", "itc2019", "xhstt"),
)
def test_standardized_native_scores_reject_fractional_values_even_if_self_consistent(
    tmp_path: Path,
    family_id: str,
) -> None:
    instance_path, output_payload, canonical = _native_claim_artifacts(
        tmp_path, family_id
    )
    case = BenchmarkCaseSpec(
        case_id=f"fractional-{family_id}",
        family_id=family_id,
        instance_path=str(instance_path),
        time_limit_seconds=10.0,
        seeds=(11, 13, 17),
        repetitions=2,
        workers=1,
        cpu_affinity=0,
    )
    plan = make_replicated_plan(
        [case],
        corpus_manifest=make_corpus_manifest(
            [case], corpus_id=f"fractional-{family_id}"
        ),
    )
    executions = expand_plan(plan)
    authority, vector, total, components, validation = canonical
    records = [_paired_record(execution) for execution in executions]
    for record in records:
        output_path = Path(str(record["output_path"]))
        output_path.write_bytes(output_payload)
        record.update(
            {
                "score_authority": authority,
                "score_vector": vector,
                "score_total": total,
                "score_components": components,
                "independent_validation": validation,
                "output_sha256": sha256_file(output_path),
            }
        )
        _reseal_paired_worker_result(record)
    records[0]["score_vector"] = [7.5] if family_id == "itc2019" else [0, 7.5]
    records[0]["score_total"] = 7.5

    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=plan.corpus_manifest,
        plan_mode="replicated",
    )

    assert summary["gates"]["native_result_integrity_complete"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False


def test_paired_summary_requires_exact_cells_and_reports_seed_level_wtl(
    tmp_path: Path,
) -> None:
    plan = _paired_itc2019_plan(tmp_path)
    executions = expand_plan(plan)
    records = [_paired_record(execution) for execution in executions]

    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        require_official_validator_agreement=True,
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=plan.corpus_manifest,
        plan_mode=plan.mode,
    )

    assert all(
        row["effective_runs"] == row["expected_runs"] == 6
        for row in summary["solver_conditions"].values()
    )
    assert summary["paired_comparisons"]["by_family"]["itc2019"] == {
        "wins": 2,
        "ties": 2,
        "losses": 2,
        "compared_cells": 6,
        "required_score_authority": SCORE_AUTHORITY_INDEPENDENT,
    }
    assert (
        summary["paired_comparisons"]["by_instance_seed"][
            "itc2019::paired-itc2019::seed-11"
        ]["wins"]
        == 2
    )
    assert summary["gates"]["execution_cells_exact_and_effective"] is True
    assert summary["gates"]["paired_cells_complete"] is True
    assert summary["gates"]["score_authority_enforced"] is True
    assert summary["gates"]["superiority_claim_ready"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False
    assert summary["gates"]["claim_grade_tooling"] is False
    assert summary["gates"]["external_diagnostic_complete"] is True
    assert summary["evidence_classification"] == (
        "diagnostic_unverified_external_tooling"
    )
    assert summary["gates"]["equal_wall_time_claim_permitted"] is False

    incomplete = summarize_records(
        records[:-1],
        minimum_effective_runs_per_condition=6,
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=plan.corpus_manifest,
        plan_mode=plan.mode,
    )
    assert incomplete["gates"]["execution_cells_exact_and_effective"] is False
    assert incomplete["gates"]["paired_cells_complete"] is False
    assert incomplete["gates"]["superiority_claim_ready"] is False


def test_paired_summary_rejects_wrong_score_authority(tmp_path: Path) -> None:
    plan = _paired_itc2019_plan(tmp_path)
    executions = expand_plan(plan)
    records = [_paired_record(execution) for execution in executions]
    records[0]["score_authority"] = SCORE_AUTHORITY_NATIVE

    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=plan.corpus_manifest,
        plan_mode=plan.mode,
    )

    assert summary["paired_comparisons"]["score_authority_enforced"] is False
    assert summary["gates"]["superiority_claim_ready"] is False


def test_summary_preserves_configured_minimum_when_expected_runs_are_smaller(
    tmp_path: Path,
) -> None:
    plan = _paired_itc2019_plan(tmp_path)
    executions = expand_plan(plan)[:6]
    records = [_paired_record(execution) for execution in executions]

    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=plan.corpus_manifest,
        plan_mode="replicated",
    )

    assert all(
        row["expected_runs"] == 3
        and row["effective_target"] == 6
        and row["effective_target_met"] is False
        for row in summary["solver_conditions"].values()
    )
    assert summary["gates"]["effective_target_met"] is False
    assert summary["gates"]["superiority_claim_ready"] is False


def test_standalone_replicated_summary_enforces_three_by_two_floor(
    tmp_path: Path,
) -> None:
    plan = _paired_itc2019_plan(tmp_path)
    executions = tuple(
        execution for execution in expand_plan(plan) if execution.repetition == 1
    )
    records = [_paired_record(execution) for execution in executions]

    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=3,
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=plan.corpus_manifest,
        plan_mode="replicated",
    )

    assert summary["gates"]["replicated_design_complete"] is False
    assert all(
        row["expected_runs"] == 3
        and row["effective_target"] == 6
        and row["effective_target_met"] is False
        for row in summary["solver_conditions"].values()
    )
    assert summary["paired_comparisons"]["superiority_claim_ready"] is False
    assert summary["gates"]["superiority_claim_ready"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False


def test_superiority_requires_replicated_mode_and_exact_corpus_manifest(
    tmp_path: Path,
) -> None:
    plan = _paired_itc2019_plan(tmp_path)
    executions = expand_plan(plan)
    records = [_paired_record(execution) for execution in executions]
    expected = tuple(execution.to_dict() for execution in executions)

    smoke = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=expected,
        corpus_manifest=plan.corpus_manifest,
        plan_mode="smoke",
    )
    missing_manifest = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=expected,
        corpus_manifest=None,
        plan_mode="replicated",
    )

    assert smoke["gates"]["superiority_claim_ready"] is False
    assert smoke["paired_comparisons"]["superiority_claim_ready"] is False
    assert missing_manifest["gates"]["corpus_manifest_configured"] is False
    assert missing_manifest["gates"]["superiority_claim_ready"] is False
    assert missing_manifest["paired_comparisons"]["superiority_claim_ready"] is False


def test_replicated_comparable_corpus_rejects_mixed_paired_and_native_only_cases(
    tmp_path: Path,
) -> None:
    paired_plan = _paired_itc2019_plan(tmp_path)
    paired_case = paired_plan.cases[0]
    native_only = BenchmarkCaseSpec(
        case_id="unpaired-itc2019",
        family_id="itc2019",
        instance_path=str(_instance(tmp_path, "unpaired-itc2019.xml")),
        time_limit_seconds=10.0,
        seeds=(11, 13, 17),
        repetitions=2,
        workers=1,
        cpu_affinity=0,
    )

    with pytest.raises(ValueError, match="diagnostic_unverified"):
        make_replicated_plan(
            [paired_case, native_only],
            corpus_manifest=make_corpus_manifest(
                [paired_case, native_only], corpus_id="mixed-itc2019"
            ),
        )

    paired_executions = expand_plan(make_smoke_plan([paired_case]))
    native_executions = expand_plan(make_smoke_plan([native_only]))
    executions = (*paired_executions, *native_executions)
    records = [_paired_record(execution) for execution in executions]
    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=make_corpus_manifest(
            [paired_case, native_only], corpus_id="mixed-itc2019-summary"
        ),
        plan_mode="replicated",
    )

    assert summary["gates"]["paired_comparable_corpus_coverage_complete"] is False
    assert summary["gates"]["superiority_claim_ready"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False


def test_replicated_comparable_corpus_requires_pairing_across_families(
    tmp_path: Path,
) -> None:
    paired_plan = _paired_itc2019_plan(tmp_path)
    paired_case = paired_plan.cases[0]
    native_exam = BenchmarkCaseSpec(
        case_id="unpaired-exam",
        family_id="itc2007-exam",
        instance_path=str(_instance(tmp_path, "unpaired-exam.exam")),
        time_limit_seconds=10.0,
        seeds=(11, 13, 17),
        repetitions=2,
        workers=1,
        cpu_affinity=0,
    )
    corpus = make_corpus_manifest(
        [paired_case, native_exam], corpus_id="mixed-comparison-authorities"
    )

    with pytest.raises(ValueError, match="diagnostic_unverified"):
        make_replicated_plan(
            [paired_case, native_exam],
            corpus_manifest=corpus,
        )

    executions = (
        *expand_plan(make_smoke_plan([paired_case])),
        *expand_plan(make_smoke_plan([native_exam])),
    )
    records = [_paired_record(execution) for execution in executions]
    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=corpus,
        plan_mode="replicated",
    )

    assert summary["gates"]["paired_comparable_corpus_coverage_complete"] is False
    assert summary["paired_comparisons"]["superiority_claim_ready"] is False
    assert summary["gates"]["superiority_claim_ready"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False


def test_comparison_eligibility_enforces_feasibility_completeness_and_budget(
    tmp_path: Path,
) -> None:
    plan = _paired_itc2019_plan(tmp_path)
    executions = expand_plan(plan)
    expected = tuple(execution.to_dict() for execution in executions)

    for mutation in (
        {"feasible": False},
        {"solution_complete": False},
        {
            "configured_solver_budget_compliant": False,
            "solver_deadline_overrun_seconds": 0.25,
        },
    ):
        records = [_paired_record(execution) for execution in executions]
        records[0].update(mutation)
        summary = summarize_records(
            records,
            minimum_effective_runs_per_condition=6,
            expected_executions=expected,
            corpus_manifest=plan.corpus_manifest,
            plan_mode="replicated",
        )
        assert summary["gates"]["superiority_claim_ready"] is False


def test_family_comparison_boundaries_reject_invalid_hard_state() -> None:
    from benchmarks.multifamily_harness import _comparison_row_eligible

    common = {
        "effective": True,
        "solution_complete": True,
        "official_validator_agreement": True,
        "independent_validator_status": "completed",
        "configured_solver_budget_compliant": True,
        "configured_solver_budget_compliance_basis": (
            "native_reported_overrun_and_harness_observed_solver_elapsed"
        ),
        "solver_deadline_overrun_seconds": 0.0,
        "solver_model": "planora_native",
        "configured_solver_elapsed_seconds": 1.0,
        "configured_solver_time_limit_seconds": 10.0,
    }
    ctt = {
        **common,
        "feasible": False,
        "score_authority": SCORE_AUTHORITY_OFFICIAL,
        "score_vector": [0],
    }
    exam = {
        **common,
        "feasible": True,
        "score_authority": SCORE_AUTHORITY_INDEPENDENT,
        "score_vector": [1, 0],
    }

    assert _comparison_row_eligible("itc2007-cbctt", ctt) is False
    assert _comparison_row_eligible("itc2007-exam", exam) is False


def test_pe_hard_valid_partial_solution_remains_comparable() -> None:
    from benchmarks.multifamily_harness import _comparison_row_eligible

    row = {
        "effective": True,
        "feasible": True,
        "solution_complete": False,
        "score_authority": SCORE_AUTHORITY_OFFICIAL,
        "score_vector": [2, 11],
        "score_total": None,
        "official_validator_agreement": True,
        "independent_validator_status": "completed",
        "configured_solver_budget_compliant": True,
        "configured_solver_budget_compliance_basis": (
            "native_reported_overrun_and_harness_observed_solver_elapsed"
        ),
        "solver_deadline_overrun_seconds": 0.0,
        "solver_model": "planora_native",
        "configured_solver_elapsed_seconds": 1.0,
        "configured_solver_time_limit_seconds": 10.0,
    }

    assert _comparison_row_eligible("itc2007-pe", row) is True


def test_exact_execution_identity_rejects_pair_cell_or_seed_swaps(
    tmp_path: Path,
) -> None:
    plan = _paired_itc2019_plan(tmp_path)
    executions = expand_plan(plan)
    expected = tuple(execution.to_dict() for execution in executions)

    for field, replacement in (
        ("pair_cell_id", "forged-cell"),
        ("seed", 999),
        ("solver_model", "external_command"),
    ):
        records = [_paired_record(execution) for execution in executions]
        records[0][field] = replacement
        summary = summarize_records(
            records,
            minimum_effective_runs_per_condition=6,
            expected_executions=expected,
            corpus_manifest=plan.corpus_manifest,
            plan_mode="replicated",
        )
        assert summary["gates"]["execution_identity_exact"] is False
        assert summary["gates"]["superiority_claim_ready"] is False


def test_native_only_family_never_emits_a_superiority_outcome() -> None:
    common = {
        "execution_id": "native-cell",
        "pair_cell_id": "native-cell",
        "condition_id": "native-condition",
        "family_id": "xhstt",
        "case_id": "school",
        "seed": 17,
        "repetition": 1,
        "status": "COMPLETED",
        "effective": True,
        "feasible": True,
        "score_authority": SCORE_AUTHORITY_INDEPENDENT,
        "score_total": 3,
        "score_vector": [0, 3],
        "official_validator_configured": False,
        "official_validator_agreement": None,
        "source_snapshot_match": True,
        "input_snapshot_match": True,
        "tool_snapshot_match": True,
        "official_validator_tool_snapshot_match": True,
        "configured_solver_time_scope": "configured_solver_call",
        "configured_solver_time_limit_seconds": 10.0,
    }
    planora = {**common, "solver_id": "planora", "solver_role": "planora"}
    comparator = {
        **common,
        "execution_id": "native-cell-comparator",
        "solver_id": "other",
        "solver_role": "comparator",
        "score_vector": [0, 1],
    }

    summary = summarize_records(
        [planora, comparator], minimum_effective_runs_per_condition=1
    )

    cell = summary["paired_comparisons"]["cells"]["native-cell"]
    assert cell["status"] == "native_only_no_superiority_claim"
    assert cell["outcome"] is None
    assert summary["paired_comparisons"]["superiority_claim_ready"] is False


def test_paired_ctt_plan_requires_official_external_validator(tmp_path: Path) -> None:
    comparator = BenchmarkSolverSpec(
        solver_id="cpsolver",
        model="external_command",
        role="comparator",
        command=(
            "/bin/true",
            "{instance_path}",
            "{output_path}",
            "{seed}",
            "{time_limit_seconds}",
        ),
    )
    case = BenchmarkCaseSpec(
        case_id="ctt-no-validator",
        family_id="itc2007-cbctt",
        instance_path=str(_instance(tmp_path, "ctt-no-validator.ctt")),
        time_limit_seconds=10.0,
        seeds=(11, 13, 17),
        repetitions=2,
        workers=1,
        cpu_affinity=0,
        solvers=(BenchmarkSolverSpec.planora(), comparator),
    )

    with pytest.raises(ValueError, match="diagnostic_unverified"):
        make_replicated_plan(
            [case],
            corpus_manifest=make_corpus_manifest([case], corpus_id="ctt-corpus"),
        )


def test_paired_unitime_external_comparator_is_rejected_at_plan_time(
    tmp_path: Path,
) -> None:
    comparator = BenchmarkSolverSpec(
        solver_id="other",
        model="external_command",
        role="comparator",
        command=(
            "/bin/true",
            "{instance_path}",
            "{output_path}",
            "{seed}",
            "{time_limit_seconds}",
        ),
    )
    case = BenchmarkCaseSpec(
        case_id="unitime-paired",
        family_id="unitime-native",
        instance_path=str(_instance(tmp_path, "unitime-paired.xml")),
        time_limit_seconds=10.0,
        seeds=(11, 13, 17),
        repetitions=2,
        workers=1,
        cpu_affinity=0,
        solvers=(BenchmarkSolverSpec.planora(), comparator),
    )

    with pytest.raises(ValueError, match="diagnostic_unverified"):
        make_replicated_plan(
            [case],
            corpus_manifest=make_corpus_manifest([case], corpus_id="unitime-corpus"),
        )


def test_equal_wall_claim_rejects_in_process_planora_native(tmp_path: Path) -> None:
    comparator = BenchmarkSolverSpec(
        solver_id="comparator",
        model="external_command",
        role="comparator",
        command=(
            "/bin/true",
            "{instance_path}",
            "{output_path}",
            "{seed}",
            "{time_limit_seconds}",
        ),
        timing_scope="whole_solver_process_wall",
        process_completion_grace_seconds=0.0,
    )
    case = BenchmarkCaseSpec(
        case_id="equal-wall",
        family_id="itc2019",
        instance_path=str(_instance(tmp_path, "equal-wall.xml")),
        time_limit_seconds=1.0,
        seeds=(11, 13, 17),
        repetitions=2,
        workers=1,
        cpu_affinity=0,
        solvers=(
            BenchmarkSolverSpec(
                solver_id="planora",
                model="planora_native",
                role="planora",
                timing_scope="whole_solver_process_wall",
            ),
            comparator,
        ),
    )

    with pytest.raises(ValueError, match="diagnostic_unverified"):
        make_replicated_plan(
            [case],
            corpus_manifest=make_corpus_manifest([case], corpus_id="equal-wall"),
            allow_equal_wall_time_claim=True,
        )


def test_equal_wall_summary_requires_exact_frozen_expected_context(
    tmp_path: Path,
) -> None:
    plan = _paired_itc2019_plan(tmp_path)
    executions = expand_plan(plan)
    records = [_paired_record(execution) for execution in executions]
    for record in records:
        record["solver_model"] = "external_command"
        record["configured_solver_time_scope"] = "whole_solver_process_wall"
        record.setdefault(
            "external_solver_process", {"timed_out": False, "exit_code": 0}
        )

    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=6,
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=plan.corpus_manifest,
        allow_equal_wall_time_claim=True,
        plan_mode="replicated",
    )

    assert summary["gates"]["execution_identity_exact"] is False
    assert summary["paired_comparisons"]["equal_wall_time_claim_permitted"] is False
    assert summary["gates"]["equal_wall_time_claim_permitted"] is False


def test_source_drift_invalidates_claim_fields_but_retains_observation() -> None:
    record: dict[str, object] = {
        "status": "COMPLETED",
        "effective": True,
        "feasible": True,
        "score_vector": [0, 12],
        "score_total": 12,
        "score_authority": SCORE_AUTHORITY_INDEPENDENT,
    }
    returned = invalidate_for_source_drift(
        record,
        observed_source_sha256="f" * 64,
    )
    assert returned is record
    assert record["status"] == "SOURCE_DRIFT"
    assert record["effective"] is False
    assert record["feasible"] is False
    assert record["score_vector"] is None
    assert record["score_authority"] == "invalidated"
    assert record["observed_score_before_source_drift"] == {
        "feasible": True,
        "score_vector": [0, 12],
        "score_total": 12,
        "score_authority": SCORE_AUTHORITY_INDEPENDENT,
    }


def test_replicated_evidence_gate_requires_official_validator_when_available() -> None:
    ctt = _record(
        condition="ctt",
        family="itc2007-cbctt",
        case="ctt",
        effective=True,
        feasible=True,
        authority=SCORE_AUTHORITY_INDEPENDENT,
        score=12.0,
        vector=[12],
    )
    xhstt = _record(
        condition="xhstt",
        family="xhstt",
        case="xhstt",
        effective=True,
        feasible=True,
        authority=SCORE_AUTHORITY_INDEPENDENT,
        score=3.0,
        vector=[0, 3],
    )

    summary = summarize_records(
        [ctt, xhstt],
        minimum_effective_runs_per_condition=1,
        require_official_validator_agreement=True,
    )

    assert summary["conditions"]["ctt"]["official_validator_required"] is True
    assert summary["conditions"]["ctt"]["official_validator_requirement_met"] is False
    assert summary["conditions"]["xhstt"]["official_validator_required"] is False
    assert summary["conditions"]["xhstt"]["official_validator_requirement_met"] is True
    assert summary["gates"]["official_validator_agreement"] is False
    assert summary["gates"]["benchmark_evidence_ready"] is False


def test_instance_and_execution_hashes_change_with_real_inputs(tmp_path: Path) -> None:
    first = _case(tmp_path, case_id="first")
    second = _case(tmp_path, case_id="second")
    assert sha256_file(first.instance_path) != sha256_file(second.instance_path)
    first_execution = expand_plan(make_smoke_plan([first]))[0]
    second_execution = expand_plan(make_smoke_plan([second]))[0]
    assert first.condition_id != second.condition_id
    assert first_execution.config_sha256 != second_execution.config_sha256
    frozen_payload = make_smoke_plan([first]).to_dict()
    frozen_input_hash = first.input_sha256
    frozen_condition = first.condition_id
    Path(first.instance_path).write_text("changed after planning\n", encoding="utf-8")
    assert first.input_sha256 == frozen_input_hash
    assert first.condition_id == frozen_condition
    with pytest.raises(ValueError, match="input hash no longer matches"):
        BenchmarkPlan.from_dict(frozen_payload)


def test_every_registered_family_can_be_described_as_a_plan_case(
    tmp_path: Path,
) -> None:
    family_ids = (
        "itc2007-cbctt",
        "itc2007-exam",
        "itc2007-pe",
        "cbctt-extended",
        "itc2019",
        "unitime-native",
        "xhstt",
    )
    cases = tuple(
        BenchmarkCaseSpec(
            case_id=family_id,
            family_id=family_id,
            instance_path=str(_instance(tmp_path, f"{family_id}.input")),
            time_limit_seconds=1.0,
        )
        for family_id in family_ids
    )
    plan = make_smoke_plan(cases)
    assert {execution.case.family_id for execution in expand_plan(plan)} == set(
        family_ids
    )


def test_worker_runs_a_real_tiny_native_adapter_and_hashes_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One event, one room, one feature, one student, then the five official
    # dense matrices (including 45 availability slots and precedence).
    values = [1, 1, 1, 1, 1, 1, 1, 1, *([1] * 45), 0]
    instance = tmp_path / "tiny.tim"
    instance.write_text(
        "\n".join(str(value) for value in values) + "\n", encoding="utf-8"
    )
    case = BenchmarkCaseSpec(
        case_id="tiny-pe",
        family_id="itc2007-pe",
        instance_path=str(instance),
        time_limit_seconds=1.0,
        seeds=(3,),
    )
    execution = expand_plan(make_smoke_plan([case]))[0].to_dict()
    monkeypatch.setattr(
        "benchmarks.multifamily_harness.source_snapshot",
        lambda _root, _roots: ("stable-source", {}),
    )
    request = {
        "repo_root": str(Path.cwd()),
        "run_directory": str(tmp_path / "run"),
        "plan_sha256": "a" * 64,
        "expected_source_sha256": "stable-source",
        "source_roots": ["benchmarks"],
        "execution": execution,
    }
    (tmp_path / "run").mkdir()

    record = run_worker_request(request)

    assert execution["config_sha256"] == sha256_json(execution["config"])
    assert record["status"] == "COMPLETED"
    assert record["effective"] is True
    assert record["feasible"] is True
    assert record["solution_complete"] is True
    assert record["score_authority"] == SCORE_AUTHORITY_INDEPENDENT
    assert record["score_vector"][0] == 0
    assert record["independent_validator_status"] == "completed"
    assert record["official_validator_status"] == "not_configured"
    assert record["output_sha256"] == sha256_file(record["output_path"])
    assert record["source_snapshot_match"] is True
    assert record["worker_wall_time_seconds"] >= record["solve_wall_time_seconds"]


def test_native_worker_rejects_zero_reported_overrun_when_observed_return_is_late(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from benchmarks.multifamily_harness import _comparison_row_eligible

    instance = _instance(tmp_path, "late-native-itc2019.xml")
    case = BenchmarkCaseSpec(
        case_id="late-native",
        family_id="itc2019",
        instance_path=str(instance),
        time_limit_seconds=0.005,
        seeds=(17,),
    )
    execution = expand_plan(make_smoke_plan([case]))[0].to_dict()
    monkeypatch.setattr(
        "benchmarks.multifamily_harness.source_snapshot",
        lambda _root, _roots: ("stable-source", {}),
    )

    def late_native(
        record: dict[str, object], **_kwargs: object
    ) -> tuple[object, dict[str, object], float]:
        started = time.perf_counter()
        time.sleep(0.02)
        elapsed = time.perf_counter() - started
        record.update(
            {
                "status": "FEASIBLE",
                "feasible": True,
                "solution_complete": True,
                "score_vector": [3],
                "score_total": 3,
                "score_components": {"total": 3},
                "solver_deadline_overrun_seconds": 0.0,
                "independent_validator_status": "completed",
                "independent_validation": {"errors": [], "feasible": True},
            }
        )
        return object(), {"errors": [], "feasible": True}, elapsed

    monkeypatch.setattr("benchmarks.multifamily_harness._execute_native", late_native)
    run_directory = tmp_path / "late-native-run"
    run_directory.mkdir()
    record = run_worker_request(
        {
            "repo_root": str(Path.cwd()),
            "run_directory": str(run_directory),
            "plan_sha256": "e" * 64,
            "expected_source_sha256": "stable-source",
            "source_roots": ["benchmarks"],
            "execution": execution,
        }
    )

    assert record["solver_deadline_overrun_seconds"] == 0.0
    assert record["configured_solver_elapsed_seconds"] > 0.005
    assert record["configured_solver_budget_compliant"] is False
    assert _comparison_row_eligible("itc2019", record) is False


def test_external_solver_gets_separate_process_completion_headroom(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = [1, 1, 1, 1, 1, 1, 1, 1, *([1] * 45), 0]
    instance = tmp_path / "tiny-external.tim"
    instance.write_text(
        "\n".join(str(value) for value in values) + "\n", encoding="utf-8"
    )
    script = tmp_path / "post-output.py"
    script.write_text(
        """from pathlib import Path
import sys
import time
Path(sys.argv[2]).write_text("0 0\\n", encoding="utf-8")
time.sleep(0.12)
""",
        encoding="utf-8",
    )
    comparator = BenchmarkSolverSpec(
        solver_id="slow-finalizer",
        model="external_command",
        role="comparator",
        command=(
            sys.executable,
            str(script),
            "{instance_path}",
            "{output_path}",
            "{seed}",
            "{time_limit_seconds}",
        ),
        process_completion_grace_seconds=0.5,
    )
    case = BenchmarkCaseSpec(
        case_id="tiny-external-pe",
        family_id="itc2007-pe",
        instance_path=str(instance),
        time_limit_seconds=0.05,
        seeds=(3,),
        solvers=(BenchmarkSolverSpec.planora(), comparator),
    )
    execution = next(
        row
        for row in expand_plan(make_smoke_plan([case]))
        if row.solver.role == "comparator"
    ).to_dict()
    monkeypatch.setattr(
        "benchmarks.multifamily_harness.source_snapshot",
        lambda _root, _roots: ("stable-source", {}),
    )
    run_directory = tmp_path / "external-run"
    run_directory.mkdir()
    request = {
        "repo_root": str(Path.cwd()),
        "run_directory": str(run_directory),
        "plan_sha256": "d" * 64,
        "expected_source_sha256": "stable-source",
        "source_roots": ["benchmarks"],
        "execution": execution,
    }

    record = run_worker_request(request)

    assert record["status"] == "COMPLETED"
    assert record["effective"] is True
    assert record["configured_solver_time_limit_seconds"] == pytest.approx(0.05)
    assert record["configured_search_seconds"] == pytest.approx(0.05)
    assert record["external_process_timeout_seconds"] == pytest.approx(0.55)
    assert record["external_process_wall_time_seconds"] >= 0.1
    assert record["configured_solver_elapsed_seconds"] is None
    assert record["configured_solver_time_scope"] == "tool_configured_search_budget"
    assert record["external_solver_process"]["timed_out"] is False


def test_itc2019_worker_uses_auto_formulation_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = tmp_path / "tiny-itc2019.xml"
    instance.write_text(
        """<problem name="tiny" nrDays="1" slotsPerDay="5" nrWeeks="1">
        <optimization time="1" room="1" distribution="1" student="1"/>
        <rooms><room id="R" capacity="10"/></rooms>
        <courses><course id="C"><config id="G"><subpart id="S">
          <class id="A" limit="10"><room id="R"/><time days="1" start="0"
            length="1" weeks="1"/></class>
        </subpart></config></course></courses>
        </problem>""",
        encoding="utf-8",
    )
    case = BenchmarkCaseSpec(
        case_id="tiny-itc2019",
        family_id="itc2019",
        instance_path=str(instance),
        time_limit_seconds=1.0,
        seeds=(17,),
    )
    execution = expand_plan(make_smoke_plan([case]))[0].to_dict()
    monkeypatch.setattr(
        "benchmarks.multifamily_harness.source_snapshot",
        lambda _root, _roots: ("stable-source", {}),
    )
    request = {
        "repo_root": str(Path.cwd()),
        "run_directory": str(tmp_path / "run-itc2019"),
        "plan_sha256": "c" * 64,
        "expected_source_sha256": "stable-source",
        "source_roots": ["benchmarks"],
        "execution": execution,
    }
    (tmp_path / "run-itc2019").mkdir()

    record = run_worker_request(request)

    assert record["status"] == "COMPLETED"
    assert record["effective"] is True
    assert record["feasible"] is True
    assert record["solver_result"]["requested_formulation"] == "auto"
    assert record["solver_result"]["effective_formulation"] == "cartesian"
    assert record["solver_result"]["raw_cartesian_domain_values"] == 1
    assert record["solver_result"]["auto_cartesian_domain_threshold"] == 50_000


def test_pe_worker_keeps_hard_valid_partial_solution_comparable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The sole student makes the event too large for the zero-capacity room.
    # Official PE semantics score the resulting unplaced event in the primary
    # distance component; the empty placement still has no hard violations.
    values = [1, 1, 1, 1, 0, 1, 1, 1, *([1] * 45), 0]
    instance = tmp_path / "partial.tim"
    instance.write_text(
        "\n".join(str(value) for value in values) + "\n", encoding="utf-8"
    )
    case = BenchmarkCaseSpec(
        case_id="partial-pe",
        family_id="itc2007-pe",
        instance_path=str(instance),
        time_limit_seconds=0.2,
        seeds=(3,),
    )
    execution = expand_plan(make_smoke_plan([case]))[0].to_dict()
    monkeypatch.setattr(
        "benchmarks.multifamily_harness.source_snapshot",
        lambda _root, _roots: ("stable-source", {}),
    )
    request = {
        "repo_root": str(Path.cwd()),
        "run_directory": str(tmp_path / "run-partial"),
        "plan_sha256": "b" * 64,
        "expected_source_sha256": "stable-source",
        "source_roots": ["benchmarks"],
        "execution": execution,
    }
    (tmp_path / "run-partial").mkdir()

    record = run_worker_request(request)

    assert record["status"] == "COMPLETED"
    assert record["effective"] is True
    assert record["feasible"] is True
    assert record["solution_complete"] is False
    assert record["score_vector"][0] == 1
    assert record["score_total"] is None
