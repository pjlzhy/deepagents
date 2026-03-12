from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from deepagents_runtime.sandboxes import (
    SandboxSetupError,
    create_sandbox,
    get_default_working_dir,
)

if TYPE_CHECKING:
    from pathlib import Path


class _FakeExecuteResult:
    def __init__(self, *, output: str = "", exit_code: int = 0) -> None:
        self.output = output
        self.exit_code = exit_code
        self.truncated = False


class _FakeBackend:
    def __init__(self, backend_id: str, *, exit_code: int = 0) -> None:
        self._id = backend_id
        self._exit_code = exit_code
        self.executed: list[tuple[str, int | None]] = []

    @property
    def id(self) -> str:
        return self._id

    def execute(
        self, command: str, *, timeout: int | None = None
    ) -> _FakeExecuteResult:
        self.executed.append((command, timeout))
        return _FakeExecuteResult(output="ok", exit_code=self._exit_code)


class _FakeProvider:
    def __init__(self, backend: _FakeBackend) -> None:
        self.backend = backend
        self.created_with: list[dict[str, object]] = []
        self.deleted_ids: list[str] = []

    def get_or_create(
        self, *, sandbox_id: str | None = None, **kwargs: object
    ) -> _FakeBackend:
        payload: dict[str, object] = {"sandbox_id": sandbox_id}
        payload.update(kwargs)
        self.created_with.append(payload)
        return self.backend

    def delete(self, *, sandbox_id: str, **_: object) -> None:
        self.deleted_ids.append(sandbox_id)


def test_get_default_working_dir_returns_known_defaults() -> None:
    assert get_default_working_dir("modal") == "/workspace"
    assert get_default_working_dir("daytona") == "/home/daytona"

    with pytest.raises(ValueError, match="Unknown sandbox provider:"):
        _ = get_default_working_dir("nope")


def test_create_sandbox_creates_and_cleans_up_by_default() -> None:
    backend = _FakeBackend("sandbox-1")
    provider = _FakeProvider(backend)

    def resolver(_name: str) -> _FakeProvider:
        return provider

    with create_sandbox("modal", provider_resolver=resolver) as created:
        assert created is backend

    assert provider.created_with == [{"sandbox_id": None}]
    assert provider.deleted_ids == ["sandbox-1"]


def test_create_sandbox_does_not_cleanup_when_reusing_existing_sandbox() -> None:
    backend = _FakeBackend("sandbox-1")
    provider = _FakeProvider(backend)

    def resolver(_name: str) -> _FakeProvider:
        return provider

    with create_sandbox(
        "modal",
        provider_resolver=resolver,
        sandbox_id="existing",
    ) as created:
        assert created is backend

    assert provider.created_with == [{"sandbox_id": "existing"}]
    assert provider.deleted_ids == []


def test_create_sandbox_runs_setup_script(tmp_path: Path) -> None:
    backend = _FakeBackend("sandbox-1")
    provider = _FakeProvider(backend)

    def resolver(_name: str) -> _FakeProvider:
        return provider

    script_path = tmp_path / "setup.sh"
    script_path.write_text("echo ${TEST_VAR}", encoding="utf-8")

    with create_sandbox(
        "modal",
        provider_resolver=resolver,
        setup_script_path=str(script_path),
    ):
        pass

    assert backend.executed
    command, timeout = backend.executed[0]
    assert command.startswith("bash -c ")
    assert timeout == 5 * 60


def test_create_sandbox_forwards_provider_kwargs() -> None:
    backend = _FakeBackend("sandbox-1")
    provider = _FakeProvider(backend)

    def resolver(_name: str) -> _FakeProvider:
        return provider

    with create_sandbox(
        "modal",
        provider_resolver=resolver,
        provider_kwargs={"timeout": 123},
    ):
        pass

    assert provider.created_with == [{"sandbox_id": None, "timeout": 123}]


def test_create_sandbox_cleans_up_when_setup_fails(tmp_path: Path) -> None:
    backend = _FakeBackend("sandbox-1", exit_code=1)
    provider = _FakeProvider(backend)

    def resolver(_name: str) -> _FakeProvider:
        return provider

    script_path = tmp_path / "setup.sh"
    script_path.write_text("echo fail", encoding="utf-8")

    entered = False
    with pytest.raises(SandboxSetupError), create_sandbox(
        "modal",
        provider_resolver=resolver,
        setup_script_path=str(script_path),
    ):
        entered = True

    assert entered is False

    assert provider.deleted_ids == ["sandbox-1"]
