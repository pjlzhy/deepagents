"""Runtime-specific skill loading behavior."""

from __future__ import annotations

from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from deepagents.middleware.skills import SkillsMiddleware, SkillsState, SkillsStateUpdate


def _state_without_skills_metadata(state: SkillsState) -> SkillsState:
    """Return a shallow copy of state without cached skill metadata.

    Runtime skill directories can change after a thread starts because the
    control plane sync path rewrites skill snapshots on disk. Removing the
    cached `skills_metadata` key forces the upstream middleware to rescan the
    configured sources on every turn while preserving the rest of the thread
    state.

    Args:
        state: Current agent state.

    Returns:
        A shallow state copy that does not include `skills_metadata`.
    """
    if "skills_metadata" not in state:
        return state

    next_state = dict(state)
    next_state.pop("skills_metadata", None)
    return cast(SkillsState, next_state)


class RuntimeSkillsMiddleware(SkillsMiddleware):
    """Refresh skill metadata on every runtime turn.

    The upstream `SkillsMiddleware` caches `skills_metadata` in checkpoint
    state, which is desirable for general SDK usage but prevents long-lived
    runtime threads from seeing skill updates or additions that arrive after
    the thread starts. Runtime agents keep skill snapshots on local disk, so
    rescanning these sources on each turn is the simplest way to ensure newly
    synced skills become visible immediately.
    """

    def before_agent(
        self,
        state: SkillsState,
        runtime: Runtime,
        config: RunnableConfig,
    ) -> SkillsStateUpdate | None:
        """Reload skill metadata before each synchronous turn.

        Args:
            state: Current agent state.
            runtime: Runtime context.
            config: Runnable config.

        Returns:
            A fresh `skills_metadata` state update for the current turn.
        """
        return super().before_agent(
            _state_without_skills_metadata(state),
            runtime,
            config,
        )

    async def abefore_agent(
        self,
        state: SkillsState,
        runtime: Runtime,
        config: RunnableConfig,
    ) -> SkillsStateUpdate | None:
        """Reload skill metadata before each asynchronous turn.

        Args:
            state: Current agent state.
            runtime: Runtime context.
            config: Runnable config.

        Returns:
            A fresh `skills_metadata` state update for the current turn.
        """
        return await super().abefore_agent(
            _state_without_skills_metadata(state),
            runtime,
            config,
        )
