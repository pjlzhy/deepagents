# Agent OS Architecture Design

> An operating system for AI agents: manage agents as resources, assemble them from reusable components, and run them through a stable control-plane / data-plane split.

## 1. Design Philosophy

### 1.1 Agent as Process

Agent OS treats AI agents the way an operating system treats processes. The platform does not care about an agent's internal reasoning. It manages lifecycle, resources, isolation, and invocation boundaries.

| OS Concept | Agent OS Concept |
|------------|------------------|
| Process | Agent |
| Executable | `AgentSpec` |
| System calls | Backend and tool interfaces |
| Shared libraries | Skills and MCP integrations |
| Process manager | Control plane lifecycle manager + data plane `AgentManager` |
| Kernel | `deepagents` SDK |

### 1.2 Prompt as Orchestration

Agent orchestration is not encoded as a fixed DAG. It lives in prompt inputs, skills, memory, tools, and sub-agents. The platform is responsible for assembly and runtime management, not workflow authoring.

### 1.3 Declarative Assembly

An agent is assembled from declarative inputs:

```text
Agent = Model + Prompt + Skills + Memory + Tools + SubAgents
```

The control plane owns resource management and packages runtime-ready inputs. The data plane consumes those inputs and builds the executable graph.

### 1.4 Run Anywhere

The same runtime model should work across local and K8s deployments. Provisioning changes by environment, but control-plane / data-plane responsibilities stay the same.

---

## 2. Architecture Overview

Agent OS uses a unified separated architecture: control plane and data plane are always independent processes and communicate only through gRPC.

```text
+---------------------------+        gRPC         +---------------------------+
| Control Plane             | <----------------> | Data Plane                |
| deepagents-control        |                    | deepagents-runtime        |
|                           |                    |                           |
| Registry / packaging      |                    | Compile / execution       |
| Lifecycle / scheduling    |                    | Agent runtime / run leases|
| Routing / external API    |                    | Session / checkpoint      |
+---------------------------+                    +---------------------------+
```

### 2.1 Layer Responsibilities

| Layer | Responsibility | Knows about |
|-------|---------------|-------------|
| **SDK** (`deepagents`) | Build agent graphs from components | Models, tools, backends, middleware |
| **Control Plane** (`deepagents-control`) | Own registry, package resources, manage lifecycle and scheduling | Registry, packaging, cron, routing, external API |
| **Data Plane** (`deepagents-runtime`) | Consume rich `AgentSpec` inputs, assemble agents, execute runs | Assembly, orchestration, sandbox, MCP, sessions |
| **gRPC Protocol** (`proto/`) | Control <-> Data plane communication | `AgentExecutor`, `ResourceSync` |

### 2.2 Unified Runtime Code

Local and K8s deployments should use the same runtime behavior. The main difference is provisioning:

| | Local | K8s |
|--|-------|-----|
| Control plane | One process | One Deployment / Pod |
| Data plane | One process | One or more Deployments / Pods |
| Network | localhost | Service / cluster network |
| Provisioning | CLI / local scripts | Helm / kubectl |
| Runtime contract | Same | Same |

---

## 3. Control Plane / Data Plane Separation

Control plane and data plane are always separate processes.

### 3.1 Control Plane Responsibilities

The control plane is responsible for:

- registry CRUD for skills, MCP configs, and agent definitions
- workspace and shared-reference resolution
- packaging runtime-ready agent inputs
- install / compile / uninstall orchestration
- lifecycle and status management
- scheduling and routing
- future external API exposure

### 3.2 Data Plane Responsibilities

The data plane is responsible for:

- receiving rich `AgentSpec` inputs over gRPC
- compiling `AgentSpec` into runnable `AgentTemplate`
- executing runs through a stable runtime entrypoint
- managing agent-scoped runtime resources such as MCP runtime and sandbox owners
- managing run-scoped resources such as sandbox leases, checkpoints, and execution context
- exposing health and runtime status to the control plane

### 3.3 Communication Protocol

All control-plane to data-plane communication uses gRPC:

- `AgentExecutor.Run`: bidirectional streaming agent invocation with HITL support
- `ResourceSync.*`: unary RPCs for syncing rich `AgentSpec` inputs and runtime directives

`SyncAgentSpec` is the primary sync unit. `SyncSkill` and `SyncMcp` are compatibility RPCs and are not the preferred packaging path for new flows.

---

## 4. Resource Model

Resources are owned by the control plane Registry. The data plane consumes a runtime-oriented `AgentSpec` produced by the control plane.

### 4.1 Control Plane Resources

The control plane remains the source of truth for:

- **Skills**: reusable prompt instructions (`SKILL.md` content)
- **MCP configs**: reusable server connection definitions
- **AgentSpecs**: declarative agent definitions authored by users
- **Workspace/shared references**: optional authoring-time indirections

### 4.2 Runtime Input: Rich `AgentSpec`

Before syncing an agent to the data plane, the control plane may resolve or package registry resources, local files, and workspace references into a richer runtime input.

```yaml
metadata:
  name: code-reviewer
  version: 1.0.0

spec:
  model: anthropic:claude-sonnet-4-20250514
  prompt:
    system: |
      You are a senior code reviewer.
  skills:
    - name: code-review
      content: "<embedded SKILL.md>"
  mcp_servers:
    - name: github
      command: npx @modelcontextprotocol/server-github
      transport: stdio
  subagents:
    - name: test-runner
      description: Run project tests
      system_prompt: Run focused tests and summarize failures.
```

The exact packaging granularity is a control-plane concern. The data plane treats the synced `AgentSpec` as assembly input, not as mutable global registry state.

---

## 5. Lifecycle Model

The lifecycle is split into two layers: the agent lifecycle and the run lifecycle.

### 5.1 Agent Lifecycle

The public agent lifecycle is:

```text
absent -> installed -> compiled(runnable) -> absent
```

Operation mapping:

- `SyncAgentSpec = install`
- `Assemble = compile`
- `Remove/Delete = uninstall`

The internal runtime may still support an `unload` action that releases compiled resources while keeping the synced spec, but this should not be exposed as a public `stop` concept.

### 5.2 Run Lifecycle

The public run lifecycle is:

```text
created -> running -> ended | canceled | errored
```

Operation mapping:

- `Run = execute`
- `CancelRequest = cancel current run`

`cancel` applies only to the current execution stream. It is not a synonym for uninstalling or unloading an agent.

### 5.3 Runtime Ownership

The control plane owns registry CRUD, packaging, scheduling, and uninstall orchestration.

The data plane `AgentManager` owns runtime resources:

- compiled `AgentTemplate`
- agent-scoped MCP runtime
- agent-scoped sandbox runtime owner
- active runs

---

## 6. Control Plane Registry

The Registry lives in the control plane and remains the system source of truth for skills, MCP configs, and agent definitions.

Its responsibilities are:

- CRUD for skills, MCP configs, and authored `AgentSpec`
- workspace and shared-reference resolution
- packaging runtime-ready `AgentSpec` payloads for the data plane
- dependency tracking and safe deletion checks

The data plane may cache synced specs locally for assembly and runtime state, but it does not own the authoritative resource graph.

---

## 7. Assembly

Assembly transforms a rich `AgentSpec` into a runnable `AgentTemplate`.

### 7.1 Assembly Flow

```text
Control Plane Registry / Workspace refs
    -> resolve + package
        -> rich AgentSpec
            -> SyncAgentSpec (gRPC)
                -> Data Plane compile():
                    - resolve model
                    - build middleware from prompt / skills
                    - attach mcp_servers metadata
                    - attach subagents metadata
                    - materialize agent-scoped MCP runtime
                    - materialize agent-scoped sandbox runtime
                    - create_deep_agent(...)
                        -> compiled graph + runtime resources
```

### 7.2 Responsibility Split

The control plane owns reference resolution and packaging. The data plane owns runtime graph construction.

---

## 8. gRPC Protocol

All communication between control plane and data plane uses `proto/deepagents/runtime/v1/runtime.proto`.

### 8.1 Services

| Service | Direction | Purpose |
|---------|-----------|---------|
| `AgentExecutor` | Control -> Data | Agent invocation with bidirectional streaming |
| `ResourceSync` | Control -> Data | Sync rich `AgentSpec` inputs and runtime directives |

### 8.2 `AgentExecutor.Run`

`Run` is the execution RPC.

High-level flow:

1. Control plane opens a bidi stream
2. Control plane sends `RunRequest`
3. Data plane streams `AgentEvent`
4. If HITL is triggered, data plane sends `HITLRequest`
5. Control plane sends `HITLDecision`
6. Stream completes with `RunEnded`, `RunCanceled`, or `ErrorOccurred`

### 8.3 `ResourceSync`

`ResourceSync` is used to move runtime-ready inputs and runtime directives into the data plane.

```text
SyncSkill / SyncMcp    -> compatibility RPCs for older callers
SyncAgentSpec          -> install rich AgentSpec into data plane
Assemble(agent_name)   -> compile agent into runnable runtime
RemoveResource(...)    -> uninstall synced resource or cached runtime state
Health()               -> status / readiness check
```

The primary path is `SyncAgentSpec -> Assemble -> Run`.

---

## 9. Launch Modes

Launch mode is runtime configuration, not part of the authored agent definition.

- **Chat**: interactive session-based invocation
- **Gateway**: long-running service endpoint
- **Cron**: scheduled invocation managed by the control plane

---

## 10. CLI and Workspace

The control plane CLI manages the full system.

Representative commands:

```bash
deepagents up
deepagents registry ...
deepagents agent invoke <name> -m "..."
deepagents workspace up
```

Workspaces group authored resources and agent entries. They are a control-plane concern used for authoring, packaging, and deployment.

---

## 11. Data Flow

### 11.1 Invocation Flow

```text
CLI / Caller
  -> Control Plane
      - lookup agent -> data plane endpoint
      - ensure rich AgentSpec is installed and compiled
      - open AgentExecutor.Run stream
          -> Data Plane
              - load compiled AgentTemplate
              - reuse agent-scoped MCP / sandbox runtime resources
              - prepare run-scoped execution context
              - execute graph
              - stream AgentEvents
              - cleanup run-scoped control state
```

### 11.2 Assembly Flow

```text
Control Plane Registry / Workspace refs
    -> resolve + package
        -> rich AgentSpec
            -> SyncAgentSpec
                -> Data Plane assembly
                    - create model
                    - build middleware from prompt / skills
                    - attach mcp_servers / subagents / sandbox spec
                    - create agent-scoped MCP / sandbox runtime resources
                    -> compiled runtime
```

---

## 12. Sandbox

Sandboxing is a data-plane responsibility. In the current runtime, sandbox resources are owned by the compiled runtime agent, not by an individual run.

Current lifecycle:

- `Assemble` resolves `SandboxSpec` and creates one agent-scoped sandbox backend when sandboxing is enabled
- `Run` reuses that backend by injecting it into the graph runtime context
- `Release` / `Remove` / manager shutdown clean up the owned backend

Backend selection is driven by `SandboxSpec`:

- prefer `sandbox.resources.backend`
- also accept `sandbox.resources.kind` and `sandbox.resources.provider` as compatibility aliases
- if no backend is declared but `image` is present, default to `docker`
- otherwise default to `local`

Current backend semantics:

- `local`: use `LocalShellBackend` rooted at the agent workspace; execution is local-host shell execution without isolation
- `docker`: create one long-lived container per compiled agent and reuse it across runs until release
- `k8s`: reserved in the contract, but not yet implemented in the runtime

---

## 13. MCP Integration

MCP integration is split across planes:

- control plane stores reusable MCP definitions and packages them into runtime-ready inputs
- data plane receives MCP server configurations and manages runtime MCP usage

MCP server metadata belongs in the synced `AgentSpec`. Live MCP sessions belong to agent-scoped runtime state:

- `Assemble` starts MCP runtime resources and loads MCP tools
- `Run` reuses the compiled agent's MCP runtime
- `Release` / `Remove` / manager shutdown clean up MCP sessions

---

## 14. Sub-Agents

Sub-agents are part of the runtime assembly model.

The control plane may resolve or package sub-agent metadata before sync. The data plane is responsible for attaching those runtime-ready definitions during graph assembly.

---

## 15. Summary

The architectural split is:

- **Control plane** owns registry, packaging, lifecycle, scheduling, and routing
- **Data plane** owns assembly, execution, run-scoped resources, and runtime state

The boundary between them is a stable gRPC protocol centered on rich `AgentSpec` input and streaming invocation.
