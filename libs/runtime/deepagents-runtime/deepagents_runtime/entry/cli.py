"""CLI entry point: ``deepagents`` command.

Provides commands for agent execution and management:
    - ``deepagents run``         — Run an agent interactively
    - ``deepagents serve``       — Start data plane gRPC server
    - ``deepagents workspace``   — Manage workspace of agents
    - ``deepagents registry``    — CRUD for agent specs
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="deepagents",
        description="Agent OS — AI agent platform",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ── run ──
    run_parser = subparsers.add_parser("run", help="Run an agent")
    run_parser.add_argument("agent", help="Agent name or spec YAML path")
    run_parser.add_argument(
        "-m", "--message", default="", help="Input message"
    )
    run_parser.add_argument(
        "--mode",
        choices=["chat", "gateway", "cron"],
        default="chat",
        help="Launch mode (default: chat)",
    )
    run_parser.add_argument(
        "--thread", default=None, help="Resume a specific thread"
    )
    run_parser.add_argument(
        "--model", default=None, help="Override model (provider:model)"
    )

    # ── serve ──
    serve_parser = subparsers.add_parser(
        "serve", help="Start data plane gRPC server"
    )
    serve_parser.add_argument(
        "--port", type=int, default=50051, help="gRPC listen port (default: 50051)"
    )

    # ── workspace ──
    ws_parser = subparsers.add_parser("workspace", help="Manage workspace")
    ws_sub = ws_parser.add_subparsers(dest="ws_command")
    ws_up = ws_sub.add_parser("up", help="Start all agents in workspace")
    ws_up.add_argument(
        "-f",
        "--file",
        default="workspace.yaml",
        help="Workspace YAML path",
    )
    ws_sub.add_parser("down", help="Stop all agents in workspace")
    ws_sub.add_parser("status", help="Show workspace status")

    # ── registry ──
    reg_parser = subparsers.add_parser("registry", help="Manage registry")
    reg_sub = reg_parser.add_subparsers(dest="reg_command")

    # registry agent
    agent_parser = reg_sub.add_parser("agent", help="Manage agent specs")
    agent_sub = agent_parser.add_subparsers(dest="agent_command")
    agent_add = agent_sub.add_parser("add", help="Add agent spec from YAML")
    agent_add.add_argument("file", help="Agent spec YAML path")
    agent_sub.add_parser("list", help="List agent specs")
    agent_rm = agent_sub.add_parser("remove", help="Remove an agent spec")
    agent_rm.add_argument("name", help="Agent name")

    return parser


async def _cmd_run(args: argparse.Namespace) -> None:
    """Execute the ``run`` command."""
    from deepagents_runtime.manager.manager import AgentManager
    from deepagents_runtime.spec import AgentSpec, LaunchMode, RunConfig

    manager = AgentManager()

    # Load agent: from registry name or YAML file
    agent_path = Path(args.agent)
    if agent_path.suffix in (".yaml", ".yml") and agent_path.exists():
        import yaml

        with open(agent_path) as f:
            data = yaml.safe_load(f)
        spec = AgentSpec.from_yaml(data)
    else:
        spec = await manager.registry.get_agent_spec(args.agent)
        if spec is None:
            print(f"Error: Agent '{args.agent}' not found", file=sys.stderr)
            sys.exit(1)

    if args.model:
        spec.model = args.model

    await manager.define_agent(spec)
    await manager.assemble_agent(spec.name)

    run_config = RunConfig(
        mode=LaunchMode(args.mode),
        input=args.message,
        thread_id=args.thread,
    )

    async for event in manager.invoke(spec.name, run_config):
        # Simple text streaming to stdout
        if event.type.value == "text_delta":
            print(event.data.get("text", ""), end="", flush=True)
        elif event.type.value == "run_end":
            print()  # newline after streaming
            stats = event.data.get("stats", {})
            if stats:
                print(
                    f"\n[{stats.get('request_count', 0)} requests | "
                    f"{stats.get('input_tokens', 0)} in / "
                    f"{stats.get('output_tokens', 0)} out | "
                    f"{stats.get('wall_time_seconds', 0)}s]",
                    file=sys.stderr,
                )
        elif event.type.value == "error":
            print(
                f"Error: {event.data.get('message', '')}",
                file=sys.stderr,
            )


async def _cmd_serve(args: argparse.Namespace) -> None:
    """Execute the ``serve`` command — start data plane gRPC server."""
    from deepagents_runtime.entry.server import serve

    print(f"Starting data plane gRPC server on port {args.port}...")
    await serve(port=args.port)


async def _cmd_workspace_up(args: argparse.Namespace) -> None:
    """Execute ``workspace up``."""
    import yaml

    from deepagents_runtime.spec import WorkspaceConfig

    ws_path = Path(args.file)
    if not ws_path.exists():
        print(f"Error: {ws_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(ws_path) as f:
        data = yaml.safe_load(f)
    config = WorkspaceConfig.from_yaml(data)

    print(f"Starting workspace '{config.name}' with {len(config.agents)} agents...")
    # TODO: implement full workspace execution flow
    for name, entry in config.agents.items():
        print(f"  - {name}: {entry.mode.value} (spec: {entry.spec_path})")


async def _cmd_registry(args: argparse.Namespace) -> None:
    """Execute ``registry`` subcommands."""
    from deepagents_runtime.registry import Registry
    from deepagents_runtime.spec import AgentSpec

    registry = Registry()

    if args.reg_command == "agent":
        if args.agent_command == "add":
            import yaml

            with open(args.file) as f:
                data = yaml.safe_load(f)
            spec = AgentSpec.from_yaml(data)
            await registry.add_agent_spec(spec)
            print(f"Agent spec '{spec.name}' added")
        elif args.agent_command == "list":
            agents = await registry.list_agent_specs()
            for a in agents:
                print(f"  {a.name} v{a.version}: {a.description}")
            if not agents:
                print("  (no agent specs registered)")
        elif args.agent_command == "remove":
            if await registry.delete_agent_spec(args.name):
                print(f"Agent spec '{args.name}' removed")
            else:
                print(f"Agent spec '{args.name}' not found")
    else:
        print("Usage: deepagents registry agent {add|list|remove}")


async def _async_main(args: argparse.Namespace) -> None:
    """Route to the appropriate async command handler."""
    if args.command == "run":
        await _cmd_run(args)
    elif args.command == "serve":
        await _cmd_serve(args)
    elif args.command == "workspace":
        if args.ws_command == "up":
            await _cmd_workspace_up(args)
        elif args.ws_command == "down":
            print("Stopping workspace...")  # TODO
        elif args.ws_command == "status":
            print("Workspace status...")  # TODO
        else:
            print("Usage: deepagents workspace {up|down|status}")
    elif args.command == "registry":
        await _cmd_registry(args)
    else:
        _build_parser().print_help()


def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if not args.command:
        parser.print_help()
        sys.exit(0)

    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
