import { z } from 'zod';
import type { SkillFileDTO, SubagentSpecDTO } from '@/shared/types/api';

const stringRecordSchema = z.record(z.string());
const skillFileSchema = z.object({
  path: z.string().optional(),
  content: z.string().optional(),
});
const subagentSchema = z.object({
  name: z.string().optional(),
  description: z.string().optional(),
  system_prompt: z.string().optional(),
  model_ref: z.string().optional(),
  skill_refs: z.array(z.string()).optional(),
});

export const authoredStatusOptions = [
  { label: 'draft', value: 'draft' },
  { label: 'published', value: 'published' },
  { label: 'deleted', value: 'deleted' },
] as const;

export function formatMultilineList(values?: string[]): string {
  return (values ?? []).join('\n');
}

export function parseMultilineList(value?: string): string[] {
  return (value ?? '')
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

export function formatJsonValue(value: unknown): string {
  if (
    value === undefined ||
    value === null ||
    (Array.isArray(value) && value.length === 0) ||
    (typeof value === 'object' && !Array.isArray(value) && Object.keys(value as Record<string, unknown>).length === 0)
  ) {
    return '';
  }
  return JSON.stringify(value, null, 2);
}

export function parseOptionalStringMap(value: string, label: string): Record<string, string> | undefined {
  const normalized = value.trim();
  if (!normalized) {
    return undefined;
  }

  try {
    return stringRecordSchema.parse(JSON.parse(normalized));
  } catch (error) {
    const message = error instanceof Error ? error.message : 'invalid json';
    throw new Error(`${label} must be a JSON object<string, string>: ${message}`);
  }
}

export function parseOptionalSkillFiles(value: string): SkillFileDTO[] | undefined {
  const normalized = value.trim();
  if (!normalized) {
    return undefined;
  }

  try {
    return z.array(skillFileSchema).parse(JSON.parse(normalized));
  } catch (error) {
    const message = error instanceof Error ? error.message : 'invalid json';
    throw new Error(`files must be a SkillFile JSON array: ${message}`);
  }
}

export function parseOptionalSubagents(value: string): SubagentSpecDTO[] | undefined {
  const normalized = value.trim();
  if (!normalized) {
    return undefined;
  }

  try {
    return z.array(subagentSchema).parse(JSON.parse(normalized));
  } catch (error) {
    const message = error instanceof Error ? error.message : 'invalid json';
    throw new Error(`subagents must be a SubagentSpec JSON array: ${message}`);
  }
}
