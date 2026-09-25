import { z } from 'zod'

import { ModelType } from '@/api/types'

const modelTypeSchema = z.enum([
  ModelType.Embedding,
  ModelType.Vision,
  ModelType.Thinking,
])

const baseShape = {
  displayName: z
    .string()
    .trim()
    .min(1, 'Enter a display name.')
    .max(255, 'Use at most 255 characters.'),
  name: z
    .string()
    .trim()
    .min(1, 'Enter the provider’s model name.')
    .max(255, 'Use at most 255 characters.'),
  provider: z
    .string()
    .trim()
    .min(1, 'Enter a provider.')
    .max(255, 'Use at most 255 characters.'),
  connectionString: z.string().trim().max(2048, 'Use at most 2048 characters.').optional(),
  type: z.array(modelTypeSchema).default([]),
  apiKey: z.string().max(4096, 'Use at most 4096 characters.').optional(),
  embeddingDimension: z
    .number({ error: 'Enter a number.' })
    .int('Enter a whole number.')
    .min(1, 'Must be at least 1.')
    .optional(),
  reasoningEffort: z.string().trim().max(255).optional(),
}

type ModelShape = {
  type: ModelType[]
  apiKey?: string
  embeddingDimension?: number
  reasoningEffort?: string
}

/**
 * The cross-field rules the API enforces in `ModelWriteRequest.Validate`. Paths
 * are set explicitly so React Hook Form attaches each message to the input
 * it is about.
 *
 * `requireApiKey` is true when editing a model that already stores one: `PUT`
 * is a full replacement, so an omitted key would silently clear it.
 */
function addCrossFieldRules(value: ModelShape, ctx: z.RefinementCtx, requireApiKey: boolean) {
  if (requireApiKey && !value.apiKey?.trim()) {
    ctx.addIssue({
      code: 'custom',
      path: ['apiKey'],
      message: 'An API key is required.',
    })
  }

  if (value.type.length === 0) {
    ctx.addIssue({
      code: 'custom',
      path: ['type'],
      message: 'Select at least one capability.',
    })
  }

  if (value.type.includes(ModelType.Embedding)) {
    if (value.type.includes(ModelType.Vision) || value.type.includes(ModelType.Thinking)) {
      ctx.addIssue({
        code: 'custom',
        path: ['type'],
        message: 'Embedding cannot be combined with vision or thinking.',
      })
    }
    if (value.embeddingDimension == null) {
      ctx.addIssue({
        code: 'custom',
        path: ['embeddingDimension'],
        message: 'An embedding model must declare its output dimension.',
      })
    }
    if (value.reasoningEffort?.trim()) {
      ctx.addIssue({
        code: 'custom',
        path: ['reasoningEffort'],
        message: 'Reasoning effort does not apply to an embedding model.',
      })
    }
  }
}

/**
 * Shared by create and edit — the API generates the id, so neither form
 * collects one. `apiKey` stays required for an `api_key` model because the
 * API replaces the record wholesale — see `ApiKeyField`.
 */
export const modelEditSchema = z
  .object(baseShape)
  .superRefine((value, ctx) => addCrossFieldRules(value, ctx, true))

export type ModelEditValues = z.input<typeof modelEditSchema>
export type ModelEditParsed = z.output<typeof modelEditSchema>

export const REASONING_EFFORTS = ['low', 'medium', 'high'] as const
