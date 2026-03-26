"""Unit tests for runtime proto code generation helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepagents_runtime import proto_codegen

def test_build_protoc_args_use_leaf_proto_directory() -> None:
    """Protoc args should compile `runtime.proto` from the repo-level proto directory."""
    proto_dir = Path("D:/repo/proto")
    output_dir = Path("D:/repo/libs/runtime/deepagents-runtime/deepagents_runtime/generated")

    args = proto_codegen._build_protoc_args(
        proto_dir=proto_dir,
        output_dir=output_dir,
    )

    assert args[0] == "grpc_tools.protoc"
    assert f"-I{proto_dir}" in args
    assert f"--python_out={output_dir}" in args
    assert args[-1] == "runtime.proto"


def test_validate_generated_outputs_returns_top_level_runtime_stubs() -> None:
    """Validation should accept the checked-in top-level generated stub layout."""
    generated_dir = Path(__file__).resolve().parents[2] / "deepagents_runtime" / "generated"

    outputs = proto_codegen._validate_generated_outputs(generated_dir)

    assert outputs == [
        generated_dir / "runtime_pb2.py",
        generated_dir / "runtime_pb2.pyi",
        generated_dir / "runtime_pb2_grpc.py",
    ]


def test_validate_generated_outputs_rejects_missing_stub() -> None:
    """Validation should fail fast when a required generated file is absent."""
    missing_dir = Path(__file__).resolve().parents[2] / "does-not-exist"

    with pytest.raises(FileNotFoundError, match="runtime_pb2.py"):
        proto_codegen._validate_generated_outputs(missing_dir)
