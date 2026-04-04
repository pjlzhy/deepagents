export const links = {
  overview: () => '/overview',
  models: () => '/registry/models',
  skills: () => '/registry/skills',
  mcps: () => '/registry/mcps',
  sandboxes: () => '/registry/sandboxes',
  agents: () => '/registry/agents',
  newAgent: () => '/registry/agents/new',
  agentDetail: (agentName: string) => `/registry/agents/${encodeURIComponent(agentName)}`,
  buildAgent: () => '/registry/agents/build',
  buildAgentEdit: (agentName: string) => `/registry/agents/build/${encodeURIComponent(agentName)}`,
  chatRoot: () => '/chat',
  chatAgent: (agentName: string) => `/chat/${encodeURIComponent(agentName)}`,
  chatThread: (agentName: string, threadId: string) =>
    `/chat/${encodeURIComponent(agentName)}/${encodeURIComponent(threadId)}`,
  telemetryRoot: () => '/telemetry',
  telemetryAgent: (agentName: string) => `/telemetry/${encodeURIComponent(agentName)}`,
};
