import type { AgentSpecDTO, AgentSpecUpsertRequestDTO } from '@/shared/types/api';

export type SubagentFormValues = {
  name: string;
  description: string;
  systemPrompt: string;
  modelRef: string;
  skillRefs: string[];
};

export type BuilderFormValues = {
  name: string;
  version: string;
  description: string;
  status: string;
  tags: string[];
  modelRef: string;
  promptSystem: string;
  skillRefs: string[];
  mcpRefs: string[];
  sandboxRef: string;
  interruptOn: string[];
  subagents: SubagentFormValues[];
};

export const BUILDER_STEPS = [
  { key: 'identity', label: 'Identity', iconKey: 'Fingerprint' as const, accent: '#00f0ff', glow: 'rgba(0,240,255,0.20)' },
  { key: 'brain', label: 'Brain', iconKey: 'Brain' as const, accent: '#00f0ff', glow: 'rgba(0,240,255,0.20)' },
  { key: 'capabilities', label: 'Capabilities', iconKey: 'Lightning' as const, accent: '#39ff14', glow: 'rgba(57,255,20,0.20)' },
  { key: 'environment', label: 'Environment', iconKey: 'Server' as const, accent: '#ff2d95', glow: 'rgba(255,45,149,0.20)' },
  { key: 'delegation', label: 'Delegation', iconKey: 'Peoples' as const, accent: '#a855f7', glow: 'rgba(168,85,247,0.20)' },
] as const;

export type StepKey = (typeof BUILDER_STEPS)[number]['key'];

const FIELD_TO_STEP: Record<string, number> = {
  name: 0,
  version: 0,
  description: 0,
  status: 0,
  tags: 0,
  modelRef: 1,
  promptSystem: 1,
  skillRefs: 2,
  mcpRefs: 2,
  sandboxRef: 3,
  interruptOn: 3,
  subagents: 4,
};

export function fieldToStep(field: string): number {
  if (field.startsWith('subagents')) return 4;
  return FIELD_TO_STEP[field] ?? 0;
}

export function toBuildFormValues(agent?: AgentSpecDTO): BuilderFormValues {
  return {
    name: agent?.name ?? '',
    version: agent?.version ?? '',
    description: agent?.description ?? '',
    status: agent?.status ?? 'draft',
    tags: agent?.tags ?? [],
    modelRef: agent?.model_ref ?? '',
    promptSystem: agent?.prompt?.system ?? '',
    skillRefs: agent?.skill_refs ?? [],
    mcpRefs: agent?.mcp_refs ?? [],
    sandboxRef: agent?.sandbox_ref ?? '',
    interruptOn: agent?.interrupt_on ?? [],
    subagents: (agent?.subagents ?? []).map((s) => ({
      name: s.name ?? '',
      description: s.description ?? '',
      systemPrompt: s.system_prompt ?? '',
      modelRef: s.model_ref ?? '',
      skillRefs: s.skill_refs ?? [],
    })),
  };
}

/**
 * Normalize partial form values from Arco's getFieldsValue() —
 * array fields may come back as undefined when untouched.
 */
function safe(values: Partial<BuilderFormValues>): BuilderFormValues {
  return {
    name: values.name ?? '',
    version: values.version ?? '',
    description: values.description ?? '',
    status: values.status ?? 'draft',
    tags: values.tags ?? [],
    modelRef: values.modelRef ?? '',
    promptSystem: values.promptSystem ?? '',
    skillRefs: values.skillRefs ?? [],
    mcpRefs: values.mcpRefs ?? [],
    sandboxRef: values.sandboxRef ?? '',
    interruptOn: values.interruptOn ?? [],
    subagents: values.subagents ?? [],
  };
}

export function toBuildUpsertRequest(raw: Partial<BuilderFormValues>): AgentSpecUpsertRequestDTO {
  const values = safe(raw);
  return {
    version: values.version.trim() || undefined,
    description: values.description.trim() || undefined,
    tags: values.tags.length > 0 ? values.tags : undefined,
    model_ref: values.modelRef.trim() || undefined,
    prompt: { system: values.promptSystem || undefined },
    skill_refs: values.skillRefs.length > 0 ? values.skillRefs : undefined,
    mcp_refs: values.mcpRefs.length > 0 ? values.mcpRefs : undefined,
    sandbox_ref: values.sandboxRef.trim() || undefined,
    subagents:
      values.subagents.length > 0
        ? values.subagents.map((s) => ({
            name: (s.name ?? '').trim() || undefined,
            description: (s.description ?? '').trim() || undefined,
            system_prompt: (s.systemPrompt ?? '').trim() || undefined,
            model_ref: (s.modelRef ?? '').trim() || undefined,
            skill_refs: (s.skillRefs ?? []).length > 0 ? s.skillRefs : undefined,
          }))
        : undefined,
    interrupt_on: values.interruptOn.length > 0 ? values.interruptOn : undefined,
    status: values.status || undefined,
  };
}

export type StepCompletion = {
  complete: boolean;
  summary: string;
};

export function computeStepCompletion(raw: Partial<BuilderFormValues>): StepCompletion[] {
  const values = safe(raw);
  return [
    {
      complete: Boolean(values.name.trim()),
      summary: values.name.trim() || 'unnamed',
    },
    {
      complete: Boolean(values.modelRef.trim()),
      summary: values.modelRef.trim() || 'no model',
    },
    {
      complete: values.skillRefs.length > 0 || values.mcpRefs.length > 0,
      summary: `${values.skillRefs.length} skills, ${values.mcpRefs.length} MCPs`,
    },
    {
      complete: Boolean(values.sandboxRef.trim()),
      summary: values.sandboxRef.trim() || 'no sandbox',
    },
    {
      complete: values.subagents.length > 0,
      summary: `${values.subagents.length} delegate${values.subagents.length !== 1 ? 's' : ''}`,
    },
  ];
}
