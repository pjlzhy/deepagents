"""Unit tests for the Docker sandbox backend."""

from __future__ import annotations

from deepagents.backends.protocol import ExecuteResponse

from agents_runtime.sandbox.docker import DockerSandboxBackend


class FakeContainer:
    """Minimal fake Docker container for exec_run capture."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict[str, object]]] = []
        self.next_exit_code = 0
        self.next_output = b""

    def exec_run(self, cmd: list[str], **kwargs: object) -> tuple[int, bytes]:
        self.calls.append((cmd, kwargs))
        return self.next_exit_code, self.next_output


class StubDockerSandboxBackend(DockerSandboxBackend):
    """Docker backend stub that routes upload/download helpers through canned execute responses."""

    def __init__(self) -> None:
        super().__init__(image="python:3.12-slim")
        self.execute_calls: list[str] = []
        self.responses: list[ExecuteResponse] = []

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        del timeout
        self.execute_calls.append(command)
        if not self.responses:
            raise AssertionError("no canned ExecuteResponse available")
        return self.responses.pop(0)


def test_from_spec_reads_max_output_bytes() -> None:
    """Docker backend should honor `resources.max_output_bytes` from spec."""

    backend = __import__("asyncio").run(
        DockerSandboxBackend.from_spec(
            {
                "image": "python:3.12",
                "resources": {"backend": "docker", "max_output_bytes": 2048},
            }
        )
    )

    assert backend._image == "python:3.12"
    assert backend._max_output_bytes == 2048


def test_from_spec_accepts_runtime_mount_contract() -> None:
    """Docker backend should retain the runtime root mount configuration."""

    backend = __import__("asyncio").run(
        DockerSandboxBackend.from_spec(
            {
                "image": "python:3.12",
                "resources": {"backend": "docker"},
            },
            host_mount_dir="/tmp/runtime-agent",
            container_root="/agent",
        )
    )

    assert backend._host_mount_dir == "/tmp/runtime-agent"
    assert backend._container_root == "/agent"


def test_execute_passes_timeout_and_truncates_output() -> None:
    """Docker execute should pass timeout through to exec_run and truncate oversized output."""

    backend = DockerSandboxBackend(max_output_bytes=4)
    container = FakeContainer()
    container.next_output = b"abcdef"
    backend._container = container

    result = backend.execute("echo hi", timeout=12)

    assert result.output == "abcd"
    assert result.exit_code == 0
    assert result.truncated is True
    assert container.calls == [(["sh", "-c", "echo hi"], {"demux": False, "timeout": 12})]


def test_upload_files_maps_success_and_errors() -> None:
    """Upload should preserve order and map per-file failures."""

    backend = StubDockerSandboxBackend()
    backend.responses = [
        ExecuteResponse(output="", exit_code=0, truncated=False),
        ExecuteResponse(output="permission_denied\n", exit_code=13, truncated=False),
    ]

    responses = backend.upload_files(
        [
            ("/ok.txt", b"ok"),
            ("/denied.txt", b"nope"),
            ("relative.txt", b"bad"),
        ]
    )

    assert [response.error for response in responses] == [None, "permission_denied", "invalid_path"]
    assert len(backend.execute_calls) == 2


def test_download_files_maps_success_and_errors() -> None:
    """Download should decode payloads and map per-file failures."""

    backend = StubDockerSandboxBackend()
    backend.responses = [
        ExecuteResponse(output="aGVsbG8=", exit_code=0, truncated=False),
        ExecuteResponse(output="file_not_found\n", exit_code=2, truncated=False),
        ExecuteResponse(output="is_directory\n", exit_code=21, truncated=False),
    ]

    responses = backend.download_files(
        [
            "/ok.txt",
            "/missing.txt",
            "/dir",
            "relative.txt",
        ]
    )

    assert responses[0].content == b"hello"
    assert responses[0].error is None
    assert responses[1].error == "file_not_found"
    assert responses[2].error == "is_directory"
    assert responses[3].error == "invalid_path"
    assert len(backend.execute_calls) == 3


def test_download_files_rejects_invalid_base64_payload() -> None:
    """Download should fail closed when the container returns malformed base64."""

    backend = StubDockerSandboxBackend()
    backend.responses = [
        ExecuteResponse(output="not-base64!", exit_code=0, truncated=False),
    ]

    responses = backend.download_files(["/corrupt.txt"])

    assert responses[0].content is None
    assert responses[0].error == "invalid_path"
