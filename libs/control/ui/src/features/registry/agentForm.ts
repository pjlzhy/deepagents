import {
  formatJsonValue,
  formatMultilineList,
  parseMultilineList,
  parseOptionalStringMap,
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
  interruptOnText: string;
  sandboxImage: string;
  sandboxResourcesJson: string;
  sandboxInitText: string;
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
    interruptOnText: formatMultilineList(agent?.interrupt_on),
    sandboxImage: agent?.sandbox?.image ?? '',
    sandboxResourcesJson: formatJsonValue(agent?.sandbox?.resources),
    sandboxInitText: formatMultilineList(agent?.sandbox?.init),
    subagentsJson: formatJsonValue(agent?.subagents),
  };
}

export function toAgentUpsertRequest(values: AgentFormValues): AgentSpecUpsertRequestDTO {
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
    subagents: parseOptionalSubagents(values.subagentsJson),
    sandbox: {
      image: values.sandboxImage.trim() || undefined,
      resources: parseOptionalStringMap(values.sandboxResourcesJson, 'sandbox.resources'),
      init: parseMultilineList(values.sandboxInitText),
    },
    interrupt_on: parseMultilineList(values.interruptOnText),
    status: values.status || undefined,
  };
}
