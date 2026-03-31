import {
  formatJsonValue,
  formatMultilineList,
  parseMultilineList,
  parseOptionalSubagents,
} from '@/features/registry/formCodecs';
import type { AgentSpecDTO, AgentSpecUpsertRequestDTO } from '@/shared/types/api';

export type AgentFormValues = {
  name: string;
  version: string;
  description: string;
  status: string;
  modelRef: string;
  tagsText: string;
  promptSystem: string;
  skillRefs: string[];
  mcpRefs: string[];
  sandboxRef: string;
  interruptOnText: string;
  subagentsJson: string;
};

export function toAgentFormValues(agent?: AgentSpecDTO): AgentFormValues {
  return {
    name: agent?.name ?? '',
    version: agent?.version ?? '',
    description: agent?.description ?? '',
    status: agent?.status ?? 'draft',
    modelRef: agent?.model_ref ?? '',
    tagsText: formatMultilineList(agent?.tags),
    promptSystem: agent?.prompt?.system ?? '',
    skillRefs: agent?.skill_refs ?? [],
    mcpRefs: agent?.mcp_refs ?? [],
    sandboxRef: agent?.sandbox_ref ?? '',
    interruptOnText: formatMultilineList(agent?.interrupt_on),
    subagentsJson: formatJsonValue(agent?.subagents),
  };
}

export function toAgentUpsertRequest(
  values: AgentFormValues,
): AgentSpecUpsertRequestDTO {
  return {
    version: values.version.trim() || undefined,
    description: values.description.trim() || undefined,
    tags: parseMultilineList(values.tagsText),
    model_ref: values.modelRef.trim() || undefined,
    prompt: {
      system: values.promptSystem,
    },
    skill_refs: values.skillRefs,
    mcp_refs: values.mcpRefs,
    sandbox_ref: values.sandboxRef.trim() || undefined,
    subagents: parseOptionalSubagents(values.subagentsJson),
    interrupt_on: parseMultilineList(values.interruptOnText),
    status: values.status || undefined,
  };
}
