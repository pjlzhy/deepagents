"""Utilities for regenerating runtime protobuf stubs.

The key constraint here is to keep generated files directly under
`agents_runtime/generated/`, not under a nested package path like
`generated/deepagents/runtime/v1/`. The script achieves that by invoking
`protoc` from the repo-level `proto/` directory and compiling `runtime.proto`
directly.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Sequence

_PROTO_RELATIVE_PATH = Path("runtime.proto")
_GENERATED_FILENAMES = (
    "runtime_pb2.py",
    "runtime_pb2.pyi",
    "runtime_pb2_grpc.py",
)


def _default_package_root() -> Path:
    """Return the runtime package root directory."""
    return Path(__file__).resolve().parents[1]


def _default_repo_root(package_root: Path) -> Path:
    """Return the monorepo root for the given runtime package."""
    return package_root.parents[2]


def _build_protoc_args(*, proto_dir: Path, output_dir: Path) -> list[str]:
    """Build the `grpc_tools.protoc` argv for runtime.proto generation.

    Args:
        proto_dir: Directory containing `runtime.proto`.
        output_dir: Target directory for generated files.

    Returns:
        The argument vector for `grpc_tools.protoc.main()`.
    """
    grpc_tools_root = _grpc_tools_proto_root()
    return [
        "grpc_tools.protoc",
        f"-I{proto_dir}",
        f"-I{grpc_tools_root}",
        f"--python_out={output_dir}",
        f"--pyi_out={output_dir}",
        f"--grpc_python_out={output_dir}",
        "runtime.proto",
    ]


def _grpc_tools_proto_root() -> Path:
    """Return the built-in protobuf include directory shipped with grpc_tools."""
    import grpc_tools

    return Path(grpc_tools.__file__).resolve().parent / "_proto"


def _run_protoc(args: Sequence[str]) -> int:
    """Invoke `grpc_tools.protoc` and return its exit code.

    Args:
        args: Argument vector passed to `grpc_tools.protoc.main()`.

    Returns:
        The integer exit code from `grpc_tools.protoc`.
    """
    from grpc_tools import protoc

    return int(protoc.main(list(args)))


def _validate_generated_outputs(output_dir: Path) -> list[Path]:
    """Validate that all expected runtime stub files exist in the target directory.

    Args:
        output_dir: Directory expected to contain the top-level runtime stubs.

    Returns:
        The resolved output file paths.

    Raises:
        FileNotFoundError: If any expected generated file is missing.
    """
    output_paths: list[Path] = []
    for filename in _GENERATED_FILENAMES:
        path = output_dir / filename
        if not path.is_file():
            msg = f"missing generated stub: {path}"
            raise FileNotFoundError(msg)
        output_paths.append(path)
    return output_paths


def generate_runtime_proto(
    *,
    package_root: Path | None = None,
    repo_root: Path | None = None,
) -> list[Path]:
    """Regenerate checked-in protobuf artifacts for the runtime package.

    Args:
        package_root: Optional override for `libs/runtime/agents-runtime`.
        repo_root: Optional override for the monorepo root.

    Returns:
        The generated top-level stub file paths.

    Raises:
        FileNotFoundError: If `runtime.proto` cannot be found or generated files
            are incomplete.
        RuntimeError: If `grpc_tools.protoc` returns a non-zero exit code.
    """
    resolved_package_root = package_root or _default_package_root()
    resolved_repo_root = repo_root or _default_repo_root(resolved_package_root)

    proto_dir = resolved_repo_root / "proto"
    proto_file = proto_dir / _PROTO_RELATIVE_PATH
    output_dir = resolved_package_root / "agents_runtime" / "generated"

    if not proto_file.is_file():
        msg = f"runtime proto not found: {proto_file}"
        raise FileNotFoundError(msg)

    output_dir.mkdir(parents=True, exist_ok=True)
    exit_code = _run_protoc(
        _build_protoc_args(proto_dir=proto_dir, output_dir=output_dir)
    )
    if exit_code != 0:
        msg = f"grpc_tools.protoc failed with exit code {exit_code}"
        raise RuntimeError(msg)
    return _validate_generated_outputs(output_dir)


def main() -> int:
    """CLI entry point for local runtime proto regeneration."""
    try:
        copied_paths = generate_runtime_proto()
    except Exception as exc:
        print(f"Failed to generate runtime protobuf stubs: {exc}", file=sys.stderr)
        return 1

    print("Generated runtime protobuf stubs:")
    for path in copied_paths:
        print(f" - {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
