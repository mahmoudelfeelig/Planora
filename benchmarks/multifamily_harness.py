"""Source-frozen native and diagnostic external benchmark harness.

The harness deliberately keeps orchestration separate from solver modules.  A
plan is expanded into one fresh Python process per execution, and every result
is invalidated if the source snapshot changes before, during, or after that
execution.  Scores are aggregated only within a benchmark family and retain an
explicit authority label; a locally implemented standard score is never
silently promoted to an official external score. External commands are useful
for smoke diagnostics, but their arbitrary dependency-loading grammars are not
hermetically closed here and therefore cannot enter replicated claim evidence.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, is_dataclass
import hashlib
import importlib.metadata
import inspect
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import stat
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence
import zipfile

try:
    import resource
except ImportError:  # pragma: no cover - unavailable on Windows
    resource = None  # type: ignore[assignment]

from benchmarks.corpus import (
    BENCHMARK_FAMILIES,
    get_benchmark_family,
    resolve_benchmark_entrypoint,
)


SCHEMA_VERSION = "planora.multifamily-benchmark.v2"
PLAN_MODES = frozenset({"smoke", "replicated"})
SOLVER_MODELS = frozenset({"planora_native", "external_command"})
SOLVER_ROLES = frozenset({"planora", "comparator"})
DEFAULT_SOURCE_ROOTS = ("benchmarks", "core", "services", "utils", "product")
SCORE_AUTHORITY_OFFICIAL = "official_external"
SCORE_AUTHORITY_INDEPENDENT = "independent_standardized"
SCORE_AUTHORITY_NATIVE = "native_only"
_BUDGET_TOLERANCE_SECONDS = 1e-6
_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SOLVER_ID = _CASE_ID
_OPTION_GROUPS = frozenset({"parser", "solver", "validator", "writer", "ctt"})
_COMMAND_PLACEHOLDERS = frozenset(
    {
        "{instance_path}",
        "{output_path}",
        "{seed}",
        "{time_limit_seconds}",
        "{workers}",
        "{run_directory}",
    }
)
_SCRIPT_SUFFIXES = frozenset(
    {
        ".py",
        ".pyw",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".rb",
        ".pl",
        ".lua",
        ".sh",
        ".jar",
        ".class",
        ".java",
        ".kt",
        ".scala",
        ".exe",
        ".bat",
        ".cmd",
        ".ps1",
        ".so",
        ".dll",
        ".dylib",
        ".zip",
        ".whl",
    }
)
_TOOL_CONFIG_SUFFIXES = frozenset({".cfg", ".conf", ".properties"})
_RUNTIME_ARTIFACT_SUFFIXES = frozenset(
    {
        ".onnx",
        ".pt",
        ".pth",
        ".pb",
        ".tflite",
        ".pkl",
        ".joblib",
        ".safetensors",
        ".gguf",
        ".model",
        ".wasm",
        ".dylib",
        ".dll",
        ".so",
    }
)
_CLASSPATH_OPTIONS = frozenset({"-cp", "-classpath", "--class-path"})
_JAVA_SAFE_SCALAR_PROPERTIES = frozenset(
    {
        "General.Seed",
        "Parallel.NrSolvers",
        "Termination.TimeOut",
    }
)
_JAVA_SAFE_XX_ASSIGNMENTS = frozenset({"ActiveProcessorCount"})
_JAVA_SAFE_X_RESOURCE_OPTION = re.compile(r"^-X(?:ms|mx|ss)[1-9][0-9]*(?:[kKmMgGtT])?$")
_JAVA_MAIN_CLASS = re.compile(
    r"^[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)+$"
)
_PATH_ASSIGNMENT_OPTION_WORDS = frozenset(
    {
        "artifact",
        "checkpoint",
        "classpath",
        "config",
        "executable",
        "file",
        "jar",
        "lib",
        "library",
        "model",
        "path",
        "plugin",
        "script",
        "weights",
    }
)
_SHELL_EXECUTABLE_NAMES = frozenset(
    {
        "bash",
        "sh",
        "dash",
        "ksh",
        "csh",
        "tcsh",
        "zsh",
        "fish",
        "cmd",
        "cmd.exe",
        "powershell",
        "pwsh",
    }
)
_LAUNCHER_EXECUTABLE_NAMES = frozenset(
    {
        "env",
        "env.exe",
        "nice",
        "nohup",
        "timeout",
        "taskset",
        "chrt",
        "ionice",
        "stdbuf",
        "xargs",
    }
)
# These lanes define shared score authority when a future hermetic comparator
# profile becomes available. Extended CB-CTT, XHSTT, and UniTime
# remain interoperability/native evidence even when a local published-semantics
# scorer exists; the harness therefore refuses to turn those scores into a
# superiority outcome.
_COMPARISON_AUTHORITY = {
    "itc2007-cbctt": SCORE_AUTHORITY_OFFICIAL,
    "itc2007-pe": SCORE_AUTHORITY_OFFICIAL,
    "itc2007-exam": SCORE_AUTHORITY_INDEPENDENT,
    "itc2019": SCORE_AUTHORITY_INDEPENDENT,
}
_CHILD_ENVIRONMENT_PASSTHROUGH = (
    "SYSTEMROOT",
    "WINDIR",
)


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_directory(
    path: Path,
) -> tuple[str, int]:
    """Hash every regular file in a directory without following mutable links."""

    digest = hashlib.sha256()
    file_count = 0
    for candidate in sorted(path.rglob("*")):
        if candidate.is_symlink():
            raise ValueError(
                f"tool artifact cannot contain a symbolic link: {candidate}"
            )
        mode = candidate.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError(
                f"tool artifact cannot contain a special file: {candidate}"
            )
        if candidate.suffix.lower() == ".jar":
            _reject_jar_manifest_external_loading(candidate)
        relative = candidate.relative_to(path).as_posix().encode("utf-8")
        file_sha256 = sha256_file(candidate)
        file_digest = bytes.fromhex(file_sha256)
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(file_digest)
        file_count += 1
    return digest.hexdigest(), file_count


def _resolve_artifact_path(
    raw: str,
    *,
    base_directory: Path,
    executable: bool = False,
) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        local = (base_directory / candidate).resolve()
        if local.exists():
            candidate = local
        elif executable and len(candidate.parts) == 1:
            resolved = shutil.which(raw)
            if resolved is None:
                raise ValueError(f"tool executable cannot be resolved: {raw!r}")
            candidate = Path(resolved).resolve()
        else:
            candidate = local
    else:
        candidate = candidate.resolve()
    if not candidate.exists():
        raise ValueError(f"tool artifact cannot be resolved: {raw!r}")
    if candidate.is_symlink():
        raise ValueError(f"tool artifact cannot be a symbolic link: {candidate}")
    if executable and not candidate.is_file():
        raise ValueError(f"tool executable is not a file: {candidate}")
    return candidate


def _artifact_record(path: Path, *, kind: str) -> dict[str, Any]:
    if path.is_file() and path.suffix.lower() == ".jar":
        _reject_jar_manifest_external_loading(path)
    if path.is_file():
        digest = sha256_file(path)
        file_count = 1
        artifact_type = "file"
    elif path.is_dir():
        digest, file_count = _sha256_directory(path)
        artifact_type = "directory"
    else:  # pragma: no cover - guarded by _resolve_artifact_path
        raise ValueError(f"unsupported tool artifact: {path}")
    return {
        "path": str(path.resolve()),
        "kind": kind,
        "artifact_type": artifact_type,
        "sha256": digest,
        "file_count": int(file_count),
    }


def _python_launcher_snapshot(
    raw_command: str | Path,
    *,
    base_directory: Path,
) -> tuple[str, tuple[dict[str, Any], ...], str]:
    """Preserve a venv launch path while freezing its binary and metadata."""

    raw = Path(raw_command).expanduser()
    if raw.is_absolute():
        launcher = Path(os.path.abspath(os.fspath(raw)))
    elif len(raw.parts) == 1:
        located = shutil.which(os.fspath(raw))
        if located is None:
            raise ValueError(f"Python executable cannot be resolved: {raw_command!r}")
        launcher = Path(os.path.abspath(located))
    else:
        launcher = Path(os.path.abspath(base_directory / raw))
    if not launcher.is_file() or not os.access(launcher, os.X_OK):
        raise ValueError(f"Python executable is unavailable: {launcher}")
    target = launcher.resolve(strict=True)
    records = [_artifact_record(target, kind="python_executable")]
    venv_config = launcher.parent.parent / "pyvenv.cfg"
    if venv_config.is_file():
        records.append(_artifact_record(venv_config, kind="python_environment"))
    manifest = tuple(sorted(records, key=lambda row: (row["kind"], row["path"])))
    return str(launcher), manifest, sha256_json(list(manifest))


def _reject_jar_manifest_external_loading(path: Path) -> None:
    """Reject JAR manifests that can load unenumerated runtime dependencies."""

    try:
        if not zipfile.is_zipfile(path):
            raise ValueError(f"tool JAR is not a valid ZIP archive: {path}")
        with zipfile.ZipFile(path) as archive:
            try:
                raw_manifest = archive.read("META-INF/MANIFEST.MF")
            except KeyError:
                return
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"tool JAR cannot be inspected: {path}") from exc
    try:
        text = raw_manifest.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"tool JAR manifest is not UTF-8: {path}") from exc
    logical_lines: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.startswith(" ") and logical_lines:
            logical_lines[-1] += line[1:]
        else:
            logical_lines.append(line)
    external_loading = {"class-path", "boot-class-path"}
    for line in logical_lines:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip().lower() in external_loading and value.strip():
            raise ValueError(
                f"tool JAR manifest declares external loading via {key.strip()!r}; "
                "enumerate every runtime JAR explicitly"
            )


def _looks_like_path_value(raw: str) -> bool:
    """Recognize unambiguous path syntax without treating ordinary scalars as files."""

    if not raw:
        return False
    if Path(raw).expanduser().is_absolute():
        return True
    if re.match(r"^[A-Za-z]:[\\/]", raw):
        return True
    return raw.startswith(("~/", "~\\", "./", ".\\", "../", "..\\")) or any(
        separator in raw for separator in ("/", "\\")
    )


def _assignment_option_declares_path(raw_prefix: str) -> bool:
    words = tuple(
        word for word in re.split(r"[^a-z0-9]+", raw_prefix.lstrip("-").lower()) if word
    )
    return bool(words and words[-1] in _PATH_ASSIGNMENT_OPTION_WORDS)


def _safe_java_scalar_property(token: str) -> bool:
    if not token.startswith("-D") or "=" not in token[2:]:
        return False
    name, value = token[2:].split("=", 1)
    if name not in _JAVA_SAFE_SCALAR_PROPERTIES or not value:
        return False
    if value in {"{seed}", "{time_limit_seconds}", "{workers}"}:
        return True
    return bool(re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value))


def _safe_java_xx_option(token: str) -> bool:
    if not token.startswith("-XX:") or "=" not in token[4:]:
        return False
    name, value = token[4:].split("=", 1)
    return bool(
        name in _JAVA_SAFE_XX_ASSIGNMENTS and re.fullmatch(r"[1-9][0-9]*", value)
    )


def _validate_java_argv_policy(tokens: Sequence[str]) -> None:
    """Allow only the frozen CPSolver Java launcher surface.

    Filesystem and executable-loading launcher options are intentionally denied,
    even with absolute paths. Runtime JARs must be explicit classpath or ``-jar``
    entries, and the remaining arguments may only be a stable main class,
    benchmark placeholders, or scalar application arguments.
    """

    classpath_seen = False
    launch_target_seen = False
    index = 0
    while index < len(tokens):
        token = str(tokens[index])
        if token.startswith("@"):
            raise ValueError(
                "Java @argfiles are unsupported for claim-grade runs; use direct "
                "explicit classpath or JAR argv tokens"
            )
        if token in _CLASSPATH_OPTIONS:
            if classpath_seen or launch_target_seen or index + 1 >= len(tokens):
                raise ValueError("unsupported Java launcher option ordering")
            classpath_seen = True
            index += 2
            continue
        if any(token.startswith(option + "=") for option in _CLASSPATH_OPTIONS):
            if classpath_seen or launch_target_seen:
                raise ValueError("unsupported Java launcher option ordering")
            classpath_seen = True
            index += 1
            continue
        if token == "-jar":
            if classpath_seen or launch_target_seen or index + 1 >= len(tokens):
                raise ValueError("unsupported Java launcher option ordering")
            launch_target_seen = True
            index += 2
            continue
        if token.startswith("-"):
            if (
                _JAVA_SAFE_X_RESOURCE_OPTION.fullmatch(token)
                or _safe_java_xx_option(token)
                or _safe_java_scalar_property(token)
            ) and not launch_target_seen:
                index += 1
                continue
            raise ValueError(f"unsupported Java launcher option: {token!r}")
        if not launch_target_seen:
            if not _JAVA_MAIN_CLASS.fullmatch(token):
                raise ValueError(
                    "Java command requires one explicit package-qualified main class"
                )
            launch_target_seen = True
            index += 1
            continue
        if token in _COMMAND_PLACEHOLDERS:
            index += 1
            continue
        if "{" in token or "}" in token:
            raise ValueError(f"unsupported Java application argument: {token!r}")
        if (
            Path(token).is_absolute()
            or re.match(r"^[A-Za-z]:[\\/]", token)
            or re.fullmatch(r"[A-Za-z0-9._:-]+", token)
        ):
            index += 1
            continue
        raise ValueError(f"unsupported Java application argument: {token!r}")
    if not launch_target_seen:
        raise ValueError("Java command requires an explicit main class or JAR")


def snapshot_command_tools(
    command: Sequence[str],
    *,
    base_directory: str | Path | None = None,
    declared_artifacts: Sequence[str] = (),
) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...], str]:
    """Resolve and hash directly declared artifacts in a diagnostic command.

    Shell snippets, classpath wildcards, missing scripts, missing JARs, missing
    response files, and unresolved path-valued assignments are rejected. This
    does not claim dependency closure for arbitrary interpreter/native/config
    grammars; every external command remains ``diagnostic_unverified``.
    """

    raw_command = tuple(str(part) for part in command)
    if not raw_command or any(not part for part in raw_command):
        raise ValueError("external command must contain non-empty argv tokens")
    if any(token.startswith("@") for token in raw_command):
        raise ValueError(
            "command @response files are unsupported for claim-grade runs; "
            "enumerate every argument and runtime artifact explicitly"
        )
    raw_executable_name = Path(raw_command[0]).name.lower()
    if raw_executable_name in _SHELL_EXECUTABLE_NAMES:
        raise ValueError(
            "shell launcher commands are unresolved benchmark logic; invoke a "
            "frozen executable or script directly"
        )
    if raw_executable_name in _LAUNCHER_EXECUTABLE_NAMES:
        raise ValueError(
            "launcher commands are unresolved benchmark logic; invoke the frozen "
            "tool directly"
        )
    base = Path(base_directory or Path.cwd()).resolve()
    executable = _resolve_artifact_path(
        raw_command[0], base_directory=base, executable=True
    )
    normalized = list(raw_command)
    normalized[0] = str(executable)
    artifacts: dict[str, dict[str, Any]] = {
        str(executable): _artifact_record(executable, kind="executable")
    }
    executable_name = executable.name.lower()
    if executable_name in _SHELL_EXECUTABLE_NAMES:
        raise ValueError(
            "shell launcher commands are unresolved benchmark logic; invoke a "
            "frozen executable or script directly"
        )
    if executable_name in _LAUNCHER_EXECUTABLE_NAMES:
        raise ValueError(
            "launcher commands are unresolved benchmark logic; invoke the frozen "
            "tool directly"
        )
    interpreter = bool(
        executable_name.startswith("python")
        or executable_name in {"node", "node.exe", "ruby", "perl"}
    )
    java = executable_name in {"java", "java.exe"}
    if java:
        _validate_java_argv_policy(normalized[1:])
    logic_payload_found = False

    index = 1
    while index < len(normalized):
        token = normalized[index]
        if token in _COMMAND_PLACEHOLDERS or "{" in token or "}" in token:
            unknown = {
                match.group(0)
                for match in re.finditer(r"\{[^{}]+\}", token)
                if match.group(0) not in _COMMAND_PLACEHOLDERS
            }
            if unknown:
                raise ValueError(
                    f"unknown external-command placeholders: {sorted(unknown)}"
                )
            scrubbed = token
            for placeholder in _COMMAND_PLACEHOLDERS:
                scrubbed = scrubbed.replace(placeholder, "")
            if "{" in scrubbed or "}" in scrubbed:
                raise ValueError(
                    f"malformed external-command placeholder token: {token!r}"
                )
            templated_value = token.split("=", 1)[-1]
            if token not in _COMMAND_PLACEHOLDERS and templated_value not in (
                _COMMAND_PLACEHOLDERS
            ):
                raise ValueError(
                    "templated behavior or path selection is unresolved benchmark "
                    "logic; placeholder values must occupy a complete argv value"
                )
            templated_suffix = Path(templated_value).suffix.lower()
            if templated_suffix in (
                _SCRIPT_SUFFIXES | _TOOL_CONFIG_SUFFIXES | _RUNTIME_ARTIFACT_SUFFIXES
            ):
                raise ValueError(
                    "templated behavior artifacts are unresolved benchmark logic; "
                    "use one static hashed path per solver specification"
                )
            index += 1
            continue
        inline_classpath_option = next(
            (option for option in _CLASSPATH_OPTIONS if token.startswith(option + "=")),
            None,
        )
        if inline_classpath_option is not None:
            raw_classpath = token.split("=", 1)[1]
            if "*" in raw_classpath or "?" in raw_classpath:
                raise ValueError("classpath wildcards are unresolved benchmark logic")
            pieces = raw_classpath.split(os.pathsep)
            if not pieces or any(not piece for piece in pieces):
                raise ValueError("classpath must contain explicit non-empty entries")
            resolved_pieces = []
            for piece in pieces:
                path = _resolve_artifact_path(piece, base_directory=base)
                resolved_pieces.append(str(path))
                artifacts[str(path)] = _artifact_record(path, kind="classpath")
            normalized[index] = (
                inline_classpath_option + "=" + os.pathsep.join(resolved_pieces)
            )
            logic_payload_found = True
            index += 1
            continue
        if token in _CLASSPATH_OPTIONS:
            if index + 1 >= len(normalized):
                raise ValueError(f"{token} requires an explicit classpath")
            raw_classpath = normalized[index + 1]
            if "*" in raw_classpath or "?" in raw_classpath:
                raise ValueError("classpath wildcards are unresolved benchmark logic")
            pieces = raw_classpath.split(os.pathsep)
            if not pieces or any(not piece for piece in pieces):
                raise ValueError("classpath must contain explicit non-empty entries")
            resolved_pieces: list[str] = []
            for piece in pieces:
                path = _resolve_artifact_path(piece, base_directory=base)
                resolved_pieces.append(str(path))
                artifacts[str(path)] = _artifact_record(path, kind="classpath")
            logic_payload_found = True
            normalized[index + 1] = os.pathsep.join(resolved_pieces)
            index += 2
            continue
        if token == "-jar":
            if index + 1 >= len(normalized):
                raise ValueError("-jar requires an explicit JAR path")
            jar = _resolve_artifact_path(normalized[index + 1], base_directory=base)
            if not jar.is_file() or jar.suffix.lower() != ".jar":
                raise ValueError(f"-jar target is not a JAR file: {jar}")
            normalized[index + 1] = str(jar)
            artifacts[str(jar)] = _artifact_record(jar, kind="jar")
            logic_payload_found = True
            index += 2
            continue
        if "=" not in token and _assignment_option_declares_path(token):
            if index + 1 >= len(normalized):
                raise ValueError(f"path-valued option {token!r} requires a value")
            raw_value = normalized[index + 1]
            if raw_value in {
                "{instance_path}",
                "{output_path}",
                "{run_directory}",
            }:
                index += 1
                continue
            if "{" in raw_value or "}" in raw_value:
                raise ValueError(
                    "templated behavior artifacts are unresolved benchmark logic; "
                    "use one static hashed path per solver specification"
                )
            path = _resolve_artifact_path(raw_value, base_directory=base)
            normalized[index + 1] = str(path)
            artifacts[str(path)] = _artifact_record(path, kind="command_input")
            logic_payload_found = True
            index += 2
            continue
        artifact_token = token
        assignment_prefix: str | None = None
        assignment_declares_path = False
        if "=" in token:
            prefix, candidate_value = token.split("=", 1)
            candidate_path = Path(candidate_value).expanduser()
            candidate_exists = (
                candidate_path.exists()
                if candidate_path.is_absolute()
                else (base / candidate_path).exists()
            )
            assignment_declares_path = bool(
                candidate_exists
                or _looks_like_path_value(candidate_value)
                or _assignment_option_declares_path(prefix)
                or Path(candidate_value).suffix.lower()
                in (
                    _SCRIPT_SUFFIXES
                    | _TOOL_CONFIG_SUFFIXES
                    | _RUNTIME_ARTIFACT_SUFFIXES
                )
            )
            if assignment_declares_path:
                assignment_prefix = prefix + "="
                artifact_token = candidate_value
        suffix = Path(artifact_token).suffix.lower()
        if suffix in (
            _SCRIPT_SUFFIXES | _TOOL_CONFIG_SUFFIXES | _RUNTIME_ARTIFACT_SUFFIXES
        ):
            path = _resolve_artifact_path(artifact_token, base_directory=base)
            normalized[index] = (assignment_prefix or "") + str(path)
            artifacts[str(path)] = _artifact_record(path, kind="command_input")
            logic_payload_found = True
        elif assignment_declares_path or (
            Path(artifact_token).is_absolute() or (base / Path(artifact_token)).exists()
        ):
            path = _resolve_artifact_path(artifact_token, base_directory=base)
            normalized[index] = (assignment_prefix or "") + str(path)
            artifacts[str(path)] = _artifact_record(path, kind="auxiliary_input")
            logic_payload_found = True
        index += 1

    for raw_artifact in declared_artifacts:
        if not str(raw_artifact):
            raise ValueError("declared tool artifact paths cannot be empty")
        artifact = _resolve_artifact_path(str(raw_artifact), base_directory=base)
        artifacts[str(artifact)] = _artifact_record(artifact, kind="declared_artifact")
        logic_payload_found = True

    if interpreter and "-m" in normalized[1:]:
        raise ValueError(
            "interpreter module execution is unresolved logic; use an explicit "
            "script path or a standalone executable"
        )
    if interpreter and not logic_payload_found:
        raise ValueError(
            "interpreter command requires an explicit, hashable script input"
        )
    if java and not logic_payload_found:
        raise ValueError(
            "Java command requires an explicit JAR or non-wildcard classpath"
        )

    manifest = tuple(artifacts[path] for path in sorted(artifacts))
    snapshot_sha256 = sha256_json({"command": normalized, "artifacts": list(manifest)})
    return tuple(normalized), manifest, snapshot_sha256


def tool_snapshot_matches(manifest: Sequence[Mapping[str, Any]]) -> bool:
    """Return false when any directly manifested tool artifact drifts."""

    try:
        for expected in manifest:
            path = Path(str(expected["path"]))
            observed = _artifact_record(path, kind=str(expected["kind"]))
            if observed != dict(expected):
                return False
    except (OSError, ValueError, KeyError):
        return False
    return True


def _observed_file_sha256(path: str | Path) -> str | None:
    candidate = Path(path)
    return sha256_file(candidate) if candidate.is_file() else None


def source_snapshot(
    repo_root: str | Path,
    source_roots: Sequence[str] = DEFAULT_SOURCE_ROOTS,
) -> tuple[str, dict[str, str]]:
    """Hash all Python source files in the declared benchmark trust boundary."""

    root = Path(repo_root).resolve()
    files: dict[str, str] = {}
    for source_name in source_roots:
        source_path = (root / source_name).resolve()
        if root != source_path and root not in source_path.parents:
            raise ValueError(f"source root escapes repository: {source_name!r}")
        if not source_path.is_dir():
            raise FileNotFoundError(f"source root does not exist: {source_path}")
        for path in sorted(source_path.rglob("*.py")):
            if path.is_file():
                files[path.relative_to(root).as_posix()] = sha256_file(path)
    digest = hashlib.sha256()
    for relative, file_digest in sorted(files.items()):
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(bytes.fromhex(file_digest))
    return digest.hexdigest(), files


def _json_roundtrip(value: Any, *, label: str) -> Any:
    try:
        return json.loads(_canonical_json_bytes(value).decode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be finite JSON data") from exc


def _normalize_options(raw: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    normalized = _json_roundtrip(dict(raw or {}), label="case options")
    unknown = sorted(set(normalized) - _OPTION_GROUPS)
    if unknown:
        raise ValueError(f"unknown option groups: {unknown}")
    output: dict[str, dict[str, Any]] = {}
    for group, values in normalized.items():
        if not isinstance(values, dict):
            raise ValueError(f"option group {group!r} must be an object")
        output[str(group)] = dict(values)
    return output


@dataclass(frozen=True)
class BenchmarkSolverSpec:
    """One explicitly identified solver implementation in a benchmark lane."""

    solver_id: str
    model: str
    role: str
    command: tuple[str, ...] = ()
    declared_tool_artifacts: tuple[str, ...] = ()
    timing_scope: str | None = None
    process_completion_grace_seconds: float | None = None
    artifact_base_directory: Any = field(default=None, repr=False, compare=False)
    tool_manifest: tuple[dict[str, Any], ...] = field(init=False)
    tool_snapshot_sha256: str = field(init=False)
    command_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if not _SOLVER_ID.fullmatch(str(self.solver_id)):
            raise ValueError(
                "solver_id must use only alphanumerics, dot, underscore, or hyphen"
            )
        if self.model not in SOLVER_MODELS:
            raise ValueError(f"solver model must be one of {sorted(SOLVER_MODELS)}")
        if self.role not in SOLVER_ROLES:
            raise ValueError(f"solver role must be one of {sorted(SOLVER_ROLES)}")
        timing_scope = self.timing_scope
        if self.model == "planora_native":
            if self.command or self.declared_tool_artifacts:
                raise ValueError(
                    "planora_native solver cannot define an external command"
                )
            if self.role != "planora":
                raise ValueError("planora_native solver must have role 'planora'")
            command: tuple[str, ...] = ()
            manifest: tuple[dict[str, Any], ...] = ()
            tool_hash = sha256_json({"model": self.model, "source_frozen": True})
            timing_scope = timing_scope or "configured_solver_call"
            completion_grace = float(self.process_completion_grace_seconds or 0.0)
            if completion_grace != 0.0:
                raise ValueError(
                    "planora_native solver cannot define process completion grace"
                )
        else:
            if self.role != "comparator":
                raise ValueError("external_command solver must have role 'comparator'")
            required_placeholders = {
                "{instance_path}",
                "{output_path}",
                "{seed}",
                "{time_limit_seconds}",
            }
            command_text = "\0".join(str(part) for part in self.command)
            missing_placeholders = sorted(
                placeholder
                for placeholder in required_placeholders
                if placeholder not in command_text
            )
            if missing_placeholders:
                raise ValueError(
                    "external comparator command must expose deterministic input, "
                    f"output, seed, and configured-time placeholders; missing {missing_placeholders}"
                )
            command, manifest, tool_hash = snapshot_command_tools(
                self.command,
                base_directory=self.artifact_base_directory,
                declared_artifacts=self.declared_tool_artifacts,
            )
            timing_scope = timing_scope or "tool_configured_search_budget"
            completion_grace = float(
                30.0
                if self.process_completion_grace_seconds is None
                else self.process_completion_grace_seconds
            )
            if not math.isfinite(completion_grace) or completion_grace < 0:
                raise ValueError(
                    "process completion grace must be finite and non-negative"
                )
        if not timing_scope or not _CASE_ID.fullmatch(str(timing_scope)):
            raise ValueError("timing_scope must be a stable identifier")
        object.__setattr__(self, "command", command)
        object.__setattr__(
            self,
            "declared_tool_artifacts",
            tuple(str(value) for value in self.declared_tool_artifacts),
        )
        object.__setattr__(self, "timing_scope", str(timing_scope))
        object.__setattr__(self, "process_completion_grace_seconds", completion_grace)
        object.__setattr__(self, "tool_manifest", manifest)
        object.__setattr__(self, "tool_snapshot_sha256", tool_hash)
        object.__setattr__(self, "command_sha256", sha256_json(list(command)))

    @classmethod
    def planora(cls, solver_id: str = "planora") -> "BenchmarkSolverSpec":
        return cls(solver_id=solver_id, model="planora_native", role="planora")

    @property
    def evidence_classification(self) -> str:
        return (
            "source_frozen_native"
            if self.model == "planora_native"
            else "diagnostic_unverified"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "solver_id": self.solver_id,
            "model": self.model,
            "role": self.role,
            "evidence_classification": self.evidence_classification,
            "command": list(self.command),
            "declared_tool_artifacts": list(self.declared_tool_artifacts),
            "timing_scope": self.timing_scope,
            "process_completion_grace_seconds": self.process_completion_grace_seconds,
            "command_sha256": self.command_sha256,
            "tool_manifest": [dict(row) for row in self.tool_manifest],
            "tool_snapshot_sha256": self.tool_snapshot_sha256,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        base_directory: str | Path | None = None,
    ) -> "BenchmarkSolverSpec":
        raw = dict(payload)
        allowed = {
            "solver_id",
            "model",
            "role",
            "evidence_classification",
            "command",
            "declared_tool_artifacts",
            "timing_scope",
            "process_completion_grace_seconds",
            "command_sha256",
            "tool_manifest",
            "tool_snapshot_sha256",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ValueError(f"unknown benchmark solver fields: {unknown}")
        solver = cls(
            solver_id=str(raw["solver_id"]),
            model=str(raw["model"]),
            role=str(raw["role"]),
            command=tuple(str(value) for value in raw.get("command", ())),
            declared_tool_artifacts=tuple(
                str(value) for value in raw.get("declared_tool_artifacts", ())
            ),
            timing_scope=(
                str(raw["timing_scope"])
                if raw.get("timing_scope") is not None
                else None
            ),
            process_completion_grace_seconds=(
                float(raw["process_completion_grace_seconds"])
                if raw.get("process_completion_grace_seconds") is not None
                else None
            ),
            artifact_base_directory=base_directory,
        )
        for key, observed in (
            ("command_sha256", solver.command_sha256),
            ("tool_snapshot_sha256", solver.tool_snapshot_sha256),
        ):
            if raw.get(key) is not None and str(raw[key]) != observed:
                raise ValueError(f"solver {solver.solver_id!r} {key} no longer matches")
        if raw.get("tool_manifest") is not None and list(raw["tool_manifest"]) != list(
            solver.tool_manifest
        ):
            raise ValueError(
                f"solver {solver.solver_id!r} tool manifest no longer matches"
            )
        if (
            raw.get("evidence_classification") is not None
            and str(raw["evidence_classification"]) != solver.evidence_classification
        ):
            raise ValueError(
                f"solver {solver.solver_id!r} evidence classification no longer matches"
            )
        return solver


@dataclass(frozen=True)
class CorpusInstanceSpec:
    case_id: str
    family_id: str
    input_sha256: str

    def __post_init__(self) -> None:
        if not _CASE_ID.fullmatch(str(self.case_id)):
            raise ValueError("corpus case_id is invalid")
        get_benchmark_family(self.family_id)
        if not re.fullmatch(r"[0-9a-f]{64}", str(self.input_sha256)):
            raise ValueError("corpus input_sha256 must be a lowercase SHA-256 digest")

    def to_dict(self) -> dict[str, str]:
        return {
            "case_id": self.case_id,
            "family_id": self.family_id,
            "input_sha256": self.input_sha256,
        }


@dataclass(frozen=True)
class CorpusManifestSpec:
    corpus_id: str
    instances: tuple[CorpusInstanceSpec, ...]

    def __post_init__(self) -> None:
        if not _CASE_ID.fullmatch(str(self.corpus_id)):
            raise ValueError("corpus_id is invalid")
        if not self.instances:
            raise ValueError("corpus manifest must contain at least one instance")
        keys = [(row.family_id, row.case_id) for row in self.instances]
        if len(set(keys)) != len(keys):
            raise ValueError("corpus manifest contains duplicate family/case entries")

    @property
    def manifest_sha256(self) -> str:
        return sha256_json(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "corpus_id": self.corpus_id,
            "instances": [row.to_dict() for row in self.instances],
        }
        if include_hash:
            payload["manifest_sha256"] = self.manifest_sha256
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CorpusManifestSpec":
        raw = dict(payload)
        unknown = sorted(set(raw) - {"corpus_id", "instances", "manifest_sha256"})
        if unknown:
            raise ValueError(f"unknown corpus manifest fields: {unknown}")
        manifest = cls(
            corpus_id=str(raw["corpus_id"]),
            instances=tuple(
                CorpusInstanceSpec(
                    case_id=str(row["case_id"]),
                    family_id=str(row["family_id"]),
                    input_sha256=str(row["input_sha256"]),
                )
                for row in raw.get("instances", ())
            ),
        )
        if (
            raw.get("manifest_sha256") is not None
            and str(raw["manifest_sha256"]) != manifest.manifest_sha256
        ):
            raise ValueError("corpus manifest hash does not match its contents")
        return manifest


def make_corpus_manifest(
    cases: Sequence["BenchmarkCaseSpec"], *, corpus_id: str
) -> CorpusManifestSpec:
    return CorpusManifestSpec(
        corpus_id=corpus_id,
        instances=tuple(
            CorpusInstanceSpec(case.case_id, case.family_id, case.input_sha256)
            for case in cases
        ),
    )


@dataclass(frozen=True)
class BenchmarkCaseSpec:
    case_id: str
    family_id: str
    instance_path: str
    time_limit_seconds: float
    seeds: tuple[int, ...] = (17,)
    repetitions: int = 1
    workers: int = 1
    options: dict[str, dict[str, Any]] = field(default_factory=dict)
    solvers: tuple[BenchmarkSolverSpec, ...] = field(
        default_factory=lambda: (BenchmarkSolverSpec.planora(),)
    )
    official_validator_command: tuple[str, ...] = ()
    cpu_affinity: int | None = None
    artifact_base_directory: Any = field(default=None, repr=False, compare=False)
    input_sha256: str = field(init=False)
    official_validator_tool_manifest: tuple[dict[str, Any], ...] = field(init=False)
    official_validator_tool_snapshot_sha256: str | None = field(init=False)

    def __post_init__(self) -> None:
        if not _CASE_ID.fullmatch(str(self.case_id)):
            raise ValueError(
                "case_id must start with an alphanumeric character and contain "
                "only alphanumerics, dot, underscore, or hyphen"
            )
        get_benchmark_family(self.family_id)
        instance = Path(self.instance_path).resolve()
        if not instance.is_file():
            raise FileNotFoundError(f"benchmark instance does not exist: {instance}")
        if not math.isfinite(self.time_limit_seconds) or self.time_limit_seconds <= 0:
            raise ValueError("time_limit_seconds must be finite and positive")
        if not self.seeds or any(
            type(seed) is not int or seed < 0 for seed in self.seeds
        ):
            raise ValueError("seeds must contain non-negative integers")
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be unique within a case")
        if self.repetitions < 1:
            raise ValueError("repetitions must be positive")
        if self.workers < 1:
            raise ValueError("workers must be positive")
        if self.cpu_affinity is not None and self.cpu_affinity < 0:
            raise ValueError("cpu_affinity must be non-negative")
        solvers = tuple(self.solvers)
        if not solvers:
            raise ValueError("benchmark case must contain at least one solver")
        solver_ids = [solver.solver_id for solver in solvers]
        if len(set(solver_ids)) != len(solver_ids):
            raise ValueError("solver_id values must be unique within a case")
        planora_count = sum(solver.role == "planora" for solver in solvers)
        if planora_count != 1:
            raise ValueError("benchmark case must contain exactly one Planora solver")
        command = tuple(str(part) for part in self.official_validator_command)
        if command:
            command, validator_manifest, validator_hash = snapshot_command_tools(
                command,
                base_directory=self.artifact_base_directory,
            )
        else:
            validator_manifest = ()
            validator_hash = None
        object.__setattr__(self, "instance_path", str(instance))
        object.__setattr__(self, "input_sha256", sha256_file(instance))
        object.__setattr__(self, "seeds", tuple(int(seed) for seed in self.seeds))
        object.__setattr__(self, "options", _normalize_options(self.options))
        object.__setattr__(self, "solvers", solvers)
        object.__setattr__(self, "official_validator_command", command)
        object.__setattr__(self, "official_validator_tool_manifest", validator_manifest)
        object.__setattr__(
            self, "official_validator_tool_snapshot_sha256", validator_hash
        )

    @property
    def condition_payload(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "family_id": self.family_id,
            "instance_sha256": self.input_sha256,
            "time_limit_seconds": float(self.time_limit_seconds),
            "workers": int(self.workers),
            "options": self.options,
            "official_validator_tool_snapshot_sha256": (
                self.official_validator_tool_snapshot_sha256
            ),
            "cpu_affinity": self.cpu_affinity,
        }

    @property
    def condition_id(self) -> str:
        return sha256_json(self.condition_payload)[:20]

    @property
    def official_validator_evidence_classification(self) -> str:
        return (
            "diagnostic_unverified"
            if self.official_validator_command
            else "not_configured"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "family_id": self.family_id,
            "instance_path": self.instance_path,
            "input_sha256": self.input_sha256,
            "time_limit_seconds": float(self.time_limit_seconds),
            "seeds": list(self.seeds),
            "repetitions": int(self.repetitions),
            "workers": int(self.workers),
            "options": self.options,
            "solvers": [solver.to_dict() for solver in self.solvers],
            "official_validator_command": list(self.official_validator_command),
            "official_validator_evidence_classification": (
                self.official_validator_evidence_classification
            ),
            "official_validator_tool_manifest": [
                dict(row) for row in self.official_validator_tool_manifest
            ],
            "official_validator_tool_snapshot_sha256": (
                self.official_validator_tool_snapshot_sha256
            ),
            "cpu_affinity": self.cpu_affinity,
            "condition_id": self.condition_id,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        base_directory: str | Path | None = None,
    ) -> "BenchmarkCaseSpec":
        raw = dict(payload)
        allowed = {
            "case_id",
            "family_id",
            "instance_path",
            "time_limit_seconds",
            "seeds",
            "repetitions",
            "workers",
            "options",
            "solvers",
            "official_validator_command",
            "official_validator_evidence_classification",
            "official_validator_tool_manifest",
            "official_validator_tool_snapshot_sha256",
            "cpu_affinity",
            "condition_id",
            "input_sha256",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ValueError(f"unknown benchmark case fields: {unknown}")
        path = Path(str(raw["instance_path"]))
        if not path.is_absolute() and base_directory is not None:
            path = Path(base_directory) / path
        validator = raw.get("official_validator_command", ())
        if isinstance(validator, str):
            validator = (validator,)
        raw_solvers = raw.get("solvers")
        solvers = (
            tuple(
                BenchmarkSolverSpec.from_dict(row, base_directory=base_directory)
                for row in raw_solvers
            )
            if raw_solvers is not None
            else (BenchmarkSolverSpec.planora(),)
        )
        case = cls(
            case_id=str(raw["case_id"]),
            family_id=str(raw["family_id"]),
            instance_path=str(path.resolve()),
            time_limit_seconds=float(raw["time_limit_seconds"]),
            seeds=tuple(int(seed) for seed in raw.get("seeds", (17,))),
            repetitions=int(raw.get("repetitions", 1)),
            workers=int(raw.get("workers", 1)),
            options=dict(raw.get("options") or {}),
            solvers=solvers,
            official_validator_command=tuple(str(part) for part in validator),
            cpu_affinity=(
                int(raw["cpu_affinity"])
                if raw.get("cpu_affinity") is not None
                else None
            ),
            artifact_base_directory=base_directory,
        )
        declared_condition = raw.get("condition_id")
        declared_input = raw.get("input_sha256")
        if declared_input is not None and str(declared_input) != case.input_sha256:
            raise ValueError(
                f"case {case.case_id!r} input hash no longer matches its file"
            )
        if (
            declared_condition is not None
            and str(declared_condition) != case.condition_id
        ):
            raise ValueError(
                f"case {case.case_id!r} condition hash no longer matches its input/config"
            )
        declared_validator_hash = raw.get("official_validator_tool_snapshot_sha256")
        if declared_validator_hash is not None and str(declared_validator_hash) != str(
            case.official_validator_tool_snapshot_sha256
        ):
            raise ValueError(
                f"case {case.case_id!r} official validator tool hash no longer matches"
            )
        if raw.get("official_validator_tool_manifest") is not None and list(
            raw["official_validator_tool_manifest"]
        ) != list(case.official_validator_tool_manifest):
            raise ValueError(
                f"case {case.case_id!r} official validator tool manifest no longer matches"
            )
        if (
            raw.get("official_validator_evidence_classification") is not None
            and str(raw["official_validator_evidence_classification"])
            != case.official_validator_evidence_classification
        ):
            raise ValueError(
                f"case {case.case_id!r} validator evidence classification no longer matches"
            )
        return case


@dataclass(frozen=True)
class BenchmarkPlan:
    mode: str
    cases: tuple[BenchmarkCaseSpec, ...]
    minimum_effective_runs_per_condition: int
    supervision_grace_seconds: float = 40.0
    source_roots: tuple[str, ...] = DEFAULT_SOURCE_ROOTS
    require_official_validator_agreement: bool = False
    corpus_manifest: CorpusManifestSpec | None = None
    allow_equal_wall_time_claim: bool = False

    def __post_init__(self) -> None:
        if self.mode not in PLAN_MODES:
            raise ValueError(f"mode must be one of {sorted(PLAN_MODES)}")
        if not self.cases:
            raise ValueError("benchmark plan must contain at least one case")
        case_ids = [case.case_id for case in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("case_id values must be unique")
        if self.minimum_effective_runs_per_condition < 1:
            raise ValueError("minimum_effective_runs_per_condition must be positive")
        if (
            not math.isfinite(self.supervision_grace_seconds)
            or self.supervision_grace_seconds <= 0
        ):
            raise ValueError("supervision_grace_seconds must be finite and positive")
        roots = tuple(str(value) for value in self.source_roots)
        if not roots or any(not value for value in roots):
            raise ValueError("source_roots must be non-empty")
        missing_roots = sorted(set(DEFAULT_SOURCE_ROOTS) - set(roots))
        if missing_roots:
            raise ValueError(
                "source_roots cannot omit benchmark trust-boundary roots: "
                f"{missing_roots}"
            )
        if self.mode == "replicated":
            diagnostic_external_solvers = sorted(
                {
                    solver.solver_id
                    for case in self.cases
                    for solver in case.solvers
                    if solver.model == "external_command"
                }
            )
            diagnostic_external_validators = sorted(
                case.case_id for case in self.cases if case.official_validator_command
            )
            if diagnostic_external_solvers or diagnostic_external_validators:
                raise ValueError(
                    "external solvers and validators are diagnostic_unverified and "
                    "cannot enter replicated claim-grade plans; use a smoke plan "
                    "until a hermetic typed tool profile exists "
                    f"(solvers={diagnostic_external_solvers}, "
                    f"validator_cases={diagnostic_external_validators})"
                )
            comparison_requested = any(
                len(case.solvers) > 1 and case.family_id in _COMPARISON_AUTHORITY
                for case in self.cases
            )
            for case in self.cases:
                if len(case.seeds) < 3:
                    raise ValueError(
                        "replicated cases require at least three unique prespecified seeds"
                    )
                if case.family_id in {"itc2007-cbctt", "itc2007-pe"}:
                    raise ValueError(
                        f"{case.family_id} replicated native evidence is unavailable: "
                        "its external validator is diagnostic_unverified"
                    )
                expected_runs_per_solver = len(case.seeds) * int(case.repetitions)
                if case.repetitions < 2:
                    raise ValueError(
                        "replicated cases require at least two repetitions per seed"
                    )
                if expected_runs_per_solver < 6:
                    raise ValueError(
                        "replicated cases require at least six expected runs per solver"
                    )
                if expected_runs_per_solver < self.minimum_effective_runs_per_condition:
                    raise ValueError(
                        f"case {case.case_id!r} has {expected_runs_per_solver} "
                        "expected runs per solver, below "
                        f"minimum_effective_runs_per_condition="
                        f"{self.minimum_effective_runs_per_condition}"
                    )
                if (
                    case.family_id in {"itc2007-cbctt", "itc2007-pe"}
                    and not case.official_validator_command
                ):
                    raise ValueError(
                        f"{case.family_id} replicated evidence requires an official external validator"
                    )
                if len(case.solvers) > 1:
                    if case.family_id == "unitime-native":
                        raise ValueError(
                            "unitime-native external comparator scoring is unavailable"
                        )
                    if len(case.solvers) != 2:
                        raise ValueError(
                            "paired replicated cases require exactly two solvers"
                        )
                    if case.workers != 1 or case.cpu_affinity is None:
                        raise ValueError(
                            "paired replicated cases require workers=1 and an explicit CPU affinity"
                        )
                    if {solver.role for solver in case.solvers} != {
                        "planora",
                        "comparator",
                    }:
                        raise ValueError(
                            "paired cases require one Planora and one comparator solver"
                        )
                if (
                    comparison_requested
                    and case.family_id in _COMPARISON_AUTHORITY
                    and len(case.solvers) != 2
                ):
                    raise ValueError(
                        "replicated comparative evidence requires comparator "
                        "coverage for every comparison-authority manifest case; split "
                        "Planora-only native evidence into a separate smoke plan"
                    )
            if self.corpus_manifest is None:
                raise ValueError(
                    "replicated plans require an explicit exact corpus manifest"
                )
        if self.corpus_manifest is not None:
            expected = {
                (row.family_id, row.case_id): row.input_sha256
                for row in self.corpus_manifest.instances
            }
            observed = {
                (case.family_id, case.case_id): case.input_sha256 for case in self.cases
            }
            if expected != observed:
                missing = sorted(set(expected) - set(observed))
                extra = sorted(set(observed) - set(expected))
                changed = sorted(
                    key
                    for key in set(expected).intersection(observed)
                    if expected[key] != observed[key]
                )
                raise ValueError(
                    "corpus manifest does not exactly match plan cases "
                    f"(missing={missing}, extra={extra}, changed={changed})"
                )
        if self.allow_equal_wall_time_claim:
            for case in self.cases:
                scopes = {solver.timing_scope for solver in case.solvers}
                if len(case.solvers) > 1 and any(
                    solver.model == "planora_native" for solver in case.solvers
                ):
                    raise ValueError(
                        "equal-wall claims require Planora to run as a true "
                        "subprocess covering the whole solver; planora_native is "
                        "an in-process call"
                    )
                if len(case.solvers) > 1 and scopes != {"whole_solver_process_wall"}:
                    raise ValueError(
                        "equal-wall claims require every paired solver to use "
                        "timing_scope='whole_solver_process_wall'"
                    )
                if len(case.solvers) > 1 and any(
                    float(solver.process_completion_grace_seconds or 0.0) != 0.0
                    for solver in case.solvers
                ):
                    raise ValueError(
                        "equal-wall claims require zero process completion grace "
                        "for every paired solver"
                    )
        object.__setattr__(self, "source_roots", roots)

    @property
    def plan_sha256(self) -> str:
        return sha256_json(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "mode": self.mode,
            "minimum_effective_runs_per_condition": int(
                self.minimum_effective_runs_per_condition
            ),
            "supervision_grace_seconds": float(self.supervision_grace_seconds),
            "source_roots": list(self.source_roots),
            "require_official_validator_agreement": bool(
                self.require_official_validator_agreement
            ),
            "corpus_manifest": (
                self.corpus_manifest.to_dict() if self.corpus_manifest else None
            ),
            "allow_equal_wall_time_claim": bool(self.allow_equal_wall_time_claim),
            "cases": [case.to_dict() for case in self.cases],
        }
        if include_hash:
            payload["plan_sha256"] = self.plan_sha256
        return payload

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        base_directory: str | Path | None = None,
    ) -> "BenchmarkPlan":
        raw = dict(payload)
        allowed = {
            "schema_version",
            "mode",
            "minimum_effective_runs_per_condition",
            "supervision_grace_seconds",
            "source_roots",
            "require_official_validator_agreement",
            "corpus_manifest",
            "allow_equal_wall_time_claim",
            "cases",
            "plan_sha256",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ValueError(f"unknown benchmark plan fields: {unknown}")
        declared_schema = raw.get("schema_version")
        if declared_schema is not None and str(declared_schema) != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported benchmark plan schema {declared_schema!r}; "
                f"expected {SCHEMA_VERSION!r}"
            )
        mode = str(raw.get("mode", "smoke"))
        default_target = 6 if mode == "replicated" else 1
        plan = cls(
            mode=mode,
            cases=tuple(
                BenchmarkCaseSpec.from_dict(row, base_directory=base_directory)
                for row in raw.get("cases", ())
            ),
            minimum_effective_runs_per_condition=int(
                raw.get("minimum_effective_runs_per_condition", default_target)
            ),
            supervision_grace_seconds=float(raw.get("supervision_grace_seconds", 40.0)),
            source_roots=tuple(raw.get("source_roots", DEFAULT_SOURCE_ROOTS)),
            require_official_validator_agreement=bool(
                raw.get("require_official_validator_agreement", mode == "replicated")
            ),
            corpus_manifest=(
                CorpusManifestSpec.from_dict(raw["corpus_manifest"])
                if raw.get("corpus_manifest") is not None
                else None
            ),
            allow_equal_wall_time_claim=bool(
                raw.get("allow_equal_wall_time_claim", False)
            ),
        )
        declared_hash = raw.get("plan_sha256")
        if declared_hash is not None and str(declared_hash) != plan.plan_sha256:
            raise ValueError("benchmark plan hash does not match its contents")
        return plan


def make_smoke_plan(
    cases: Sequence[BenchmarkCaseSpec],
    *,
    supervision_grace_seconds: float = 40.0,
    corpus_manifest: CorpusManifestSpec | None = None,
) -> BenchmarkPlan:
    return BenchmarkPlan(
        mode="smoke",
        cases=tuple(cases),
        minimum_effective_runs_per_condition=1,
        supervision_grace_seconds=supervision_grace_seconds,
        require_official_validator_agreement=False,
        corpus_manifest=corpus_manifest,
    )


def make_replicated_plan(
    cases: Sequence[BenchmarkCaseSpec],
    *,
    corpus_manifest: CorpusManifestSpec,
    minimum_effective_runs_per_condition: int = 6,
    supervision_grace_seconds: float = 40.0,
    allow_equal_wall_time_claim: bool = False,
) -> BenchmarkPlan:
    return BenchmarkPlan(
        mode="replicated",
        cases=tuple(cases),
        minimum_effective_runs_per_condition=minimum_effective_runs_per_condition,
        supervision_grace_seconds=supervision_grace_seconds,
        require_official_validator_agreement=True,
        corpus_manifest=corpus_manifest,
        allow_equal_wall_time_claim=allow_equal_wall_time_claim,
    )


@dataclass(frozen=True)
class BenchmarkExecution:
    execution_index: int
    case: BenchmarkCaseSpec
    solver: BenchmarkSolverSpec
    seed: int
    repetition: int
    pair_order_position: int = 1

    @property
    def execution_id(self) -> str:
        base = f"{self.case.case_id}__seed-{self.seed}__rep-{self.repetition:03d}"
        if len(self.case.solvers) == 1 and self.solver.solver_id == "planora":
            return base
        return f"{base}__solver-{self.solver.solver_id}"

    @property
    def pair_cell_id(self) -> str:
        return sha256_json(
            {
                "condition_id": self.case.condition_id,
                "seed": int(self.seed),
                "repetition": int(self.repetition),
            }
        )[:20]

    @property
    def config_payload(self) -> dict[str, Any]:
        return {
            "case_id": self.case.case_id,
            "family_id": self.case.family_id,
            "time_limit_seconds": float(self.case.time_limit_seconds),
            "workers": int(self.case.workers),
            "seed": int(self.seed),
            "repetition": int(self.repetition),
            "options": self.case.options,
            "solver": self.solver.to_dict(),
            "official_validator_command": list(self.case.official_validator_command),
            "official_validator_evidence_classification": (
                self.case.official_validator_evidence_classification
            ),
            "official_validator_tool_manifest": [
                dict(row) for row in self.case.official_validator_tool_manifest
            ],
            "official_validator_tool_snapshot_sha256": (
                self.case.official_validator_tool_snapshot_sha256
            ),
            "cpu_affinity": self.case.cpu_affinity,
        }

    @property
    def config_sha256(self) -> str:
        return sha256_json(self.config_payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_index": int(self.execution_index),
            "execution_id": self.execution_id,
            "pair_cell_id": self.pair_cell_id,
            "pair_order_position": int(self.pair_order_position),
            "condition_id": self.case.condition_id,
            "config_sha256": self.config_sha256,
            "config": self.config_payload,
            "instance_path": self.case.instance_path,
            "input_sha256": self.case.input_sha256,
        }


def expand_plan(plan: BenchmarkPlan) -> tuple[BenchmarkExecution, ...]:
    executions: list[BenchmarkExecution] = []
    index = 0
    for case in plan.cases:
        cell_index = 0
        for repetition in range(1, case.repetitions + 1):
            for seed in case.seeds:
                solvers = list(case.solvers)
                if len(solvers) > 1 and cell_index % 2:
                    solvers.reverse()
                for order_position, solver in enumerate(solvers, start=1):
                    executions.append(
                        BenchmarkExecution(
                            execution_index=index,
                            case=case,
                            solver=solver,
                            seed=seed,
                            repetition=repetition,
                            pair_order_position=order_position,
                        )
                    )
                    index += 1
                cell_index += 1
    return tuple(executions)


def _score_authority(family_id: str, official_agreement: bool | None) -> str:
    family = get_benchmark_family(family_id)
    if official_agreement is True:
        return SCORE_AUTHORITY_OFFICIAL
    if family.score_status == "native_non_official":
        return SCORE_AUTHORITY_NATIVE
    return SCORE_AUTHORITY_INDEPENDENT


def _json_safe(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_safe(value.to_dict())
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _call_with_options(
    function: Any,
    positional: Sequence[Any],
    *,
    forced: Mapping[str, Any] | None = None,
    options: Mapping[str, Any] | None = None,
) -> Any:
    kwargs = dict(options or {})
    overlap = sorted(set(kwargs).intersection(forced or {}))
    if overlap:
        raise ValueError(
            f"options cannot override harness-controlled values: {overlap}"
        )
    kwargs.update(forced or {})
    signature = inspect.signature(function)
    accepts_extra = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if not accepts_extra:
        unknown = sorted(set(kwargs) - set(signature.parameters))
        if unknown:
            raise ValueError(
                f"unsupported options for {function.__module__}.{function.__name__}: "
                f"{unknown}"
            )
    return function(*positional, **kwargs)


def _trim_solver_payload(result: Any) -> dict[str, Any]:
    payload = _json_safe(result)
    if not isinstance(payload, dict):
        return {"result": payload}
    for large in ("assignments", "solution", "placements", "student_classes"):
        payload.pop(large, None)
    return payload


def _base_worker_record(
    execution: Mapping[str, Any],
    family_id: str,
    instance_path: Path,
) -> dict[str, Any]:
    family = get_benchmark_family(family_id)
    return {
        "schema_version": SCHEMA_VERSION,
        "execution_index": int(execution["execution_index"]),
        "execution_id": str(execution["execution_id"]),
        "pair_cell_id": str(execution.get("pair_cell_id", execution["execution_id"])),
        "pair_order_position": int(execution.get("pair_order_position", 1)),
        "condition_id": str(execution["condition_id"]),
        "case_id": str(execution["config"]["case_id"]),
        "family_id": family_id,
        "family_title": family.title,
        "instance_id": instance_path.stem,
        "instance_path": str(instance_path),
        "input_sha256": _observed_file_sha256(instance_path),
        "input_sha256_expected": str(execution["input_sha256"]),
        "config_sha256": str(execution["config_sha256"]),
        "seed": int(execution["config"]["seed"]),
        "repetition": int(execution["config"]["repetition"]),
        "time_limit_seconds": float(execution["config"]["time_limit_seconds"]),
        "workers": int(execution["config"]["workers"]),
        "solver_id": str(
            execution["config"].get("solver", {}).get("solver_id", "planora")
        ),
        "solver_model": str(
            execution["config"].get("solver", {}).get("model", "planora_native")
        ),
        "solver_role": str(
            execution["config"].get("solver", {}).get("role", "planora")
        ),
        "official_validator_evidence_classification": str(
            execution["config"].get(
                "official_validator_evidence_classification", "not_configured"
            )
        ),
        "evidence_classification": (
            "diagnostic_unverified"
            if execution["config"].get("solver", {}).get("model") == "external_command"
            or execution["config"].get("official_validator_command")
            else "source_frozen_native"
        ),
        "solver_command_sha256": execution["config"]
        .get("solver", {})
        .get("command_sha256"),
        "solver_tool_snapshot_sha256": execution["config"]
        .get("solver", {})
        .get("tool_snapshot_sha256"),
        "official_validator_tool_snapshot_sha256": execution["config"].get(
            "official_validator_tool_snapshot_sha256"
        ),
        "status": "NOT_RUN",
        "execution_isolation": "fresh_python_process_per_case",
        "worker_pid": None,
        "effective": False,
        "feasible": False,
        "solution_complete": None,
        "source_snapshot_match": None,
        "input_snapshot_match": None,
        "tool_snapshot_match": None,
        "official_validator_tool_snapshot_match": None,
        "score_authority": _score_authority(family_id, None),
        "score_authority_detail": family.score_status,
        "score_vector": None,
        "score_total": None,
        "score_components": None,
        "lower_is_better": True,
        "independent_validator_status": "not_run",
        "official_validator_status": (
            "not_configured" if family.official_validator_available else "not_available"
        ),
        "official_validator_agreement": None,
        "official_validator_configured": bool(
            execution["config"].get("official_validator_command")
        ),
        "validator_capability": family.validator_status,
        "output_path": None,
        "output_sha256": None,
        "solver_deadline_overrun_seconds": None,
        "configured_solver_budget_compliant": False,
        "configured_solver_budget_compliance_basis": "not_observed",
        "configured_solver_budget_tolerance_seconds": _BUDGET_TOLERANCE_SECONDS,
        "solve_wall_time_seconds": None,
        "configured_solver_time_scope": str(
            execution["config"]
            .get("solver", {})
            .get("timing_scope", "configured_solver_call")
        ),
        "configured_solver_elapsed_seconds": None,
        "configured_solver_time_limit_seconds": float(
            execution["config"]["time_limit_seconds"]
        ),
        "configured_search_seconds": float(execution["config"]["time_limit_seconds"]),
        "external_process_timeout_seconds": (
            float(execution["config"]["time_limit_seconds"])
            + float(
                execution["config"]
                .get("solver", {})
                .get("process_completion_grace_seconds", 0.0)
            )
            if execution["config"].get("solver", {}).get("model") == "external_command"
            else None
        ),
        "external_process_wall_time_seconds": None,
        "worker_wall_time_seconds": None,
        "worker_cpu_time_seconds": None,
        "worker_overrun_seconds": None,
        "peak_rss_bytes": None,
        "resource_measurement_scope": "not_measured",
        "timing_scope_note": (
            "configured_solver_elapsed_seconds follows configured_solver_time_scope; "
            "worker and supervisor wall clocks include different setup/validation scopes"
        ),
        "adapter": {
            "parser": family.parser_entrypoint,
            "scorer": family.scorer_entrypoint,
            "validator": family.validator_entrypoint,
            "solver": family.solver_entrypoint,
            "official_validator": family.official_validator_entrypoint,
        },
    }


def _solution_suffix(family_id: str) -> str:
    return {
        "itc2007-cbctt": ".out",
        "itc2007-pe": ".sln",
        "itc2007-exam": ".sln",
        "cbctt-extended": ".out",
        "itc2019": ".xml",
        "unitime-native": ".xml",
        "xhstt": ".xml",
    }[family_id]


def _attach_official_validation(
    record: dict[str, Any],
    *,
    family_id: str,
    command: Sequence[str],
    command_tool_manifest: Sequence[Mapping[str, Any]],
    instance_path: Path,
    output_path: Path,
    independent_validation: Any,
    timeout_seconds: float,
) -> None:
    family = get_benchmark_family(family_id)
    if not family.official_validator_available:
        record["official_validator_status"] = "not_available"
        return
    if not command:
        record["official_validator_status"] = "not_configured"
        return
    record["official_validator_command"] = list(command)
    record["official_validator_tool_manifest"] = [
        dict(row) for row in command_tool_manifest
    ]
    if not output_path.is_file():
        record["official_validator_status"] = "no_output"
        return
    official = resolve_benchmark_entrypoint(family.official_validator_entrypoint or "")
    try:
        with _clean_child_environment_context():
            _execute_official_validator(
                record,
                family_id=family_id,
                command=command,
                instance_path=instance_path,
                output_path=output_path,
                independent_validation=independent_validation,
                timeout_seconds=timeout_seconds,
                official=official,
            )
    except Exception as exc:
        record["official_validator_status"] = "error"
        record["official_validator_error"] = f"{type(exc).__name__}: {exc}"
        record["effective"] = False
        return


def _execute_official_validator(
    record: dict[str, Any],
    *,
    family_id: str,
    command: Sequence[str],
    instance_path: Path,
    output_path: Path,
    independent_validation: Any,
    timeout_seconds: float,
    official: Any,
) -> None:
    """Execute one official adapter under the caller's sanitized environment."""

    if family_id == "itc2007-cbctt":
        result = official(
            list(command),
            instance_path,
            output_path,
            timeout_seconds=timeout_seconds,
        )
        external = result.to_dict()
        internal_score = dict(record.get("score_components") or {})
        agreement = bool(
            result.feasible == bool(record.get("feasible"))
            and result.soft_score.to_dict() == internal_score
        )
        record["feasible"] = bool(result.feasible)
        record["solution_complete"] = bool(result.lecture_violations == 0)
        record["score_vector"] = [int(result.total_cost)]
        record["score_total"] = int(result.total_cost)
        record["score_components"] = result.soft_score.to_dict()
    elif family_id == "itc2007-pe":
        if len(command) != 1:
            raise ValueError("ITC-2007 PE validator command must be one executable")
        result = official(
            command[0],
            instance_path,
            output_path,
            timeout_seconds=timeout_seconds,
        )
        external = result.to_dict()
        agreement = bool(
            tuple(result.lexicographic)
            == tuple(independent_validation.score.lexicographic)
            and result.hard_violations == len(independent_validation.errors)
        )
        # PE is scored lexicographically by distance-to-feasibility and soft
        # cost. An unplaced event contributes to the first component; it is not
        # itself a hard-validator violation, so partial incumbents stay comparable.
        record["feasible"] = bool(result.feasible)
        record["solution_complete"] = bool(result.distance_to_feasibility == 0)
        record["score_vector"] = list(result.lexicographic)
        record["score_total"] = (
            int(result.soft_violations) if result.distance_to_feasibility == 0 else None
        )
    elif family_id == "itc2007-exam":
        result = official(
            command[0],
            instance_path,
            output_path,
            timeout_seconds=timeout_seconds,
            extra_arguments=tuple(command[1:]),
        )
        external = result.to_dict()
        agreement = bool(
            result.distance_to_feasibility
            == independent_validation.hard.distance_to_feasibility
            and result.overall_penalty == independent_validation.objective.total
        )
        record["feasible"] = bool(result.feasible)
        record["score_vector"] = [
            int(result.distance_to_feasibility),
            int(result.overall_penalty),
        ]
        record["score_total"] = int(result.overall_penalty) if result.feasible else None
    else:  # pragma: no cover - guarded by the registry
        raise ValueError(f"no official-validator adapter for {family_id}")
    record["official_validation"] = _json_safe(external)
    record["official_validator_agreement"] = bool(agreement)
    record["official_validator_status"] = "agreement" if agreement else "disagreement"
    if agreement:
        record["score_authority"] = SCORE_AUTHORITY_OFFICIAL
    else:
        record["status"] = "SCORER_MISMATCH"
        record["effective"] = False
        record["feasible"] = False


def _execute_ctt(
    record: dict[str, Any],
    *,
    instance_path: Path,
    output_path: Path,
    metadata_path: Path,
    execution: Mapping[str, Any],
) -> tuple[Any, float]:
    from benchmarks.itc2007_harness import run_planora_worker

    config = execution["config"]
    all_options = dict(config.get("options") or {})
    ignored_groups = sorted(
        group
        for group in ("parser", "solver", "validator", "writer")
        if all_options.get(group)
    )
    if ignored_groups:
        raise ValueError(
            "ITC-2007 CTT accepts adapter settings only in the 'ctt' option "
            f"group; non-empty groups: {ignored_groups}"
        )
    ctt = dict(all_options.get("ctt", {}))
    allowed = {
        "strategy",
        "itc2007_course_symmetry",
        "itc2007_adaptive_seeding",
        "itc2007_compact_adaptive_arms",
        "itc2007_fixed_time_room_dive",
        "itc2007_fixed_time_room_strategy",
    }
    unknown = sorted(set(ctt) - allowed)
    if unknown:
        raise ValueError(f"unsupported ITC-2007 CTT options: {unknown}")
    started = time.perf_counter()
    payload = run_planora_worker(
        instance_path,
        output_path,
        metadata_path,
        seed=int(config["seed"]),
        time_limit_seconds=float(config["time_limit_seconds"]),
        workers=int(config["workers"]),
        strategy=str(ctt.get("strategy", "projected_hybrid")),
        itc2007_course_symmetry=bool(ctt.get("itc2007_course_symmetry", False)),
        itc2007_adaptive_seeding=bool(ctt.get("itc2007_adaptive_seeding", True)),
        itc2007_compact_adaptive_arms=bool(
            ctt.get("itc2007_compact_adaptive_arms", False)
        ),
        itc2007_fixed_time_room_dive=bool(
            ctt.get("itc2007_fixed_time_room_dive", False)
        ),
        itc2007_fixed_time_room_strategy=str(
            ctt.get("itc2007_fixed_time_room_strategy", "oracle_then_cp")
        ),
        cpu=config.get("cpu_affinity"),
    )
    solve_wall = time.perf_counter() - started
    score = payload.get("official_score_internal")
    record["solver_result"] = _json_safe(payload)
    record["adapter"]["execution"] = "benchmarks.itc2007_harness:run_planora_worker"
    record["status"] = str(payload.get("status", "UNKNOWN"))
    record["feasible"] = bool(payload.get("feasible"))
    record["solution_complete"] = bool(record["feasible"] and output_path.is_file())
    record["independent_validator_status"] = "solver_internal_only"
    if isinstance(score, dict):
        record["score_vector"] = [int(score["total"])]
        record["score_total"] = int(score["total"])
        record["score_components"] = dict(score)
    record["solver_deadline_overrun_seconds"] = max(
        0.0,
        float(payload.get("worker_wall_time_seconds") or solve_wall)
        - float(config["time_limit_seconds"]),
    )
    return payload, solve_wall


def _execute_native(
    record: dict[str, Any],
    *,
    family_id: str,
    instance_path: Path,
    output_path: Path,
    execution: Mapping[str, Any],
) -> tuple[Any, Any, float]:
    family = get_benchmark_family(family_id)
    config = execution["config"]
    options = dict(config.get("options") or {})
    if options.get("ctt"):
        raise ValueError(
            f"the 'ctt' option group is unavailable for benchmark family {family_id}"
        )
    parser = resolve_benchmark_entrypoint(family.parser_entrypoint)
    solver = resolve_benchmark_entrypoint(family.solver_entrypoint or "")
    validator = (
        resolve_benchmark_entrypoint(family.validator_entrypoint)
        if family.validator_entrypoint
        else None
    )
    problem = _call_with_options(
        parser,
        (instance_path,),
        options=options.get("parser"),
    )
    seed_name = "random_seed" if family_id == "itc2019" else "seed"
    started = time.perf_counter()
    result = _call_with_options(
        solver,
        (problem,),
        forced={
            "time_limit_seconds": float(config["time_limit_seconds"]),
            seed_name: int(config["seed"]),
            "workers": int(config["workers"]),
        },
        options=options.get("solver"),
    )
    solve_wall = time.perf_counter() - started
    record["solver_result"] = _trim_solver_payload(result)
    record["status"] = str(getattr(result, "status", "UNKNOWN"))
    internal_overrun = getattr(result, "deadline_overrun_seconds", None)
    record["solver_deadline_overrun_seconds"] = max(
        float(internal_overrun or 0.0),
        max(0.0, solve_wall - float(config["time_limit_seconds"])),
    )

    independent: Any = None
    if family_id == "itc2007-pe":
        independent = _call_with_options(
            validator,
            (problem, result.assignments),
            options=options.get("validator"),
        )
        score = independent.score
        record["feasible"] = bool(independent.feasible)
        record["solution_complete"] = bool(score.distance_to_feasibility == 0)
        record["score_vector"] = list(score.lexicographic)
        record["score_total"] = (
            int(score.soft_violations) if score.distance_to_feasibility == 0 else None
        )
        record["score_components"] = score.to_dict()
        from benchmarks.itc2007_pe import write_itc2007_pe_solution

        write_itc2007_pe_solution(
            output_path,
            result.assignments,
            problem=problem,
            **dict(options.get("writer") or {}),
        )
    elif family_id == "itc2007-exam":
        independent = _call_with_options(
            validator,
            (problem, result.assignments),
            options=options.get("validator"),
        )
        record["feasible"] = bool(independent.feasible)
        record["solution_complete"] = bool(
            len(result.assignments) == len(problem.exams)
        )
        record["score_vector"] = [
            int(independent.hard.total),
            int(independent.objective.total),
        ]
        record["score_total"] = (
            int(independent.objective.total) if independent.feasible else None
        )
        record["score_components"] = independent.to_dict()
        if len(result.assignments) == len(problem.exams):
            from benchmarks.itc2007_exam import write_itc2007_exam_solution

            write_itc2007_exam_solution(
                output_path,
                result.assignments,
                problem=problem,
                **dict(options.get("writer") or {}),
            )
    elif family_id == "cbctt-extended":
        formulation = str(dict(options.get("solver") or {}).get("formulation", "UD2"))
        validator_options = dict(options.get("validator") or {})
        if (
            "formulation" in validator_options
            and str(validator_options["formulation"]) != formulation
        ):
            raise ValueError(
                "CB-CTT validator formulation must exactly match the solver formulation"
            )
        validator_options["formulation"] = formulation
        if result.validation is not None:
            independent = _call_with_options(
                validator,
                (problem, result.assignments),
                options=validator_options,
            )
            record["feasible"] = bool(independent.feasible)
            record["solution_complete"] = bool(independent.feasible)
            record["score_vector"] = [
                int(independent.hard_violations),
                int(independent.score.total),
            ]
            record["score_total"] = (
                int(independent.score.total) if independent.feasible else None
            )
            record["score_components"] = independent.score.to_dict()
            from benchmarks.cbctt_native import write_cbctt_solution

            write_cbctt_solution(
                output_path,
                result.assignments,
                **dict(options.get("writer") or {}),
            )
    elif family_id == "itc2019":
        errors = _call_with_options(
            validator,
            (problem, result.placements, result.student_classes),
            options=options.get("validator"),
        )
        independent = {"errors": list(errors), "feasible": not errors}
        record["feasible"] = bool(not errors and result.objective is not None)
        record["solution_complete"] = bool(record["feasible"])
        if record["feasible"]:
            scorer = resolve_benchmark_entrypoint(family.scorer_entrypoint)
            score = scorer(problem, result.placements, result.student_classes)
            if score.to_dict() != result.objective.to_dict():
                raise ValueError("ITC-2019 solver and independent scorer disagree")
            record["score_vector"] = [int(score.total)]
            record["score_total"] = int(score.total)
            record["score_components"] = score.to_dict()
            from benchmarks.itc2019 import write_itc2019_solution

            write_itc2019_solution(
                problem,
                result.placements,
                result.student_classes,
                output_path,
                **dict(options.get("writer") or {}),
            )
    elif family_id == "unitime-native":
        independent = _call_with_options(
            validator,
            (problem, result.solution),
            options=options.get("validator"),
        )
        record["feasible"] = bool(independent.feasible)
        record["solution_complete"] = bool(independent.feasible)
        record["score_vector"] = [
            int(independent.score.hard_violations),
            float(independent.score.native_total),
        ]
        record["score_total"] = (
            float(independent.score.native_total) if independent.feasible else None
        )
        record["score_components"] = independent.score.to_dict()
        if independent.supported and not independent.errors:
            from benchmarks.unitime_native import write_unitime_solution_xml

            write_unitime_solution_xml(
                output_path,
                problem,
                result.solution,
                **dict(options.get("writer") or {}),
            )
    elif family_id == "xhstt":
        independent = _call_with_options(
            validator,
            (problem, result.solution),
            options=options.get("validator"),
        )
        record["feasible"] = bool(independent.feasible)
        record["solution_complete"] = bool(independent.feasible)
        record["score_vector"] = list(independent.score.lexicographic)
        record["score_total"] = (
            int(independent.score.soft_cost) if independent.feasible else None
        )
        record["score_components"] = independent.score.to_dict()
        from benchmarks.xhstt import write_xhstt_solution

        write_xhstt_solution(
            output_path,
            result.solution,
            **dict(options.get("writer") or {}),
        )
    else:  # pragma: no cover - registry exhaustiveness guard
        raise ValueError(f"no native adapter for benchmark family {family_id!r}")

    if independent is None:
        record["independent_validator_status"] = "no_candidate"
    else:
        record["independent_validator_status"] = "completed"
        record["independent_validation"] = _json_safe(independent)
    return result, independent, solve_wall


def _render_external_command(
    command: Sequence[str],
    *,
    instance_path: Path,
    output_path: Path,
    run_directory: Path,
    seed: int,
    time_limit_seconds: float,
    workers: int,
) -> tuple[str, ...]:
    values = {
        "{instance_path}": str(instance_path),
        "{output_path}": str(output_path),
        "{run_directory}": str(run_directory),
        "{seed}": str(int(seed)),
        "{time_limit_seconds}": format(float(time_limit_seconds), ".17g"),
        "{workers}": str(int(workers)),
    }
    rendered: list[str] = []
    for raw in command:
        token = str(raw)
        for placeholder, value in values.items():
            token = token.replace(placeholder, value)
        if re.search(r"\{[^{}]+\}", token):
            raise ValueError(f"unresolved external-command placeholder in {raw!r}")
        rendered.append(token)
    return tuple(rendered)


def _score_external_candidate(
    record: dict[str, Any],
    *,
    family_id: str,
    instance_path: Path,
    output_path: Path,
    options: Mapping[str, Any],
) -> Any:
    """Parse and independently score a comparator's standard solution file."""

    if not output_path.is_file():
        raise FileNotFoundError("external solver did not create its requested output")
    if family_id == "itc2007-cbctt":
        from benchmarks.itc2007 import (
            convert_itc2007_to_instance,
            load_itc2007_solution,
            parse_itc2007_ctt,
            score_itc2007_schedule,
        )

        problem = parse_itc2007_ctt(instance_path)
        instance = convert_itc2007_to_instance(problem)
        schedule = load_itc2007_solution(output_path, problem, instance)
        score = score_itc2007_schedule(problem, instance, schedule)
        record["feasible"] = True
        record["solution_complete"] = True
        record["score_vector"] = [int(score.total)]
        record["score_total"] = int(score.total)
        record["score_components"] = score.to_dict()
        independent: Any = {"feasible": True, "score": score.to_dict()}
    elif family_id == "itc2007-pe":
        from benchmarks.itc2007_pe import (
            parse_itc2007_pe,
            parse_itc2007_pe_solution,
            validate_itc2007_pe_solution,
        )

        problem = parse_itc2007_pe(instance_path)
        assignments = parse_itc2007_pe_solution(output_path, problem)
        independent = validate_itc2007_pe_solution(problem, assignments)
        score = independent.score
        record["feasible"] = bool(independent.feasible)
        record["solution_complete"] = bool(score.distance_to_feasibility == 0)
        record["score_vector"] = list(score.lexicographic)
        record["score_total"] = (
            int(score.soft_violations) if score.distance_to_feasibility == 0 else None
        )
        record["score_components"] = score.to_dict()
    elif family_id == "itc2007-exam":
        from benchmarks.itc2007_exam import (
            parse_itc2007_exam,
            parse_itc2007_exam_solution,
            validate_itc2007_exam_solution,
        )

        problem = parse_itc2007_exam(instance_path)
        assignments = parse_itc2007_exam_solution(output_path, problem)
        independent = validate_itc2007_exam_solution(problem, assignments)
        record["feasible"] = bool(independent.feasible)
        record["solution_complete"] = bool(len(assignments) == len(problem.exams))
        record["score_vector"] = [
            int(independent.hard.total),
            int(independent.objective.total),
        ]
        record["score_total"] = (
            int(independent.objective.total) if independent.feasible else None
        )
        record["score_components"] = independent.to_dict()
    elif family_id == "itc2019":
        from benchmarks.itc2019 import (
            parse_itc2019_solution,
            parse_itc2019_xml,
            score_itc2019_solution,
            validate_itc2019_solution_document,
        )

        problem = parse_itc2019_xml(instance_path)
        solution = parse_itc2019_solution(output_path)
        errors = validate_itc2019_solution_document(problem, solution)
        independent = {"errors": list(errors), "feasible": not errors}
        record["feasible"] = not errors
        record["solution_complete"] = not errors
        if not errors:
            score = score_itc2019_solution(
                problem, solution.placements, solution.student_classes
            )
            record["score_vector"] = [int(score.total)]
            record["score_total"] = int(score.total)
            record["score_components"] = score.to_dict()
    elif family_id == "unitime-native":
        from benchmarks.unitime_native import (
            parse_unitime_xml,
            validate_unitime_solution,
        )

        problem = parse_unitime_xml(instance_path)
        output_problem = parse_unitime_xml(output_path)
        solution = output_problem.embedded_solution
        if solution is None:
            raise ValueError("UniTime output does not contain an embedded solution")
        independent = validate_unitime_solution(problem, solution)
        record["feasible"] = bool(independent.feasible)
        record["solution_complete"] = bool(independent.feasible)
        record["score_vector"] = [
            int(independent.score.hard_violations),
            float(independent.score.native_total),
        ]
        record["score_total"] = (
            float(independent.score.native_total) if independent.feasible else None
        )
        record["score_components"] = independent.score.to_dict()
    elif family_id == "cbctt-extended":
        from benchmarks.cbctt import parse_cbctt_ectt
        from benchmarks.cbctt_native import (
            parse_cbctt_solution,
            validate_cbctt_assignments,
        )

        problem = parse_cbctt_ectt(instance_path)
        assignments = parse_cbctt_solution(
            output_path, problem=problem, require_complete=True
        )
        validator_options = dict(options.get("validator") or {})
        validator_options.setdefault(
            "formulation", dict(options.get("solver") or {}).get("formulation", "UD2")
        )
        independent = validate_cbctt_assignments(
            problem, assignments, **validator_options
        )
        record["feasible"] = bool(independent.feasible)
        record["solution_complete"] = True
        record["score_vector"] = [
            int(independent.hard_violations),
            int(independent.score.total),
        ]
        record["score_total"] = (
            int(independent.score.total) if independent.feasible else None
        )
        record["score_components"] = independent.score.to_dict()
    elif family_id == "xhstt":
        from benchmarks.xhstt import (
            parse_xhstt,
            parse_xhstt_solutions,
            validate_xhstt_solution,
        )

        problem = parse_xhstt(instance_path)
        solutions = parse_xhstt_solutions(output_path, problem)
        if len(solutions) != 1:
            raise ValueError("external XHSTT output must contain exactly one solution")
        independent = validate_xhstt_solution(problem, solutions[0])
        record["feasible"] = bool(independent.feasible)
        record["solution_complete"] = True
        record["score_vector"] = list(independent.score.lexicographic)
        record["score_total"] = (
            int(independent.score.soft_cost) if independent.feasible else None
        )
        record["score_components"] = independent.score.to_dict()
    else:
        raise ValueError(
            f"external comparator scoring is unavailable for family {family_id!r}"
        )
    record["independent_validator_status"] = "completed"
    record["independent_validation"] = _json_safe(independent)
    return independent


@dataclass(frozen=True)
class _NoFollowFileSnapshot:
    path: Path
    payload: bytes = field(repr=False)
    sha256: str
    device: int
    inode: int
    stat_signature: tuple[int, ...]

    @property
    def identity(self) -> tuple[int, int]:
        return self.device, self.inode


def _stat_signature(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_mode),
        int(metadata.st_nlink),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
        int(metadata.st_ctime_ns),
    )


def _normalized_absolute_path(raw_path: str | Path) -> Path:
    raw = os.fspath(raw_path)
    if not isinstance(raw, str) or not os.path.isabs(raw):
        raise ValueError("artifact path must be absolute")
    if os.path.normpath(raw) != raw:
        raise ValueError("artifact path must be lexically normalized")
    path = Path(raw)
    if not path.name or any(part in {".", ".."} for part in path.parts):
        raise ValueError("artifact path must name a normalized file")
    return path


def _close_descriptors(descriptors: Sequence[int]) -> None:
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError:
            pass


def _snapshot_regular_file_no_follow(
    raw_path: str | Path,
    *,
    reject_hardlinks: bool,
) -> _NoFollowFileSnapshot:
    """Read one stable regular file through an ``O_NOFOLLOW`` descriptor."""

    path = _normalized_absolute_path(raw_path)
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory_flag is None:
        raise RuntimeError("secure directory-relative no-follow opens are unavailable")
    common_flags = int(no_follow) | int(getattr(os, "O_CLOEXEC", 0))
    directory_flags = os.O_RDONLY | common_flags | int(directory_flag)
    file_flags = (
        os.O_RDONLY
        | common_flags
        | int(getattr(os, "O_BINARY", 0))
        | int(getattr(os, "O_NONBLOCK", 0))
    )
    descriptors: list[int] = []
    components = path.parts[1:]
    try:
        root_descriptor = os.open(os.path.sep, directory_flags)
        descriptors.append(root_descriptor)
        directory_descriptors = [root_descriptor]
        directory_names: list[str] = []
        current = root_descriptor
        for component in components[:-1]:
            child = os.open(component, directory_flags, dir_fd=current)
            metadata = os.fstat(child)
            if not stat.S_ISDIR(metadata.st_mode):
                os.close(child)
                raise ValueError("artifact ancestor is not a directory")
            descriptors.append(child)
            directory_descriptors.append(child)
            directory_names.append(component)
            current = child
        descriptor = os.open(components[-1], file_flags, dir_fd=current)
        descriptors.append(descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("artifact descriptor is not a regular file")
        if reject_hardlinks and int(before.st_nlink) != 1:
            raise ValueError("native output must not have hard links")
        first_chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            first_chunks.append(chunk)
        between = os.fstat(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        second_chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            second_chunks.append(chunk)
        after = os.fstat(descriptor)
        signature = _stat_signature(before)
        if signature not in {
            _stat_signature(between),
            _stat_signature(after),
        } or _stat_signature(between) != _stat_signature(after):
            raise ValueError("artifact changed while it was read")
        payload = b"".join(first_chunks)
        repeated_payload = b"".join(second_chunks)
        if payload != repeated_payload:
            raise ValueError("artifact content changed between stable reads")

        for index, component in enumerate(directory_names):
            named = os.stat(
                component,
                dir_fd=directory_descriptors[index],
                follow_symlinks=False,
            )
            opened = os.fstat(directory_descriptors[index + 1])
            if stat.S_ISLNK(named.st_mode) or not stat.S_ISDIR(named.st_mode):
                raise ValueError("artifact ancestor changed type during read")
            if (int(named.st_dev), int(named.st_ino)) != (
                int(opened.st_dev),
                int(opened.st_ino),
            ):
                raise ValueError("artifact ancestor changed during read")
        named_leaf = os.stat(components[-1], dir_fd=current, follow_symlinks=False)
        if stat.S_ISLNK(named_leaf.st_mode) or not stat.S_ISREG(named_leaf.st_mode):
            raise ValueError("artifact leaf changed type during read")
        if signature != _stat_signature(named_leaf):
            raise ValueError("artifact changed after descriptor read")
    finally:
        _close_descriptors(descriptors)
    if len(payload) != int(before.st_size):
        raise ValueError("artifact byte length changed while it was read")
    return _NoFollowFileSnapshot(
        path=path,
        payload=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        device=int(before.st_dev),
        inode=int(before.st_ino),
        stat_signature=signature,
    )


def _write_private_parser_snapshot(path: Path, payload: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=False)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= int(getattr(os, "O_CLOEXEC", 0))
    flags |= int(getattr(os, "O_BINARY", 0))
    descriptor = os.open(path, flags, 0o600)
    try:
        view = memoryview(payload)
        written = 0
        while written < len(view):
            written += os.write(descriptor, view[written:])
        os.fsync(descriptor)
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o400)
    finally:
        os.close(descriptor)
    if not hasattr(os, "fchmod"):  # pragma: no cover - Windows fallback
        path.chmod(0o400)


def _native_run_artifact_paths(
    expected_execution: Mapping[str, Any],
    record: Mapping[str, Any],
) -> tuple[Path, Path, Path, dict[str, Any]]:
    """Bind a native row to the supervisor's exact per-execution run layout."""

    command = record.get("command")
    if not isinstance(command, (list, tuple)) or len(command) != 8:
        raise ValueError("native replicated row requires its supervisor command")
    rendered = tuple(str(item) for item in command)
    supervisor_python = record.get("supervisor_python_path")
    if not isinstance(supervisor_python, str):
        raise ValueError("native row does not name the supervisor Python executable")
    expected_python = _normalized_absolute_path(supervisor_python)
    try:
        resolved_expected_python = expected_python.resolve(strict=True)
    except OSError as exc:
        raise ValueError("native supervisor Python executable is unavailable") from exc
    current_python = Path(sys.executable).resolve(strict=True)
    if (
        rendered[0] != str(expected_python)
        or resolved_expected_python != current_python
        or rendered[1:5]
        != ("-m", "benchmarks.multifamily_harness", "worker", "--request")
        or rendered[6] != "--result"
    ):
        raise ValueError("native supervisor command has an unexpected shape")
    request_path = _normalized_absolute_path(rendered[5])
    result_path = _normalized_absolute_path(rendered[7])
    if request_path.name != "request.json" or result_path.name != "result.json":
        raise ValueError("native supervisor request/result filenames are invalid")
    if request_path.parent != result_path.parent:
        raise ValueError("native supervisor request/result directories differ")
    execution_id = str(expected_execution.get("execution_id"))
    run_directory = request_path.parent
    if run_directory.name != execution_id:
        raise ValueError("native run directory is not bound to execution_id")
    family_id = str(dict(expected_execution.get("config") or {}).get("family_id"))
    output_path = _normalized_absolute_path(str(record.get("output_path")))
    expected_output = run_directory / f"solution{_solution_suffix(family_id)}"
    if output_path != expected_output:
        raise ValueError("native output path is outside its exact run layout")

    request_snapshot = _snapshot_regular_file_no_follow(
        request_path, reject_hardlinks=True
    )
    result_snapshot = _snapshot_regular_file_no_follow(
        result_path, reject_hardlinks=True
    )
    for key, expected_path in (
        ("worker_request_path", request_path),
        ("worker_result_path", result_path),
    ):
        if str(record.get(key)) != str(expected_path):
            raise ValueError(f"native row {key} does not match its command")
    for key, snapshot in (
        ("worker_request_sha256", request_snapshot),
        ("worker_result_sha256", result_snapshot),
    ):
        if str(record.get(key)) != snapshot.sha256:
            raise ValueError(f"native row {key} does not match its artifact")
    if str(record.get("supervisor_python_sha256")) != sha256_file(
        resolved_expected_python
    ):
        raise ValueError("native row supervisor Python hash is invalid")

    try:
        request_payload = json.loads(request_snapshot.payload.decode("utf-8"))
        result_payload = json.loads(result_snapshot.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("native supervisor request/result is not valid JSON") from exc
    if not isinstance(request_payload, dict) or not isinstance(result_payload, dict):
        raise ValueError("native supervisor request/result must be JSON objects")
    if not result_payload:
        raise ValueError("native supervisor result must not be empty")
    if request_payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("native supervisor request schema is invalid")
    if request_payload.get("execution") != dict(expected_execution):
        raise ValueError("native supervisor request execution does not match")
    if str(request_payload.get("run_directory")) != str(run_directory):
        raise ValueError("native supervisor request run directory does not match")
    if str(request_payload.get("plan_sha256")) != str(record.get("plan_sha256")):
        raise ValueError("native supervisor request plan hash does not match")
    if str(request_payload.get("expected_source_sha256")) != str(
        record.get("source_sha256_expected")
    ):
        raise ValueError("native supervisor request source hash does not match")
    source_roots = request_payload.get("source_roots")
    if (
        not isinstance(source_roots, list)
        or any(not isinstance(item, str) or not item for item in source_roots)
        or not set(DEFAULT_SOURCE_ROOTS).issubset(source_roots)
    ):
        raise ValueError("native supervisor request source roots are incomplete")
    repo_root = request_payload.get("repo_root")
    if not isinstance(repo_root, str) or not Path(repo_root).is_absolute():
        raise ValueError("native supervisor request repository root is invalid")

    required_result_fields = {
        "execution_id",
        "config_sha256",
        "family_id",
        "case_id",
        "input_sha256",
        "status",
        "effective",
        "feasible",
        "output_path",
        "output_sha256",
    }
    if not required_result_fields.issubset(result_payload):
        raise ValueError("native supervisor result is missing required worker fields")
    for key, value in result_payload.items():
        if _canonical_json_bytes(record.get(key)) != _canonical_json_bytes(value):
            raise ValueError(f"native supervisor result field {key!r} was rewritten")
    return request_path, result_path, output_path, request_payload


def _derive_native_artifact_record(
    *,
    family_id: str,
    instance_path: Path,
    output_path: Path,
    options: Mapping[str, Any],
) -> dict[str, Any]:
    """Parse, validate, and score private artifact snapshots independently."""

    parser_options = dict(options.get("parser") or {})
    validator_options = dict(options.get("validator") or {})
    writer_options = dict(options.get("writer") or {})
    observed: dict[str, Any] = {}
    if options.get("ctt"):
        raise ValueError("the ctt option group is unavailable for this native lane")

    if family_id == "itc2007-exam":
        from benchmarks.itc2007_exam import (
            parse_itc2007_exam,
            parse_itc2007_exam_solution,
            validate_itc2007_exam_solution,
        )

        if writer_options:
            raise ValueError("ITC-2007 Exam writer options are unsupported")
        problem = _call_with_options(
            parse_itc2007_exam, (instance_path,), options=parser_options
        )
        assignments = parse_itc2007_exam_solution(output_path, problem)
        independent = _call_with_options(
            validate_itc2007_exam_solution,
            (problem, assignments),
            options=validator_options,
        )
        observed.update(
            feasible=bool(independent.feasible),
            solution_complete=bool(len(assignments) == len(problem.exams)),
            score_vector=[
                int(independent.hard.total),
                int(independent.objective.total),
            ],
            score_total=(
                int(independent.objective.total) if independent.feasible else None
            ),
            score_components=independent.to_dict(),
        )
    elif family_id == "cbctt-extended":
        from benchmarks.cbctt import parse_cbctt_ectt
        from benchmarks.cbctt_native import (
            parse_cbctt_solution,
            validate_cbctt_assignments,
        )

        if writer_options:
            raise ValueError("extended CB-CTT writer options are unsupported")
        problem = _call_with_options(
            parse_cbctt_ectt, (instance_path,), options=parser_options
        )
        assignments = parse_cbctt_solution(
            output_path, problem=problem, require_complete=True
        )
        solver_formulation = str(
            dict(options.get("solver") or {}).get("formulation", "UD2")
        )
        if (
            "formulation" in validator_options
            and str(validator_options["formulation"]) != solver_formulation
        ):
            raise ValueError(
                "CB-CTT validator formulation must exactly match the solver formulation"
            )
        validator_options["formulation"] = solver_formulation
        independent = _call_with_options(
            validate_cbctt_assignments,
            (problem, assignments),
            options=validator_options,
        )
        observed.update(
            feasible=bool(independent.feasible),
            solution_complete=bool(independent.feasible),
            score_vector=[
                int(independent.hard_violations),
                int(independent.score.total),
            ],
            score_total=(
                int(independent.score.total) if independent.feasible else None
            ),
            score_components=independent.score.to_dict(),
        )
    elif family_id == "itc2019":
        from benchmarks.itc2019 import (
            parse_itc2019_solution,
            parse_itc2019_xml,
            score_itc2019_solution,
            validate_itc2019_solution_document,
        )

        problem = _call_with_options(
            parse_itc2019_xml, (instance_path,), options=parser_options
        )
        solution = parse_itc2019_solution(output_path)
        errors = _call_with_options(
            validate_itc2019_solution_document,
            (problem, solution),
            options=validator_options,
        )
        independent = {"errors": list(errors), "feasible": not errors}
        observed.update(
            feasible=not errors,
            solution_complete=not errors,
        )
        if not errors:
            score = score_itc2019_solution(
                problem, solution.placements, solution.student_classes
            )
            observed.update(
                score_vector=[int(score.total)],
                score_total=int(score.total),
                score_components=score.to_dict(),
            )
        allowed_writer_options = {"metadata"}
        if set(writer_options) - allowed_writer_options:
            raise ValueError("unsupported ITC-2019 writer options")
    elif family_id == "unitime-native":
        from benchmarks.unitime_native import (
            parse_unitime_xml,
            validate_unitime_solution,
        )

        allowed_writer_options = {"sectioning_solution_mode", "allow_unsupported"}
        if set(writer_options) - allowed_writer_options:
            raise ValueError("unsupported UniTime writer options")
        problem = _call_with_options(
            parse_unitime_xml, (instance_path,), options=parser_options
        )
        output_problem = parse_unitime_xml(
            output_path,
            sectioning_solution_mode=str(
                writer_options.get("sectioning_solution_mode", "best")
            ),
        )
        if output_problem.kind != problem.kind:
            raise ValueError("UniTime output kind differs from the input problem")
        solution = output_problem.embedded_solution
        if solution is None:
            raise ValueError("UniTime output does not contain an embedded solution")
        if solution.kind != problem.kind:
            raise ValueError("UniTime embedded solution kind differs from the input")
        independent = _call_with_options(
            validate_unitime_solution,
            (problem, solution),
            options=validator_options,
        )
        observed.update(
            feasible=bool(independent.feasible),
            solution_complete=bool(independent.feasible),
            score_vector=[
                int(independent.score.hard_violations),
                float(independent.score.native_total),
            ],
            score_total=(
                float(independent.score.native_total) if independent.feasible else None
            ),
            score_components=independent.score.to_dict(),
        )
    elif family_id == "xhstt":
        from benchmarks.xhstt import (
            parse_xhstt,
            parse_xhstt_solutions,
            validate_xhstt_solution,
        )

        if set(writer_options) - {"solution_group_id"}:
            raise ValueError("unsupported XHSTT writer options")
        problem = _call_with_options(
            parse_xhstt, (instance_path,), options=parser_options
        )
        solutions = parse_xhstt_solutions(output_path, problem)
        if len(solutions) != 1:
            raise ValueError("XHSTT output must contain exactly one solution")
        if solutions[0].instance_id != problem.id:
            raise ValueError("XHSTT output references the wrong instance")
        independent = _call_with_options(
            validate_xhstt_solution,
            (problem, solutions[0]),
            options=validator_options,
        )
        observed.update(
            feasible=bool(independent.feasible),
            solution_complete=bool(independent.feasible),
            score_vector=list(independent.score.lexicographic),
            score_total=(
                int(independent.score.soft_cost) if independent.feasible else None
            ),
            score_components=independent.score.to_dict(),
        )
    else:
        raise ValueError(
            f"native artifact revalidation is unavailable for family {family_id!r}"
        )

    observed["score_authority"] = _score_authority(family_id, None)
    observed["independent_validator_status"] = "completed"
    observed["independent_validation"] = _json_safe(independent)
    return observed


def _revalidation_failure(reason: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "reason": str(reason),
        "output_path": None,
        "output_identity": None,
    }


def _revalidate_native_artifact(
    expected_execution: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    source_cache: dict[tuple[str, tuple[str, ...]], str] | None = None,
    derivation_cache: dict[tuple[str, str, str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Independently derive a native row from stable, private artifact copies."""

    try:
        config = dict(expected_execution.get("config") or {})
        solver = dict(config.get("solver") or {})
        family_id = str(config.get("family_id"))
        if solver.get("model") != "planora_native":
            return _revalidation_failure("not_planora_native")
        if family_id in {"itc2007-cbctt", "itc2007-pe"}:
            return _revalidation_failure("claim_lane_unavailable")
        expected_input_sha256 = str(expected_execution["input_sha256"])
        if not re.fullmatch(r"[0-9a-f]{64}", expected_input_sha256):
            return _revalidation_failure("invalid_expected_input_sha256")
        _, _, bound_output_path, request_payload = _native_run_artifact_paths(
            expected_execution, record
        )
        repo_root = str(request_payload["repo_root"])
        source_roots = tuple(str(item) for item in request_payload["source_roots"])
        source_key = (repo_root, source_roots)
        cache = source_cache if source_cache is not None else {}
        observed_source = cache.get(source_key)
        if observed_source is None:
            observed_source, _ = source_snapshot(repo_root, source_roots)
            cache[source_key] = observed_source
        if observed_source != str(record.get("source_sha256_expected")):
            return _revalidation_failure("source_sha256_mismatch")
        input_snapshot = _snapshot_regular_file_no_follow(
            str(expected_execution["instance_path"]), reject_hardlinks=False
        )
        if input_snapshot.sha256 != expected_input_sha256:
            return _revalidation_failure("input_sha256_mismatch")
        output_snapshot = _snapshot_regular_file_no_follow(
            bound_output_path, reject_hardlinks=True
        )
        if input_snapshot.identity == output_snapshot.identity:
            return _revalidation_failure("input_output_alias")
        if output_snapshot.sha256 != str(record.get("output_sha256")):
            return _revalidation_failure("output_sha256_mismatch")

        options = dict(config.get("options") or {})
        derivation_key = (
            family_id,
            input_snapshot.sha256,
            output_snapshot.sha256,
            sha256_json(options),
        )
        derived_cache = derivation_cache if derivation_cache is not None else {}
        cached_observed = derived_cache.get(derivation_key)
        if cached_observed is None:
            with tempfile.TemporaryDirectory(
                prefix="planora-native-revalidate-"
            ) as raw:
                private_root = Path(raw)
                private_input = private_root / "input" / input_snapshot.path.name
                private_output = private_root / "output" / output_snapshot.path.name
                _write_private_parser_snapshot(private_input, input_snapshot.payload)
                _write_private_parser_snapshot(private_output, output_snapshot.payload)
                observed = _derive_native_artifact_record(
                    family_id=family_id,
                    instance_path=private_input,
                    output_path=private_output,
                    options=options,
                )
            derived_cache[derivation_key] = observed
        else:
            observed = cached_observed

        input_after = _snapshot_regular_file_no_follow(
            input_snapshot.path, reject_hardlinks=False
        )
        output_after = _snapshot_regular_file_no_follow(
            output_snapshot.path, reject_hardlinks=True
        )
        if (
            input_after.identity != input_snapshot.identity
            or input_after.sha256 != input_snapshot.sha256
            or input_after.stat_signature != input_snapshot.stat_signature
        ):
            return _revalidation_failure("input_changed_during_revalidation")
        if (
            output_after.identity != output_snapshot.identity
            or output_after.sha256 != output_snapshot.sha256
            or output_after.stat_signature != output_snapshot.stat_signature
        ):
            return _revalidation_failure("output_changed_during_revalidation")

        canonical_fields = (
            "feasible",
            "solution_complete",
            "score_authority",
            "score_vector",
            "score_total",
            "score_components",
            "independent_validator_status",
            "independent_validation",
        )
        mismatched = [
            key
            for key in canonical_fields
            if _canonical_json_bytes(record.get(key))
            != _canonical_json_bytes(observed.get(key))
        ]
        if mismatched:
            return _revalidation_failure(
                "canonical_record_mismatch:" + ",".join(mismatched)
            )
        return {
            "status": "passed",
            "reason": "independently_reparsed_validated_and_scored",
            "output_path": str(output_snapshot.path),
            "output_identity": list(output_snapshot.identity),
        }
    except Exception as exc:
        return _revalidation_failure(
            f"revalidation_error:{type(exc).__name__}:{str(exc)[:200]}"
        )


def _execute_external(
    record: dict[str, Any],
    *,
    family_id: str,
    instance_path: Path,
    output_path: Path,
    run_directory: Path,
    execution: Mapping[str, Any],
) -> tuple[Any, float]:
    config = execution["config"]
    solver = dict(config["solver"])
    rendered = _render_external_command(
        tuple(solver["command"]),
        instance_path=instance_path,
        output_path=output_path,
        run_directory=run_directory,
        seed=int(config["seed"]),
        time_limit_seconds=float(config["time_limit_seconds"]),
        workers=int(config["workers"]),
    )
    process = _run_isolated_process(
        rendered,
        cwd=run_directory,
        timeout_seconds=(
            float(config["time_limit_seconds"])
            + float(solver.get("process_completion_grace_seconds", 0.0))
        ),
        stdout_path=run_directory / "solver-stdout.log",
        stderr_path=run_directory / "solver-stderr.log",
        cpu_affinity=config.get("cpu_affinity"),
    )
    record["external_solver_process"] = process
    record["external_process_wall_time_seconds"] = float(
        process["supervisor_wall_time_seconds"]
    )
    if solver.get("timing_scope") == "whole_solver_process_wall":
        record["configured_solver_elapsed_seconds"] = float(
            process["supervisor_wall_time_seconds"]
        )
    record["solver_deadline_overrun_seconds"] = None
    if process["timed_out"]:
        raise TimeoutError(
            "external solver exceeded its separate process-completion limit"
        )
    if process["exit_code"] != 0:
        raise RuntimeError(f"external solver exited with code {process['exit_code']}")
    record["configured_solver_budget_compliant"] = True
    record["configured_solver_budget_compliance_basis"] = (
        "required_configured_limit_argv_and_bounded_process_completion"
    )
    independent = _score_external_candidate(
        record,
        family_id=family_id,
        instance_path=instance_path,
        output_path=output_path,
        options=dict(config.get("options") or {}),
    )
    record["solver_result"] = {
        "model": "external_command",
        "command_sha256": solver["command_sha256"],
        "process_exit_code": process["exit_code"],
    }
    record["status"] = "COMPLETED"
    return independent, float(process["supervisor_wall_time_seconds"])


def _usage_snapshot() -> dict[str, float | None]:
    if resource is None:
        return {"cpu_seconds": None, "peak_rss_bytes": None}
    self_usage = resource.getrusage(resource.RUSAGE_SELF)
    child_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    rss_raw = max(float(self_usage.ru_maxrss), float(child_usage.ru_maxrss))
    if platform.system() != "Darwin":
        rss_raw *= 1024.0
    return {
        "cpu_seconds": float(
            self_usage.ru_utime
            + self_usage.ru_stime
            + child_usage.ru_utime
            + child_usage.ru_stime
        ),
        "peak_rss_bytes": rss_raw,
    }


def run_worker_request(request: Mapping[str, Any]) -> dict[str, Any]:
    repo_root = Path(str(request["repo_root"])).resolve()
    execution = dict(request["execution"])
    config = dict(execution["config"])
    family_id = str(config["family_id"])
    instance_path = Path(str(execution["instance_path"])).resolve()
    run_directory = Path(str(request["run_directory"])).resolve()
    expected_source = str(request["expected_source_sha256"])
    source_roots = tuple(str(value) for value in request["source_roots"])
    record = _base_worker_record(execution, family_id, instance_path)
    record["plan_sha256"] = str(request["plan_sha256"])
    record["worker_pid"] = int(os.getpid())
    record["source_sha256_expected"] = expected_source
    record["official_validator_configured"] = bool(
        config.get("official_validator_command")
    )
    if sha256_json(config) != str(execution["config_sha256"]):
        record["status"] = "CONFIG_HASH_MISMATCH"
        return record
    input_before = _observed_file_sha256(instance_path)
    record["input_sha256_worker_start"] = input_before
    if input_before != str(execution["input_sha256"]):
        invalidate_for_input_drift(
            record,
            observed_input_sha256=input_before,
        )
        return record
    record["input_snapshot_match"] = True
    solver_config = dict(config.get("solver") or {})
    solver_tool_manifest = tuple(solver_config.get("tool_manifest") or ())
    official_tool_manifest = tuple(config.get("official_validator_tool_manifest") or ())
    record["tool_snapshot_match"] = tool_snapshot_matches(solver_tool_manifest)
    record["official_validator_tool_snapshot_match"] = (
        tool_snapshot_matches(official_tool_manifest)
        if config.get("official_validator_command")
        else True
    )
    if (
        not record["tool_snapshot_match"]
        or not record["official_validator_tool_snapshot_match"]
    ):
        invalidate_for_tool_drift(record)
        return record
    source_before, _ = source_snapshot(repo_root, source_roots)
    record["source_sha256_worker_start"] = source_before
    if source_before != expected_source:
        record["status"] = "SOURCE_DRIFT"
        record["source_snapshot_match"] = False
        return record

    output_path = run_directory / f"solution{_solution_suffix(family_id)}"
    metadata_path = run_directory / "adapter-worker.json"
    usage_before = _usage_snapshot()
    worker_started = time.perf_counter()
    independent: Any = None
    try:
        parse_started = time.perf_counter()
        if solver_config.get("model", "planora_native") == "external_command":
            record["parse_seconds"] = None
            independent, solve_wall = _execute_external(
                record,
                family_id=family_id,
                instance_path=instance_path,
                output_path=output_path,
                run_directory=run_directory,
                execution=execution,
            )
        elif family_id == "itc2007-cbctt":
            # Parsing is performed inside the production adapter.
            record["parse_seconds"] = None
            _, solve_wall = _execute_ctt(
                record,
                instance_path=instance_path,
                output_path=output_path,
                metadata_path=metadata_path,
                execution=execution,
            )
        else:
            # _execute_native includes parsing; retain an honest combined setup
            # measurement rather than presenting it as solver time.
            result, independent, solve_wall = _execute_native(
                record,
                family_id=family_id,
                instance_path=instance_path,
                output_path=output_path,
                execution=execution,
            )
            record["adapter_result_type"] = type(result).__name__
            record["parse_and_adapter_seconds"] = float(
                time.perf_counter() - parse_started
            )
        record["solve_wall_time_seconds"] = float(solve_wall)
        if (
            record["configured_solver_elapsed_seconds"] is None
            and solver_config.get("model", "planora_native") == "planora_native"
        ):
            record["configured_solver_elapsed_seconds"] = float(solve_wall)
        if solver_config.get("model", "planora_native") == "planora_native":
            overrun = record.get("solver_deadline_overrun_seconds")
            observed_elapsed = record.get("configured_solver_elapsed_seconds")
            configured_limit = float(config["time_limit_seconds"])
            record["configured_solver_budget_compliant"] = bool(
                isinstance(overrun, (int, float))
                and float(overrun) <= _BUDGET_TOLERANCE_SECONDS
                and isinstance(observed_elapsed, (int, float))
                and float(observed_elapsed)
                <= configured_limit + _BUDGET_TOLERANCE_SECONDS
            )
            record["configured_solver_budget_compliance_basis"] = (
                "native_reported_overrun_and_harness_observed_solver_elapsed"
            )
        record["output_path"] = str(output_path) if output_path.is_file() else None
        record["output_sha256"] = (
            sha256_file(output_path) if output_path.is_file() else None
        )
        _attach_official_validation(
            record,
            family_id=family_id,
            command=tuple(config.get("official_validator_command") or ()),
            command_tool_manifest=official_tool_manifest,
            instance_path=instance_path,
            output_path=output_path,
            independent_validation=independent,
            timeout_seconds=30.0,
        )
        has_score = isinstance(record.get("score_vector"), list)
        independent_complete = record["independent_validator_status"] == "completed"
        if family_id == "itc2007-cbctt":
            independent_complete = record["official_validator_status"] == "agreement"
        supported = True
        validation = record.get("independent_validation")
        if isinstance(validation, dict):
            supported = not bool(validation.get("unsupported_features"))
        official_ok = record["official_validator_status"] not in {
            "disagreement",
            "error",
            "no_output",
        }
        record["effective"] = bool(
            has_score and independent_complete and supported and official_ok
        )
        if record["official_validator_status"] == "error":
            record["status"] = "OFFICIAL_VALIDATOR_ERROR"
        elif (
            record["official_validator_status"] == "no_output"
            and record["official_validator_configured"]
        ):
            record["status"] = "OFFICIAL_VALIDATOR_NO_OUTPUT"
        elif record["status"] not in {"SCORER_MISMATCH"}:
            record["status"] = "COMPLETED"
    except Exception as exc:
        record["status"] = "ADAPTER_ERROR"
        record["adapter_error"] = f"{type(exc).__name__}: {exc}"
        record["effective"] = False
        record["feasible"] = False

    source_after, _ = source_snapshot(repo_root, source_roots)
    record["source_sha256_worker_end"] = source_after
    record["source_snapshot_match"] = bool(
        source_before == expected_source == source_after
    )
    if not record["source_snapshot_match"]:
        invalidate_for_source_drift(record, observed_source_sha256=source_after)
    input_after = _observed_file_sha256(instance_path)
    record["input_sha256_worker_end"] = input_after
    if input_after != input_before:
        invalidate_for_input_drift(
            record,
            observed_input_sha256=input_after,
        )
    record["tool_snapshot_match"] = tool_snapshot_matches(solver_tool_manifest)
    record["official_validator_tool_snapshot_match"] = (
        tool_snapshot_matches(official_tool_manifest)
        if config.get("official_validator_command")
        else True
    )
    if (
        not record["tool_snapshot_match"]
        or not record["official_validator_tool_snapshot_match"]
    ):
        invalidate_for_tool_drift(record)
    usage_after = _usage_snapshot()
    record["worker_wall_time_seconds"] = float(time.perf_counter() - worker_started)
    if (
        usage_before["cpu_seconds"] is not None
        and usage_after["cpu_seconds"] is not None
    ):
        record["worker_cpu_time_seconds"] = max(
            0.0,
            float(usage_after["cpu_seconds"]) - float(usage_before["cpu_seconds"]),
        )
    else:
        record["worker_cpu_time_seconds"] = None
    record["peak_rss_bytes"] = usage_after["peak_rss_bytes"]
    record["resource_measurement_scope"] = (
        "worker_self_plus_descendants_rusage"
        if resource is not None
        else "unavailable_on_platform"
    )
    record["worker_overrun_seconds"] = max(
        0.0,
        float(record["worker_wall_time_seconds"]) - float(config["time_limit_seconds"]),
    )
    return _json_safe(record)


def invalidate_for_source_drift(
    record: dict[str, Any],
    *,
    observed_source_sha256: str,
) -> dict[str, Any]:
    """Invalidate a record without deleting the raw diagnostic evidence."""

    record["status_before_source_drift"] = record.get("status")
    record["observed_score_before_source_drift"] = {
        "feasible": record.get("feasible"),
        "score_vector": record.get("score_vector"),
        "score_total": record.get("score_total"),
        "score_authority": record.get("score_authority"),
    }
    record["status"] = "SOURCE_DRIFT"
    record["source_snapshot_match"] = False
    record["source_sha256_observed"] = str(observed_source_sha256)
    record["effective"] = False
    record["feasible"] = False
    record["score_vector"] = None
    record["score_total"] = None
    record["score_authority"] = "invalidated"
    return record


def invalidate_for_input_drift(
    record: dict[str, Any],
    *,
    observed_input_sha256: str | None,
) -> dict[str, Any]:
    """Prevent a changed instance from contributing benchmark claims."""

    record["status_before_input_drift"] = record.get("status")
    record["observed_score_before_input_drift"] = {
        "feasible": record.get("feasible"),
        "score_vector": record.get("score_vector"),
        "score_total": record.get("score_total"),
        "score_authority": record.get("score_authority"),
    }
    record["status"] = "INPUT_DRIFT"
    record["input_snapshot_match"] = False
    record["input_sha256_observed"] = observed_input_sha256
    record["effective"] = False
    record["feasible"] = False
    record["score_vector"] = None
    record["score_total"] = None
    record["score_authority"] = "invalidated"
    return record


def invalidate_for_tool_drift(record: dict[str, Any]) -> dict[str, Any]:
    """Prevent changed solver/validator binaries from contributing claims."""

    record["status_before_tool_drift"] = record.get("status")
    record["observed_score_before_tool_drift"] = {
        "feasible": record.get("feasible"),
        "score_vector": record.get("score_vector"),
        "score_total": record.get("score_total"),
        "score_authority": record.get("score_authority"),
    }
    record["status"] = "TOOL_DRIFT"
    record["effective"] = False
    record["feasible"] = False
    record["score_vector"] = None
    record["score_total"] = None
    record["score_authority"] = "invalidated"
    return record


def _child_environment() -> dict[str, str]:
    environment = {
        name: os.environ[name]
        for name in _CHILD_ENVIRONMENT_PASSTHROUGH
        if os.environ.get(name)
    }
    environment.update(
        {
            "PATH": os.defpath,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "TZ": "UTC",
            "PYTHONHASHSEED": "0",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        }
    )
    return environment


@contextmanager
def _clean_child_environment_context() -> Iterable[None]:
    """Temporarily apply the same allowlist used for every child process.

    Official validator adapters spawn their own subprocesses and do not expose
    an ``env`` parameter.  Workers are single-run isolated processes, so this
    scoped replacement safely guarantees the nested validator inherits the
    exact same deterministic environment as solvers and worker processes.
    """

    original = dict(os.environ)
    sanitized = _child_environment()
    try:
        os.environ.clear()
        os.environ.update(sanitized)
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def _pin_current_process(cpu: int | None) -> None:
    if cpu is None:
        return
    if not hasattr(os, "sched_setaffinity"):
        raise RuntimeError("CPU affinity is unavailable on this platform")
    allowed = set(os.sched_getaffinity(0))
    if int(cpu) not in allowed:
        raise ValueError(
            f"CPU {cpu} is unavailable; allowed CPUs are {sorted(allowed)}"
        )
    os.sched_setaffinity(0, {int(cpu)})


def _run_isolated_process(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout_seconds: float,
    stdout_path: Path,
    stderr_path: Path,
    cpu_affinity: int | None,
) -> dict[str, Any]:
    if cpu_affinity is not None and (
        os.name != "posix" or not hasattr(os, "sched_setaffinity")
    ):
        raise RuntimeError(
            "requested single-CPU affinity cannot be enforced on this platform"
        )
    started = time.perf_counter()
    usage_before = (
        resource.getrusage(resource.RUSAGE_CHILDREN) if resource is not None else None
    )

    def child_setup() -> None:
        _pin_current_process(cpu_affinity)

    process = subprocess.Popen(
        list(command),
        cwd=str(cwd),
        env=_child_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=(os.name == "posix"),
        preexec_fn=child_setup
        if cpu_affinity is not None and os.name == "posix"
        else None,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=float(timeout_seconds))
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:  # pragma: no cover - exercised on Windows
            process.kill()
        stdout, stderr = process.communicate()
    wall = time.perf_counter() - started
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    usage_after = (
        resource.getrusage(resource.RUSAGE_CHILDREN) if resource is not None else None
    )
    cpu_seconds: float | None = None
    if usage_before is not None and usage_after is not None:
        cpu_seconds = max(
            0.0,
            float(usage_after.ru_utime - usage_before.ru_utime)
            + float(usage_after.ru_stime - usage_before.ru_stime),
        )
    return {
        "command": list(command),
        "exit_code": None if timed_out else int(process.returncode),
        "timed_out": bool(timed_out),
        "supervisor_wall_time_seconds": float(wall),
        "supervisor_cpu_time_seconds": cpu_seconds,
        "stdout_path": str(stdout_path.resolve()),
        "stderr_path": str(stderr_path.resolve()),
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(_json_safe(payload), sort_keys=True, indent=2, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _source_drift_record(
    execution: BenchmarkExecution,
    *,
    expected_source_sha256: str,
    observed_source_sha256: str,
) -> dict[str, Any]:
    record = _base_worker_record(
        execution.to_dict(),
        execution.case.family_id,
        Path(execution.case.instance_path),
    )
    record["source_sha256_expected"] = expected_source_sha256
    return invalidate_for_source_drift(
        record,
        observed_source_sha256=observed_source_sha256,
    )


def _input_drift_record(
    execution: BenchmarkExecution,
    *,
    observed_input_sha256: str | None,
) -> dict[str, Any]:
    record = _base_worker_record(
        execution.to_dict(),
        execution.case.family_id,
        Path(execution.case.instance_path),
    )
    return invalidate_for_input_drift(
        record,
        observed_input_sha256=observed_input_sha256,
    )


def _tool_drift_record(execution: BenchmarkExecution) -> dict[str, Any]:
    record = _base_worker_record(
        execution.to_dict(),
        execution.case.family_id,
        Path(execution.case.instance_path),
    )
    record["tool_snapshot_match"] = tool_snapshot_matches(
        execution.solver.tool_manifest
    )
    record["official_validator_tool_snapshot_match"] = (
        tool_snapshot_matches(execution.case.official_validator_tool_manifest)
        if execution.case.official_validator_command
        else True
    )
    return invalidate_for_tool_drift(record)


def run_benchmark_plan(
    plan: BenchmarkPlan,
    *,
    repo_root: str | Path,
    output_directory: str | Path,
    python_command: str | Path = sys.executable,
) -> dict[str, Any]:
    """Execute a plan sequentially with a fresh, source-checked process per run."""

    root = Path(repo_root).resolve()
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=False)
    expected_source, source_files = source_snapshot(root, plan.source_roots)
    executions = expand_plan(plan)
    resolved_python, python_tool_manifest, python_tool_sha256 = (
        _python_launcher_snapshot(
            python_command,
            base_directory=root,
        )
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "plan": plan.to_dict(),
        "plan_sha256": plan.plan_sha256,
        "repo_root": str(root),
        "source_sha256": expected_source,
        "source_files": source_files,
        "python_command": resolved_python,
        "python_tool_manifest": list(python_tool_manifest),
        "python_tool_snapshot_sha256": python_tool_sha256,
        "child_environment": _child_environment(),
        "child_environment_sha256": sha256_json(_child_environment()),
        "child_environment_policy": (
            "allowlisted host runtime keys plus fixed deterministic solver controls"
        ),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "dependencies": {name: _package_version(name) for name in ("ortools", "lxml")},
        "families": [family.to_dict() for family in BENCHMARK_FAMILIES],
        "execution_count": len(executions),
        "execution_order": [
            {
                "execution_index": row.execution_index,
                "execution_id": row.execution_id,
                "pair_cell_id": row.pair_cell_id,
                "pair_order_position": row.pair_order_position,
                "solver_id": row.solver.solver_id,
            }
            for row in executions
        ],
        "corpus_manifest": (
            plan.corpus_manifest.to_dict() if plan.corpus_manifest else None
        ),
        "corpus_completeness_at_start": bool(
            plan.corpus_manifest is None
            or {
                (row.family_id, row.case_id): row.input_sha256
                for row in plan.corpus_manifest.instances
            }
            == {
                (case.family_id, case.case_id): _observed_file_sha256(
                    case.instance_path
                )
                for case in plan.cases
            }
        ),
        "timing_scopes": {
            "configured_solver_elapsed_seconds": (
                "solver-specific configured scope recorded by configured_solver_time_scope"
            ),
            "worker_wall_time_seconds": "adapter worker excluding Python process startup",
            "supervisor_wall_time_seconds": "complete isolated Python worker process",
            "equal_wall_time_claim_allowed": bool(plan.allow_equal_wall_time_claim),
        },
        "instances": [
            {
                "case_id": case.case_id,
                "path": case.instance_path,
                "sha256_expected": case.input_sha256,
                "sha256_observed": _observed_file_sha256(case.instance_path),
            }
            for case in plan.cases
        ],
    }
    _write_json(output / "manifest.json", manifest)
    records: list[dict[str, Any]] = []
    source_drifted = False
    input_drifted_cases: set[str] = set()
    tool_drifted = False
    for execution in executions:
        current_source, _ = source_snapshot(root, plan.source_roots)
        if source_drifted or current_source != expected_source:
            source_drifted = True
            records.append(
                _source_drift_record(
                    execution,
                    expected_source_sha256=expected_source,
                    observed_source_sha256=current_source,
                )
            )
            continue
        tools_match = tool_snapshot_matches(execution.solver.tool_manifest) and (
            not execution.case.official_validator_command
            or tool_snapshot_matches(execution.case.official_validator_tool_manifest)
        )
        if (
            tool_drifted
            or not tools_match
            or not tool_snapshot_matches(python_tool_manifest)
        ):
            tool_drifted = True
            records.append(_tool_drift_record(execution))
            continue
        current_input = _observed_file_sha256(execution.case.instance_path)
        if (
            execution.case.case_id in input_drifted_cases
            or current_input != execution.case.input_sha256
        ):
            input_drifted_cases.add(execution.case.case_id)
            records.append(
                _input_drift_record(
                    execution,
                    observed_input_sha256=current_input,
                )
            )
            continue
        run_directory = output / "runs" / execution.execution_id
        run_directory.mkdir(parents=True, exist_ok=False)
        request_path = run_directory / "request.json"
        result_path = run_directory / "result.json"
        request = {
            "schema_version": SCHEMA_VERSION,
            "repo_root": str(root),
            "run_directory": str(run_directory),
            "plan_sha256": plan.plan_sha256,
            "expected_source_sha256": expected_source,
            "source_roots": list(plan.source_roots),
            "execution": execution.to_dict(),
        }
        _write_json(request_path, request)
        request_sha256 = sha256_file(request_path)
        process = _run_isolated_process(
            [
                resolved_python,
                "-m",
                "benchmarks.multifamily_harness",
                "worker",
                "--request",
                str(request_path),
                "--result",
                str(result_path),
            ],
            cwd=root,
            timeout_seconds=(
                float(execution.case.time_limit_seconds)
                + float(execution.solver.process_completion_grace_seconds or 0.0)
                + float(plan.supervision_grace_seconds)
            ),
            stdout_path=run_directory / "stdout.log",
            stderr_path=run_directory / "stderr.log",
            cpu_affinity=execution.case.cpu_affinity,
        )
        if process["timed_out"]:
            record = _base_worker_record(
                execution.to_dict(),
                execution.case.family_id,
                Path(execution.case.instance_path),
            )
            record.update(process)
            record["status"] = "SUPERVISOR_TIMEOUT"
        elif process["exit_code"] != 0 or not result_path.is_file():
            record = _base_worker_record(
                execution.to_dict(),
                execution.case.family_id,
                Path(execution.case.instance_path),
            )
            record.update(process)
            record["status"] = "WORKER_PROCESS_ERROR"
        else:
            try:
                record = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                record = _base_worker_record(
                    execution.to_dict(),
                    execution.case.family_id,
                    Path(execution.case.instance_path),
                )
                record["status"] = "WORKER_RESULT_ERROR"
                record["worker_result_error"] = f"{type(exc).__name__}: {exc}"
            record.update(process)
        record["worker_request_path"] = str(request_path)
        record["worker_request_sha256"] = request_sha256
        record["worker_result_path"] = str(result_path)
        record["worker_result_sha256"] = (
            sha256_file(result_path) if result_path.is_file() else None
        )
        record["supervisor_python_path"] = resolved_python
        record["supervisor_python_sha256"] = sha256_file(resolved_python)
        if record.get("config_sha256") != execution.config_sha256:
            record["status"] = "INTEGRITY_ERROR"
            record["effective"] = False
            record["feasible"] = False
            record["score_vector"] = None
            record["score_total"] = None
        if record.get("input_sha256") != execution.case.input_sha256:
            input_drifted_cases.add(execution.case.case_id)
            invalidate_for_input_drift(
                record,
                observed_input_sha256=record.get("input_sha256"),
            )
        after_source, _ = source_snapshot(root, plan.source_roots)
        record["source_sha256_supervisor_after"] = after_source
        if after_source != expected_source:
            source_drifted = True
            invalidate_for_source_drift(
                record,
                observed_source_sha256=after_source,
            )
        after_input = _observed_file_sha256(execution.case.instance_path)
        record["input_sha256_supervisor_after"] = after_input
        if after_input != execution.case.input_sha256:
            input_drifted_cases.add(execution.case.case_id)
            invalidate_for_input_drift(
                record,
                observed_input_sha256=after_input,
            )
        tools_match_after = tool_snapshot_matches(execution.solver.tool_manifest) and (
            not execution.case.official_validator_command
            or tool_snapshot_matches(execution.case.official_validator_tool_manifest)
        )
        if not tools_match_after or not tool_snapshot_matches(python_tool_manifest):
            tool_drifted = True
            record["tool_snapshot_match"] = False
            invalidate_for_tool_drift(record)
        records.append(_json_safe(record))

    results_path = output / "results.jsonl"
    results_path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n"
            for row in records
        ),
        encoding="utf-8",
    )
    summary = summarize_records(
        records,
        minimum_effective_runs_per_condition=(
            plan.minimum_effective_runs_per_condition
        ),
        require_official_validator_agreement=(
            plan.require_official_validator_agreement
        ),
        expected_executions=tuple(execution.to_dict() for execution in executions),
        corpus_manifest=plan.corpus_manifest,
        allow_equal_wall_time_claim=plan.allow_equal_wall_time_claim,
        plan_mode=plan.mode,
    )
    summary["plan_sha256"] = plan.plan_sha256
    summary["source_sha256"] = expected_source
    summary["results_sha256"] = sha256_file(results_path)
    summary["source_drift_detected"] = bool(source_drifted)
    summary["input_drift_detected"] = bool(input_drifted_cases)
    summary["tool_drift_detected"] = bool(tool_drifted)
    _write_json(output / "summary.json", summary)
    return summary


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _finite_scores(rows: Iterable[Mapping[str, Any]]) -> list[float]:
    output: list[float] = []
    for row in rows:
        value = row.get("score_total")
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            output.append(float(value))
    return output


def _comparison_vector(
    family_id: str, row: Mapping[str, Any]
) -> tuple[float, ...] | None:
    expected_lengths = {
        "itc2007-cbctt": 1,
        "itc2007-pe": 2,
        "itc2007-exam": 2,
        "itc2019": 1,
    }
    expected = expected_lengths.get(family_id)
    raw = row.get("score_vector")
    if expected is None or not isinstance(raw, list) or len(raw) != expected:
        return None
    if any(
        type(value) not in {int, float}
        or not math.isfinite(float(value))
        or float(value) < 0.0
        for value in raw
    ):
        return None
    return tuple(float(value) for value in raw)


def _comparison_row_eligible(family_id: str, row: Mapping[str, Any]) -> bool:
    authority = _COMPARISON_AUTHORITY.get(family_id)
    if authority is None:
        return False
    if (
        row.get("effective") is not True
        or row.get("feasible") is not True
        or row.get("score_authority") != authority
        or row.get("configured_solver_budget_compliant") is not True
    ):
        return False
    overrun = row.get("solver_deadline_overrun_seconds")
    if isinstance(overrun, (int, float)) and float(overrun) > _BUDGET_TOLERANCE_SECONDS:
        return False
    solver_model = row.get("solver_model")
    if solver_model == "planora_native":
        if row.get("configured_solver_budget_compliance_basis") != (
            "native_reported_overrun_and_harness_observed_solver_elapsed"
        ):
            return False
        elapsed = row.get("configured_solver_elapsed_seconds")
        limit = row.get("configured_solver_time_limit_seconds")
        if (
            type(elapsed) not in {int, float}
            or type(limit) not in {int, float}
            or not math.isfinite(float(elapsed))
            or not math.isfinite(float(limit))
            or float(elapsed) > float(limit) + _BUDGET_TOLERANCE_SECONDS
        ):
            return False
    elif solver_model == "external_command":
        process = row.get("external_solver_process")
        if (
            row.get("configured_solver_budget_compliance_basis")
            != "required_configured_limit_argv_and_bounded_process_completion"
            or not isinstance(process, Mapping)
            or process.get("timed_out") is not False
            or process.get("exit_code") != 0
        ):
            return False
    else:
        return False
    if family_id == "itc2007-pe":
        if type(row.get("solution_complete")) is not bool:
            return False
    elif row.get("solution_complete") is not True:
        return False
    if authority == SCORE_AUTHORITY_OFFICIAL and (
        row.get("official_validator_agreement") is not True
    ):
        return False
    if authority == SCORE_AUTHORITY_INDEPENDENT and (
        row.get("independent_validator_status") != "completed"
    ):
        return False
    vector = _comparison_vector(family_id, row)
    if vector is None:
        return False
    score_total = row.get("score_total")
    if family_id in {"itc2007-cbctt", "itc2019"}:
        return bool(
            type(score_total) in {int, float}
            and math.isfinite(float(score_total))
            and float(score_total) == vector[0]
        )
    if family_id == "itc2007-exam":
        return bool(
            vector[0] == 0.0
            and type(score_total) in {int, float}
            and math.isfinite(float(score_total))
            and float(score_total) == vector[1]
        )
    if family_id == "itc2007-pe":
        if vector[0] > 0.0:
            return score_total is None
        return bool(
            type(score_total) in {int, float}
            and math.isfinite(float(score_total))
            and float(score_total) == vector[1]
        )
    return False


def _paired_comparison_summary(
    records: Sequence[Mapping[str, Any]],
    *,
    expected_executions: Sequence[Mapping[str, Any]],
    allow_equal_wall_time_claim: bool,
    claim_context_eligible: bool,
) -> dict[str, Any]:
    paired_rows = [
        row
        for row in records
        if row.get("pair_cell_id") is not None
        and row.get("solver_role") in {"planora", "comparator"}
    ]
    cells: dict[str, list[Mapping[str, Any]]] = {}
    for row in paired_rows:
        cells.setdefault(str(row["pair_cell_id"]), []).append(row)

    expected_by_cell: dict[str, set[str]] = {}
    expected_timing_by_cell: dict[
        str, dict[str, tuple[str, str, str, float, float]]
    ] = {}
    for execution in expected_executions:
        config = dict(execution.get("config") or {})
        solver = dict(config.get("solver") or {})
        solver_id = str(solver.get("solver_id", "planora"))
        cell_id = str(execution.get("pair_cell_id", execution.get("execution_id")))
        expected_by_cell.setdefault(cell_id, set()).add(solver_id)
        expected_timing_by_cell.setdefault(cell_id, {})[solver_id] = (
            str(solver.get("model")),
            str(solver.get("role")),
            str(solver.get("timing_scope")),
            float(config.get("time_limit_seconds", -1.0)),
            float(solver.get("process_completion_grace_seconds", -1.0)),
        )
    expected_paired = {
        cell_id: solver_ids
        for cell_id, solver_ids in expected_by_cell.items()
        if len(solver_ids) > 1
    }

    per_cell: dict[str, dict[str, Any]] = {}
    by_instance_seed: dict[str, dict[str, Any]] = {}
    by_family: dict[str, dict[str, Any]] = {}
    complete = True
    authority_ok = True
    timing_scope_matched = True
    comparative_cells = 0
    eligible_cells = 0
    native_only_cells = 0
    cell_ids = sorted(set(cells).union(expected_paired))
    for cell_id in cell_ids:
        rows = cells.get(cell_id, [])
        expected_solver_ids = expected_paired.get(cell_id)
        if expected_solver_ids is None:
            # A single-solver smoke execution is not a paired comparison cell.
            if len({str(row.get("solver_id", "planora")) for row in rows}) < 2:
                continue
            expected_solver_ids = {str(row.get("solver_id", "planora")) for row in rows}
        by_solver: dict[str, list[Mapping[str, Any]]] = {}
        for row in rows:
            by_solver.setdefault(str(row.get("solver_id", "planora")), []).append(row)
        cell_complete = set(by_solver) == expected_solver_ids and all(
            len(by_solver[solver_id]) == 1 for solver_id in expected_solver_ids
        )
        if not cell_complete:
            complete = False
            per_cell[cell_id] = {
                "status": "incomplete",
                "expected_solver_ids": sorted(expected_solver_ids),
                "observed_solver_counts": {
                    solver_id: len(group)
                    for solver_id, group in sorted(by_solver.items())
                },
            }
            continue
        selected = [
            by_solver[solver_id][0] for solver_id in sorted(expected_solver_ids)
        ]
        roles = {str(row.get("solver_role")): row for row in selected}
        if set(roles) != {"planora", "comparator"}:
            complete = False
            per_cell[cell_id] = {"status": "invalid_roles"}
            continue
        planora = roles["planora"]
        comparator = roles["comparator"]
        family_id = str(planora["family_id"])
        if family_id != str(comparator["family_id"]):
            complete = False
            per_cell[cell_id] = {"status": "family_mismatch"}
            continue
        required_authority = _COMPARISON_AUTHORITY.get(family_id)
        common = {
            "family_id": family_id,
            "case_id": str(planora["case_id"]),
            "seed": int(planora.get("seed", 0)),
            "repetition": int(planora.get("repetition", 1)),
            "planora_solver_id": str(planora.get("solver_id")),
            "comparator_solver_id": str(comparator.get("solver_id")),
            "required_score_authority": required_authority,
        }
        expected_timing = expected_timing_by_cell.get(cell_id, {})
        expected_timing_values = tuple(expected_timing.values())
        model_roles = {(value[0], value[1]) for value in expected_timing_values}
        scopes = {value[2] for value in expected_timing_values}
        time_limits = {value[3] for value in expected_timing_values}
        completion_graces = {value[4] for value in expected_timing_values}
        supported_process_models = all(
            (model == "planora_native" and role == "planora")
            or (model == "external_command" and role == "comparator")
            for model, role in model_roles
        )
        matched_timing = (
            claim_context_eligible
            and set(expected_timing) == expected_solver_ids
            and len(expected_timing_values) == 2
            and supported_process_models
            and scopes == {"whole_solver_process_wall"}
            and len(time_limits) == 1
            and time_limits != {-1.0}
            and {model for model, _role in model_roles} == {"external_command"}
            and completion_graces == {0.0}
        )
        timing_scope_matched = timing_scope_matched and matched_timing
        common["timing_scope_matched"] = matched_timing
        common["equal_wall_time_claim_permitted"] = bool(
            claim_context_eligible and allow_equal_wall_time_claim and matched_timing
        )
        if required_authority is None:
            native_only_cells += 1
            per_cell[cell_id] = {
                **common,
                "status": "native_only_no_superiority_claim",
                "outcome": None,
            }
            continue
        comparative_cells += 1
        if not _comparison_row_eligible(family_id, planora) or not (
            _comparison_row_eligible(family_id, comparator)
        ):
            authority_ok = False
            per_cell[cell_id] = {
                **common,
                "status": "authority_or_score_ineligible",
                "outcome": None,
            }
            continue
        planora_vector = _comparison_vector(family_id, planora)
        comparator_vector = _comparison_vector(family_id, comparator)
        assert planora_vector is not None and comparator_vector is not None
        if planora_vector < comparator_vector:
            outcome = "win"
        elif planora_vector > comparator_vector:
            outcome = "loss"
        else:
            outcome = "tie"
        eligible_cells += 1
        per_cell[cell_id] = {
            **common,
            "status": "compared",
            "outcome": outcome,
            "planora_score_vector": list(planora_vector),
            "comparator_score_vector": list(comparator_vector),
        }
        instance_seed_key = (
            f"{family_id}::{planora['case_id']}::seed-{int(planora.get('seed', 0))}"
        )
        bucket = by_instance_seed.setdefault(
            instance_seed_key,
            {
                "family_id": family_id,
                "case_id": str(planora["case_id"]),
                "seed": int(planora.get("seed", 0)),
                "wins": 0,
                "ties": 0,
                "losses": 0,
                "compared_repetitions": 0,
            },
        )
        outcome_key = {"win": "wins", "tie": "ties", "loss": "losses"}[outcome]
        bucket[outcome_key] += 1
        bucket["compared_repetitions"] += 1
        family_bucket = by_family.setdefault(
            family_id,
            {
                "wins": 0,
                "ties": 0,
                "losses": 0,
                "compared_cells": 0,
                "required_score_authority": required_authority,
            },
        )
        family_bucket[outcome_key] += 1
        family_bucket["compared_cells"] += 1

    expected_pair_cell_count = len(expected_paired)
    paired_complete = bool(
        complete
        and (
            not expected_paired
            or len(
                [row for row in per_cell.values() if row.get("status") != "incomplete"]
            )
            >= expected_pair_cell_count
        )
    )
    superiority_ready = bool(
        claim_context_eligible
        and comparative_cells > 0
        and eligible_cells == comparative_cells
        and paired_complete
        and authority_ok
    )
    return {
        "expected_pair_cell_count": expected_pair_cell_count,
        "observed_pair_cell_count": len(per_cell),
        "paired_cells_complete": paired_complete,
        "comparative_cell_count": comparative_cells,
        "eligible_comparative_cell_count": eligible_cells,
        "native_only_cell_count": native_only_cells,
        "score_authority_enforced": authority_ok,
        "timing_scope_matched_for_equal_wall_claim": bool(
            comparative_cells > 0 and timing_scope_matched
        ),
        "equal_wall_time_claim_permitted": bool(
            comparative_cells > 0
            and claim_context_eligible
            and allow_equal_wall_time_claim
            and timing_scope_matched
        ),
        "superiority_claim_ready": superiority_ready,
        "claim_context_eligible": bool(claim_context_eligible),
        "by_instance_seed": by_instance_seed,
        "by_family": by_family,
        "cells": per_cell,
        "comparison_rule": (
            "Planora win/tie/loss uses the family-standard lower-is-better "
            "lexicographic score vector. Native-only lanes emit no superiority outcome."
        ),
    }


def summarize_records(
    records: Sequence[Mapping[str, Any]],
    *,
    minimum_effective_runs_per_condition: int,
    require_official_validator_agreement: bool = False,
    expected_executions: Sequence[Mapping[str, Any]] = (),
    corpus_manifest: CorpusManifestSpec | None = None,
    allow_equal_wall_time_claim: bool = False,
    plan_mode: str = "smoke",
) -> dict[str, Any]:
    """Aggregate honestly comparable evidence without mixing score families."""

    if minimum_effective_runs_per_condition < 1:
        raise ValueError("minimum_effective_runs_per_condition must be positive")
    if plan_mode not in PLAN_MODES:
        raise ValueError(f"plan_mode must be one of {sorted(PLAN_MODES)}")
    required_effective_runs = max(
        int(minimum_effective_runs_per_condition),
        6 if plan_mode == "replicated" else 1,
    )
    condition_rows: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        condition_rows.setdefault(str(record["condition_id"]), []).append(record)

    conditions: dict[str, dict[str, Any]] = {}
    for condition_id, rows in sorted(condition_rows.items()):
        effective = [row for row in rows if row.get("effective") is True]
        feasible = [row for row in effective if row.get("feasible") is True]
        scores = _finite_scores(feasible)
        vectors = [
            list(row["score_vector"])
            for row in feasible
            if isinstance(row.get("score_vector"), list)
        ]
        configured = [
            row for row in rows if row.get("official_validator_configured") is True
        ]
        agreements = [
            row for row in configured if row.get("official_validator_agreement") is True
        ]
        family_has_official = get_benchmark_family(
            str(rows[0]["family_id"])
        ).official_validator_available
        official_required = bool(
            require_official_validator_agreement and family_has_official
        )
        configured_agreement_complete = bool(
            not configured or len(agreements) == len(configured)
        )
        official_requirement_met = (
            bool(len(configured) == len(rows) and len(agreements) == len(rows))
            if official_required
            else configured_agreement_complete
        )
        conditions[condition_id] = {
            "family_id": str(rows[0]["family_id"]),
            "case_id": str(rows[0]["case_id"]),
            "runs": len(rows),
            "effective_runs": len(effective),
            "effective_target": required_effective_runs,
            "effective_target_met": len(effective) >= required_effective_runs,
            "feasible_runs": len(feasible),
            "feasibility_rate_over_effective": (
                float(len(feasible) / len(effective)) if effective else None
            ),
            "statuses": dict(Counter(str(row.get("status")) for row in rows)),
            "score_authorities": dict(
                Counter(str(row.get("score_authority")) for row in effective)
            ),
            "best_score_vector": min(vectors) if vectors else None,
            "score_total_min": min(scores) if scores else None,
            "score_total_median": (
                float(statistics.median(scores)) if scores else None
            ),
            "score_total_mean": (float(statistics.fmean(scores)) if scores else None),
            "official_validator_configured_runs": len(configured),
            "official_validator_agreement_runs": len(agreements),
            "official_validator_agreement_complete": (
                len(agreements) == len(configured) if configured else None
            ),
            "official_validator_required": official_required,
            "official_validator_requirement_met": official_requirement_met,
            "source_drift_runs": sum(
                row.get("source_snapshot_match") is False for row in rows
            ),
            "input_drift_runs": sum(
                row.get("input_snapshot_match") is False for row in rows
            ),
        }

    expected_solver_condition_counts = Counter(
        (
            str(row.get("condition_id")),
            str(
                dict(row.get("config") or {})
                .get("solver", {})
                .get("solver_id", "planora")
            ),
        )
        for row in expected_executions
    )
    expected_solver_condition_design: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for row in expected_executions:
        config = dict(row.get("config") or {})
        solver = dict(config.get("solver") or {})
        expected_solver_condition_design.setdefault(
            (
                str(row.get("condition_id")),
                str(solver.get("solver_id", "planora")),
            ),
            [],
        ).append(
            (
                int(config.get("seed", -1)),
                int(config.get("repetition", -1)),
            )
        )
    replicated_design_complete = bool(
        plan_mode != "replicated"
        or (
            expected_solver_condition_design
            and all(
                len(seed_repetitions) >= 6
                and len(set(seed_repetitions)) == len(seed_repetitions)
                and len({seed for seed, _repetition in seed_repetitions}) >= 3
                and all(
                    len(
                        {
                            repetition
                            for observed_seed, repetition in seed_repetitions
                            if observed_seed == seed
                        }
                    )
                    >= 2
                    for seed in {seed for seed, _repetition in seed_repetitions}
                )
                for seed_repetitions in expected_solver_condition_design.values()
            )
        )
    )
    solver_condition_rows: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for record in records:
        solver_condition_rows.setdefault(
            (
                str(record["condition_id"]),
                str(record.get("solver_id", "planora")),
            ),
            [],
        ).append(record)
    solver_conditions: dict[str, dict[str, Any]] = {}
    for (condition_id, solver_id), rows in sorted(solver_condition_rows.items()):
        effective = [row for row in rows if row.get("effective") is True]
        expected_run_count = expected_solver_condition_counts.get(
            (condition_id, solver_id)
        )
        effective_target = max(
            required_effective_runs,
            int(expected_run_count or 0),
        )
        expected_count_met = bool(
            expected_run_count is None or len(effective) == expected_run_count
        )
        solver_conditions[f"{condition_id}::{solver_id}"] = {
            "condition_id": condition_id,
            "solver_id": solver_id,
            "solver_model": str(rows[0].get("solver_model", "planora_native")),
            "runs": len(rows),
            "expected_runs": expected_run_count,
            "effective_runs": len(effective),
            "effective_target": effective_target,
            "effective_target_met": bool(
                len(effective) >= effective_target
                and expected_count_met
                and replicated_design_complete
            ),
        }

    families: dict[str, dict[str, Any]] = {}
    for family_id in sorted({str(row["family_id"]) for row in records}):
        rows = [row for row in records if str(row["family_id"]) == family_id]
        effective = [row for row in rows if row.get("effective") is True]
        feasible = [row for row in effective if row.get("feasible") is True]
        families[family_id] = {
            "runs": len(rows),
            "effective_runs": len(effective),
            "feasible_runs": len(feasible),
            "score_authorities": dict(
                Counter(str(row.get("score_authority")) for row in effective)
            ),
            "condition_count": len({str(row["condition_id"]) for row in rows}),
        }

    target_met = bool(solver_conditions) and all(
        item["effective_target_met"] for item in solver_conditions.values()
    )
    official_agreement_ok = all(
        item["official_validator_requirement_met"] is True
        for item in conditions.values()
    )
    if expected_executions:
        source_clean = all(row.get("source_snapshot_match") is True for row in records)
        inputs_clean = all(row.get("input_snapshot_match") is True for row in records)
        tools_clean = all(
            row.get("tool_snapshot_match") is True
            and row.get("official_validator_tool_snapshot_match") is True
            for row in records
        )
    else:
        source_clean = all(
            row.get("source_snapshot_match") is not False for row in records
        )
        inputs_clean = all(
            row.get("input_snapshot_match") is not False for row in records
        )
        tools_clean = all(
            row.get("tool_snapshot_match") is not False
            and row.get("official_validator_tool_snapshot_match") is not False
            for row in records
        )

    def expected_identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
        config = dict(row.get("config") or {})
        solver = dict(config.get("solver") or {})
        return (
            str(row.get("execution_id")),
            str(row.get("condition_id")),
            str(row.get("config_sha256")),
            str(row.get("input_sha256")),
            str(config.get("family_id")),
            str(config.get("case_id")),
            int(config.get("seed", -1)),
            int(config.get("repetition", -1)),
            str(solver.get("solver_id", "planora")),
            str(solver.get("model", "planora_native")),
            str(solver.get("role", "planora")),
            str(solver.get("command_sha256")),
            str(solver.get("tool_snapshot_sha256")),
            str(solver.get("evidence_classification", "source_frozen_native")),
            str(config.get("official_validator_tool_snapshot_sha256")),
            str(
                config.get(
                    "official_validator_evidence_classification", "not_configured"
                )
            ),
            str(solver.get("timing_scope")),
            float(config.get("time_limit_seconds", -1.0)),
            str(row.get("pair_cell_id")),
            int(row.get("pair_order_position", -1)),
        )

    def observed_identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            str(row.get("execution_id")),
            str(row.get("condition_id")),
            str(row.get("config_sha256")),
            str(row.get("input_sha256")),
            str(row.get("family_id")),
            str(row.get("case_id")),
            int(row.get("seed", -1)),
            int(row.get("repetition", -1)),
            str(row.get("solver_id", "planora")),
            str(row.get("solver_model", "planora_native")),
            str(row.get("solver_role", "planora")),
            str(row.get("solver_command_sha256")),
            str(row.get("solver_tool_snapshot_sha256")),
            str(row.get("evidence_classification")),
            str(row.get("official_validator_tool_snapshot_sha256")),
            str(
                row.get("official_validator_evidence_classification", "not_configured")
            ),
            str(row.get("configured_solver_time_scope")),
            float(row.get("configured_solver_time_limit_seconds", -1.0)),
            str(row.get("pair_cell_id")),
            int(row.get("pair_order_position", -1)),
        )

    expected_identities = [expected_identity(row) for row in expected_executions]
    observed_identities = [observed_identity(row) for row in records]
    expected_configs_self_consistent = bool(
        expected_executions
        and all(
            sha256_json(dict(row.get("config") or {})) == str(row.get("config_sha256"))
            for row in expected_executions
        )
    )
    execution_identity_exact = bool(
        expected_executions
        and expected_configs_self_consistent
        and len({row[0] for row in expected_identities}) == len(expected_identities)
        and Counter(expected_identities) == Counter(observed_identities)
    )
    execution_cells_exact = bool(
        execution_identity_exact
        and all(row.get("effective") is True for row in records)
    )
    corpus_complete = True
    if corpus_manifest is not None:
        expected_corpus = {
            (row.family_id, row.case_id): row.input_sha256
            for row in corpus_manifest.instances
        }
        observed_corpus = {
            (str(row["family_id"]), str(row["case_id"])): str(
                row.get("input_sha256_expected", row.get("input_sha256"))
            )
            for row in records
        }
        corpus_complete = expected_corpus == observed_corpus
    expected_case_solvers: dict[tuple[str, str], set[str]] = {}
    for execution in expected_executions:
        config = dict(execution.get("config") or {})
        solver = dict(config.get("solver") or {})
        expected_case_solvers.setdefault(
            (str(config.get("family_id")), str(config.get("case_id"))), set()
        ).add(str(solver.get("solver_id", "planora")))
    comparison_requested = any(
        family_id in _COMPARISON_AUTHORITY and len(solver_ids) > 1
        for (family_id, _case_id), solver_ids in expected_case_solvers.items()
    )
    paired_comparable_corpus_coverage_complete = bool(
        not comparison_requested
        or (
            corpus_manifest is not None
            and all(
                row.family_id not in _COMPARISON_AUTHORITY
                or len(expected_case_solvers.get((row.family_id, row.case_id), set()))
                == 2
                for row in corpus_manifest.instances
            )
        )
    )
    expected_tool_identity_by_execution_id: dict[str, tuple[str, ...]] = {}
    for execution in expected_executions:
        config = dict(execution.get("config") or {})
        solver = dict(config.get("solver") or {})
        expected_tool_identity_by_execution_id[str(execution.get("execution_id"))] = (
            str(solver.get("command_sha256")),
            str(solver.get("tool_snapshot_sha256")),
            str(solver.get("evidence_classification", "source_frozen_native")),
            str(config.get("official_validator_tool_snapshot_sha256")),
            str(
                config.get(
                    "official_validator_evidence_classification", "not_configured"
                )
            ),
        )
    tool_identity_mismatch_present = (
        any(
            expected_tool_identity_by_execution_id.get(str(row.get("execution_id")))
            != (
                str(row.get("solver_command_sha256")),
                str(row.get("solver_tool_snapshot_sha256")),
                str(row.get("evidence_classification")),
                str(row.get("official_validator_tool_snapshot_sha256")),
                str(
                    row.get(
                        "official_validator_evidence_classification", "not_configured"
                    )
                ),
            )
            for row in records
        )
        if expected_executions
        else False
    )

    def expected_uses_external_tooling(execution: Mapping[str, Any]) -> bool:
        config = dict(execution.get("config") or {})
        solver = dict(config.get("solver") or {})
        native_solver_exact = bool(
            solver.get("model") == "planora_native"
            and solver.get("role") == "planora"
            and not solver.get("command")
            and not solver.get("declared_tool_artifacts")
            and not solver.get("tool_manifest")
            and solver.get("command_sha256") == sha256_json([])
            and solver.get("tool_snapshot_sha256")
            == sha256_json({"model": "planora_native", "source_frozen": True})
            and solver.get("evidence_classification", "source_frozen_native")
            == "source_frozen_native"
        )
        return bool(
            not native_solver_exact
            or config.get("official_validator_command")
            or config.get("official_validator_tool_manifest")
            or config.get("official_validator_tool_snapshot_sha256")
            or config.get("official_validator_evidence_classification")
            == "diagnostic_unverified"
        )

    def observed_uses_external_tooling(row: Mapping[str, Any]) -> bool:
        solver_result = dict(row.get("solver_result") or {})
        validator_status = row.get("official_validator_status")
        return bool(
            row.get("solver_model") == "external_command"
            or row.get("solver_role") == "comparator"
            or row.get("evidence_classification") != "source_frozen_native"
            or row.get("score_authority") == SCORE_AUTHORITY_OFFICIAL
            or row.get("external_solver_process") is not None
            or row.get("external_process_timeout_seconds") is not None
            or row.get("external_process_wall_time_seconds") is not None
            or solver_result.get("model") == "external_command"
            or row.get("configured_solver_budget_compliance_basis")
            == "required_configured_limit_argv_and_bounded_process_completion"
            or row.get("official_validator_configured") is True
            or row.get("official_validator_command")
            or row.get("official_validator_tool_manifest")
            or row.get("official_validator_tool_snapshot_sha256")
            or "official_validator_error" in row
            or "official_validator_validation" in row
            or "official_validation" in row
            or row.get("official_validator_agreement") is not None
            or validator_status
            not in {None, "not_available", "not_configured", "not_run"}
        )

    expected_external_tooling = any(
        expected_uses_external_tooling(execution) for execution in expected_executions
    )
    observed_external_tooling = any(
        observed_uses_external_tooling(row) for row in records
    )
    external_tooling_present = bool(
        expected_external_tooling
        or observed_external_tooling
        or tool_identity_mismatch_present
    )
    claim_grade_tooling = not external_tooling_present
    expected_native_timing_by_execution_id: dict[str, tuple[float, str]] = {}
    for execution in expected_executions:
        config = dict(execution.get("config") or {})
        solver = dict(config.get("solver") or {})
        if solver.get("model") == "planora_native":
            expected_native_timing_by_execution_id[
                str(execution.get("execution_id"))
            ] = (
                float(config.get("time_limit_seconds", math.nan)),
                str(solver.get("timing_scope")),
            )

    def native_timing_row_compliant(row: Mapping[str, Any]) -> bool:
        expected = expected_native_timing_by_execution_id.get(
            str(row.get("execution_id"))
        )
        if expected is None:
            return False
        expected_limit, expected_scope = expected
        elapsed = row.get("configured_solver_elapsed_seconds")
        observed_limit = row.get("configured_solver_time_limit_seconds")
        overrun = row.get("solver_deadline_overrun_seconds")
        tolerance = row.get("configured_solver_budget_tolerance_seconds")
        numeric_values = (elapsed, observed_limit, overrun, tolerance)
        if any(
            type(value) not in {int, float} or not math.isfinite(float(value))
            for value in numeric_values
        ):
            return False
        return bool(
            row.get("solver_model") == "planora_native"
            and row.get("status") == "COMPLETED"
            and row.get("configured_solver_budget_compliant") is True
            and row.get("configured_solver_budget_compliance_basis")
            == "native_reported_overrun_and_harness_observed_solver_elapsed"
            and expected_scope == "configured_solver_call"
            and row.get("configured_solver_time_scope") == expected_scope
            and math.isfinite(expected_limit)
            and expected_limit > 0.0
            and abs(float(observed_limit) - expected_limit) <= _BUDGET_TOLERANCE_SECONDS
            and float(elapsed) >= 0.0
            and float(elapsed) <= expected_limit + _BUDGET_TOLERANCE_SECONDS
            and float(overrun) >= 0.0
            and float(overrun) <= _BUDGET_TOLERANCE_SECONDS
            and float(tolerance) == _BUDGET_TOLERANCE_SECONDS
            and row.get("timed_out") is False
            and row.get("exit_code") == 0
            and "worker_result_error" not in row
        )

    native_timing_budget_compliant = bool(
        expected_native_timing_by_execution_id
        and len(expected_native_timing_by_execution_id) == len(expected_executions)
        and len(records) == len(expected_executions)
        and all(native_timing_row_compliant(row) for row in records)
    )
    expected_input_by_execution_id = {
        str(execution.get("execution_id")): str(execution.get("input_sha256"))
        for execution in expected_executions
    }
    expected_execution_by_id = {
        str(execution.get("execution_id")): execution
        for execution in expected_executions
    }
    native_score_vector_lengths = {
        "itc2007-cbctt": 1,
        "itc2007-pe": 2,
        "itc2007-exam": 2,
        "cbctt-extended": 2,
        "itc2019": 1,
        "unitime-native": 2,
        "xhstt": 2,
    }

    def finite_json_numbers(value: Any) -> bool:
        if isinstance(value, float):
            return math.isfinite(value)
        if isinstance(value, Mapping):
            return all(finite_json_numbers(item) for item in value.values())
        if isinstance(value, (list, tuple)):
            return all(finite_json_numbers(item) for item in value)
        return value is None or isinstance(value, (str, int, bool))

    def standardized_json_numbers_are_integers(value: Any) -> bool:
        if isinstance(value, bool):
            return True
        if isinstance(value, float):
            return False
        if isinstance(value, Mapping):
            return all(
                standardized_json_numbers_are_integers(item) for item in value.values()
            )
        if isinstance(value, (list, tuple)):
            return all(standardized_json_numbers_are_integers(item) for item in value)
        return value is None or isinstance(value, (str, int))

    def native_result_row_integrity(row: Mapping[str, Any]) -> bool:
        execution_id = str(row.get("execution_id"))
        expected_input = expected_input_by_execution_id.get(execution_id)
        family_id = str(row.get("family_id"))
        expected_vector_length = native_score_vector_lengths.get(family_id)
        vector = row.get("score_vector")
        score_total = row.get("score_total")
        components = row.get("score_components")
        validation = row.get("independent_validation")
        standardized_integer_family = family_id != "unitime-native"

        def nonempty_error_signal(value: Any) -> bool:
            if isinstance(value, Mapping):
                return any(
                    (
                        bool(
                            re.search(
                                r"error|exception|traceback|failure", str(key), re.I
                            )
                        )
                        and nonempty_error_signal(item)
                    )
                    or nonempty_error_signal(item)
                    for key, item in value.items()
                )
            if isinstance(value, (list, tuple, set, frozenset)):
                return any(nonempty_error_signal(item) for item in value)
            return value not in (None, False, "", 0)

        def has_error_signal(payload: Mapping[str, Any]) -> bool:
            for key, value in payload.items():
                if re.search(r"error|exception|traceback|failure", str(key), re.I):
                    if nonempty_error_signal(value):
                        return True
                elif isinstance(value, (Mapping, list, tuple)) and has_error_signal_in(
                    value
                ):
                    return True
            return False

        def has_error_signal_in(value: Any) -> bool:
            if isinstance(value, Mapping):
                return has_error_signal(value)
            if isinstance(value, (list, tuple)):
                return any(has_error_signal_in(item) for item in value)
            return False

        def supervisor_command_is_expected(value: Any) -> bool:
            expected_execution = expected_execution_by_id.get(execution_id)
            if expected_execution is None:
                return False
            candidate = dict(row)
            candidate["command"] = value
            try:
                _native_run_artifact_paths(expected_execution, candidate)
            except (KeyError, OSError, TypeError, ValueError):
                return False
            return True

        def has_unexpected_nested_command(value: Any, *, root: bool = False) -> bool:
            if isinstance(value, Mapping):
                for key, item in value.items():
                    normalized_key = str(key).strip().lower()
                    if normalized_key in {"command", "supervisor_command"}:
                        if root and normalized_key == "command":
                            if not supervisor_command_is_expected(item):
                                return True
                        elif item not in (None, (), [], ""):
                            return True
                    elif has_unexpected_nested_command(item):
                        return True
                return False
            if isinstance(value, (list, tuple)):
                return any(has_unexpected_nested_command(item) for item in value)
            return False

        if (
            expected_input is None
            or not re.fullmatch(r"[0-9a-f]{64}", expected_input)
            or expected_vector_length is None
            or not isinstance(vector, list)
            or len(vector) != expected_vector_length
            or any(
                isinstance(value, bool)
                or type(value) not in {int, float}
                or not math.isfinite(float(value))
                or (
                    float(value) < 0.0
                    and not (family_id == "unitime-native" and index == 1)
                )
                or (standardized_integer_family and type(value) is not int)
                for index, value in enumerate(vector)
            )
            or not isinstance(components, Mapping)
            or not components
            or not finite_json_numbers(components)
            or (
                standardized_integer_family
                and not standardized_json_numbers_are_integers(components)
            )
            or not isinstance(validation, Mapping)
            or not validation
            or validation.get("feasible") is not True
            or validation.get("errors", []) not in ([], ())
            or bool(validation.get("unsupported_features"))
            or has_error_signal(row)
            or not supervisor_command_is_expected(row.get("command"))
            or row.get("supervisor_command") not in (None, (), [])
            or has_unexpected_nested_command(row, root=True)
        ):
            return False
        partial_pe = bool(family_id == "itc2007-pe" and float(vector[0]) > 0.0)
        if partial_pe:
            if row.get("solution_complete") is not False or score_total is not None:
                return False
        elif (
            isinstance(score_total, bool)
            or type(score_total) not in {int, float}
            or (standardized_integer_family and type(score_total) is not int)
            or not math.isfinite(float(score_total))
            or (float(score_total) < 0.0 and family_id != "unitime-native")
            or _canonical_json_bytes(vector[-1]) != _canonical_json_bytes(score_total)
            or (len(vector) > 1 and float(vector[0]) != 0.0)
            or row.get("solution_complete") is not True
        ):
            return False
        score_agrees = False
        if family_id == "itc2007-pe":
            validation_score = dict(validation.get("score") or {})
            score_agrees = bool(
                validation_score.get("lexicographic") == vector
                and _canonical_json_bytes(dict(components))
                == _canonical_json_bytes(validation_score)
            )
        elif family_id == "itc2007-exam":
            hard = dict(validation.get("hard") or {})
            objective = dict(validation.get("objective") or {})
            score_agrees = bool(
                [hard.get("total"), objective.get("total")] == vector
                and _canonical_json_bytes(dict(components))
                == _canonical_json_bytes(dict(validation))
            )
        elif family_id == "cbctt-extended":
            validation_score = dict(validation.get("score") or {})
            score_agrees = bool(
                [
                    validation.get("hard_violations"),
                    validation_score.get("total"),
                ]
                == vector
                and _canonical_json_bytes(dict(components))
                == _canonical_json_bytes(validation_score)
            )
        elif family_id == "itc2019":
            objective_keys = {
                "time",
                "room",
                "distribution",
                "student",
                "weighted_time",
                "weighted_room",
                "weighted_distribution",
                "weighted_student",
                "total",
            }
            score_agrees = bool(
                set(components) == objective_keys
                and components.get("total") == vector[0]
                and components.get("total")
                == sum(
                    int(components[key])
                    for key in (
                        "weighted_time",
                        "weighted_room",
                        "weighted_distribution",
                        "weighted_student",
                    )
                )
            )
        elif family_id == "unitime-native":
            validation_score = dict(validation.get("score") or {})
            score_agrees = bool(
                type(vector[0]) is int
                and [
                    validation_score.get("hard_violations"),
                    validation_score.get("native_total"),
                ]
                == vector
                and _canonical_json_bytes(validation_score.get("native_total"))
                == _canonical_json_bytes(vector[1])
                and validation_score.get("scheme") == "planora-unitime-native-v1"
                and _canonical_json_bytes(dict(components))
                == _canonical_json_bytes(validation_score)
            )
        elif family_id == "xhstt":
            validation_score = dict(validation.get("score") or {})
            score_agrees = bool(
                validation_score.get("lexicographic") == vector
                and _canonical_json_bytes(dict(components))
                == _canonical_json_bytes(validation_score)
            )
        if not score_agrees:
            return False
        expected_authority = _score_authority(family_id, None)
        if row.get("score_authority") != expected_authority:
            return False
        if any(
            key in row
            for key in (
                "adapter_error",
                "error",
                "official_validator_error",
                "result_error",
                "solver_error",
                "worker_result_error",
            )
        ):
            return False
        if (
            row.get("status") != "COMPLETED"
            or row.get("effective") is not True
            or row.get("feasible") is not True
            or row.get("independent_validator_status") != "completed"
            or isinstance(row.get("worker_pid"), bool)
            or type(row.get("worker_pid")) is not int
            or int(row["worker_pid"]) <= 0
        ):
            return False
        output_sha256 = row.get("output_sha256")
        output_path_raw = row.get("output_path")
        if (
            not isinstance(output_path_raw, str)
            or not Path(output_path_raw).is_absolute()
            or not isinstance(output_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", output_sha256)
        ):
            return False
        output_path = Path(output_path_raw)
        try:
            output_mode = output_path.lstat().st_mode
            if (
                output_path.is_symlink()
                or not stat.S_ISREG(output_mode)
                or sha256_file(output_path) != output_sha256
            ):
                return False
        except OSError:
            return False
        input_hashes = (
            row.get("input_sha256"),
            row.get("input_sha256_expected"),
            row.get("input_sha256_worker_start"),
            row.get("input_sha256_worker_end"),
            row.get("input_sha256_supervisor_after"),
        )
        if any(value != expected_input for value in input_hashes):
            return False
        source_hashes = (
            row.get("source_sha256_expected"),
            row.get("source_sha256_worker_start"),
            row.get("source_sha256_worker_end"),
            row.get("source_sha256_supervisor_after"),
        )
        if (
            any(
                not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                for value in source_hashes
            )
            or len(set(source_hashes)) != 1
        ):
            return False
        solve_wall = row.get("solve_wall_time_seconds")
        configured_elapsed = row.get("configured_solver_elapsed_seconds")
        worker_wall = row.get("worker_wall_time_seconds")
        supervisor_wall = row.get("supervisor_wall_time_seconds")
        walls = (solve_wall, configured_elapsed, worker_wall, supervisor_wall)
        if any(
            type(value) not in {int, float}
            or not math.isfinite(float(value))
            or float(value) < 0.0
            for value in walls
        ):
            return False
        return bool(
            abs(float(configured_elapsed) - float(solve_wall))
            <= _BUDGET_TOLERANCE_SECONDS
            and float(solve_wall) <= float(worker_wall) + _BUDGET_TOLERANCE_SECONDS
            and float(worker_wall) <= float(supervisor_wall) + _BUDGET_TOLERANCE_SECONDS
        )

    artifact_revalidation_rows: list[dict[str, Any]] = []
    native_source_snapshot_cache: dict[tuple[str, tuple[str, ...]], str] = {}
    native_artifact_derivation_cache: dict[
        tuple[str, str, str, str], dict[str, Any]
    ] = {}
    for row in records:
        execution_id = str(row.get("execution_id"))
        expected_execution = expected_execution_by_id.get(execution_id)
        if expected_execution is None:
            result = _revalidation_failure("unexpected_execution_id")
        else:
            result = _revalidate_native_artifact(
                expected_execution,
                row,
                source_cache=native_source_snapshot_cache,
                derivation_cache=native_artifact_derivation_cache,
            )
        artifact_revalidation_rows.append({"execution_id": execution_id, **result})

    output_path_counts = Counter(
        str(result["output_path"])
        for result in artifact_revalidation_rows
        if result["status"] == "passed"
    )
    output_identity_counts = Counter(
        tuple(result["output_identity"])
        for result in artifact_revalidation_rows
        if result["status"] == "passed"
    )
    for result in artifact_revalidation_rows:
        if result["status"] != "passed":
            continue
        if output_path_counts[str(result["output_path"])] != 1:
            result.update(status="failed", reason="duplicate_output_path")
        elif output_identity_counts[tuple(result["output_identity"])] != 1:
            result.update(status="failed", reason="duplicate_output_inode")

    native_artifact_revalidation_complete = bool(
        expected_executions
        and len(artifact_revalidation_rows) == len(expected_executions)
        and all(result["status"] == "passed" for result in artifact_revalidation_rows)
    )
    native_result_integrity_complete = bool(
        expected_executions
        and len(records) == len(expected_executions)
        and native_timing_budget_compliant
        and all(native_result_row_integrity(row) for row in records)
        and native_artifact_revalidation_complete
    )
    claim_context_eligible = bool(
        plan_mode == "replicated"
        and claim_grade_tooling
        and native_timing_budget_compliant
        and native_result_integrity_complete
        and replicated_design_complete
        and corpus_manifest is not None
        and corpus_complete
        and execution_identity_exact
        and target_met
        and official_agreement_ok
        and source_clean
        and inputs_clean
        and tools_clean
        and paired_comparable_corpus_coverage_complete
    )
    paired = _paired_comparison_summary(
        records,
        expected_executions=expected_executions,
        allow_equal_wall_time_claim=allow_equal_wall_time_claim,
        claim_context_eligible=claim_context_eligible,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "plan_mode": plan_mode,
        "evidence_classification": (
            "diagnostic_unverified_external_tooling"
            if external_tooling_present
            else (
                "native_only_replicated_evidence"
                if plan_mode == "replicated"
                else "native_diagnostic"
            )
        ),
        "record_count": len(records),
        "effective_record_count": sum(row.get("effective") is True for row in records),
        "conditions": conditions,
        "solver_conditions": solver_conditions,
        "families": families,
        "paired_comparisons": paired,
        "native_artifact_revalidation": [
            {
                "execution_id": result["execution_id"],
                "status": result["status"],
                "reason": result["reason"],
            }
            for result in artifact_revalidation_rows
        ],
        "gates": {
            "minimum_effective_runs_per_condition": required_effective_runs,
            "configured_minimum_effective_runs_per_condition": int(
                minimum_effective_runs_per_condition
            ),
            "replicated_design_complete": replicated_design_complete,
            "effective_target_met": target_met,
            "official_validator_agreement": official_agreement_ok,
            "official_validator_agreement_required": bool(
                require_official_validator_agreement
            ),
            "source_snapshot_stable": source_clean,
            "input_snapshots_stable": inputs_clean,
            "tool_snapshots_stable": tools_clean,
            "external_tooling_present": external_tooling_present,
            "tool_identity_mismatch_present": tool_identity_mismatch_present,
            "claim_grade_tooling": claim_grade_tooling,
            "native_timing_budget_compliant": native_timing_budget_compliant,
            "native_artifact_revalidation_complete": (
                native_artifact_revalidation_complete
            ),
            "native_result_integrity_complete": native_result_integrity_complete,
            "corpus_manifest_configured": corpus_manifest is not None,
            "corpus_manifest_complete": corpus_complete,
            "paired_comparable_corpus_coverage_complete": (
                paired_comparable_corpus_coverage_complete
            ),
            "execution_cells_exact_and_effective": execution_cells_exact,
            "expected_configs_self_consistent": expected_configs_self_consistent,
            "execution_identity_exact": execution_identity_exact,
            "paired_cells_complete": paired["paired_cells_complete"],
            "score_authority_enforced": paired["score_authority_enforced"],
            "superiority_claim_ready": bool(
                paired["superiority_claim_ready"]
                and target_met
                and official_agreement_ok
                and source_clean
                and inputs_clean
                and tools_clean
                and corpus_complete
                and corpus_manifest is not None
                and plan_mode == "replicated"
                and replicated_design_complete
                and execution_cells_exact
                and paired_comparable_corpus_coverage_complete
            ),
            "equal_wall_time_claim_permitted": paired[
                "equal_wall_time_claim_permitted"
            ],
            "benchmark_evidence_ready": bool(
                claim_context_eligible and execution_cells_exact
            ),
            "native_diagnostic_ready": bool(
                plan_mode == "smoke"
                and claim_grade_tooling
                and native_timing_budget_compliant
                and native_result_integrity_complete
                and target_met
                and source_clean
                and inputs_clean
                and tools_clean
                and execution_cells_exact
            ),
            "external_diagnostic_complete": bool(
                external_tooling_present
                and target_met
                and source_clean
                and inputs_clean
                and tools_clean
                and execution_cells_exact
            ),
        },
        "comparison_scope": (
            "Scores are aggregated only within each family; no cross-family "
            "scalar ranking is produced. External solver and validator commands "
            "are diagnostic_unverified and cannot support benchmark or superiority "
            "claims."
        ),
    }


def _load_plan(path: Path) -> BenchmarkPlan:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return BenchmarkPlan.from_dict(payload, base_directory=path.parent)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run source/tool-frozen native or paired external benchmarks across "
            "scheduling families."
        )
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    validate = subcommands.add_parser("validate-plan")
    validate.add_argument("--plan", type=Path, required=True)
    describe = subcommands.add_parser("describe")
    describe.add_argument("--pretty", action="store_true")
    run = subcommands.add_parser("run")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--repo-root", type=Path, default=Path.cwd())
    run.add_argument("--output-directory", type=Path, required=True)
    run.add_argument("--python-command", default=sys.executable)
    worker = subcommands.add_parser("worker", help=argparse.SUPPRESS)
    worker.add_argument("--request", type=Path, required=True)
    worker.add_argument("--result", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    if arguments.command == "describe":
        payload = {
            "schema_version": SCHEMA_VERSION,
            "plan_modes": sorted(PLAN_MODES),
            "default_replicated_effective_target_per_solver": 6,
            "external_tool_evidence_classification": "diagnostic_unverified",
            "replicated_external_tools_supported": False,
            "families": [family.to_dict() for family in BENCHMARK_FAMILIES],
        }
        print(
            json.dumps(payload, indent=2 if arguments.pretty else None, sort_keys=True)
        )
        return 0
    if arguments.command == "validate-plan":
        plan = _load_plan(arguments.plan.resolve())
        print(json.dumps(plan.to_dict(), sort_keys=True, indent=2))
        return 0
    if arguments.command == "worker":
        request = json.loads(arguments.request.read_text(encoding="utf-8"))
        result = run_worker_request(request)
        arguments.result.parent.mkdir(parents=True, exist_ok=True)
        _write_json(arguments.result, result)
        return 0
    if arguments.command == "run":
        plan = _load_plan(arguments.plan.resolve())
        summary = run_benchmark_plan(
            plan,
            repo_root=arguments.repo_root,
            output_directory=arguments.output_directory,
            python_command=arguments.python_command,
        )
        print(json.dumps(summary, sort_keys=True, indent=2))
        return 0
    raise AssertionError(f"unhandled command {arguments.command!r}")


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
