export const links = {
  overview: () => '/overview',
  models: () => '/registry/models',
  skills: () => '/registry/skills',
  mcps: () => '/registry/mcps',
  agents: () => '/registry/agents',
  newAgent: () => '/registry/agents/new',
  agentDetail: (agentName: string) => `/registry/agents/${encodeURIComponent(agentName)}`,
  chatRoot: () => '/chat',
  chatAgent: (agentName: string) => `/chat/${encodeURIComponent(agentName)}`,
  chatThread: (agentName: string, threadId: string) =>
    `/chat/${encodeURIComponent(agentName)}/${encodeURIComponent(threadId)}`,
  history: () => '/history',
};
