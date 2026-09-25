import { z } from 'zod'

import { AuthMode, ModelType } from '@/api/types'
import { isUuid } from '@/lib/uuid'

const authModeSchema = z.enum([AuthMode.ApiKey, AuthMode.ManagedIdentity])
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
  authMode: authModeSchema,
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
  authMode: AuthMode
  type: ModelType[]
  apiKey?: string
  embeddingDimension?: number
  reasoningEffort?: string
}

/**
 * The three cross-field rules the API enforces in `ModelWriteRequest.Validate`.
 * Paths are set explicitly so React Hook Form attaches each message to the
 * input it is about.
 *
 * `requireApiKey` is true when editing a model that already stores one: `PUT`
 * is a full replacement, so an omitted key would silently clear it.
 */
function addCrossFieldRules(value: ModelShape, ctx: z.RefinementCtx, requireApiKey: boolean) {
  if (value.authMode === AuthMode.ApiKey && requireApiKey && !value.apiKey?.trim()) {
    ctx.addIssue({
      code: 'custom',
      path: ['apiKey'],
      message: 'An API key is required when the auth mode is “API key”.',
    })
  }

  if (value.type.includes(ModelType.Embedding)) {
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

export const modelCreateSchema = z
  .object({
    ...baseShape,
    id: z
      .string()
      .trim()
      .min(1, 'Enter an id.')
      .refine(isUuid, 'The id must be a valid UUID.'),
  })
  .superRefine((value, ctx) => addCrossFieldRules(value, ctx, true))

export type ModelCreateValues = z.input<typeof modelCreateSchema>
export type ModelCreateParsed = z.output<typeof modelCreateSchema>

/**
 * Editing uses the same rules. `apiKey` stays required for an `api_key` model
 * because the API replaces the record wholesale — see `ApiKeyField`.
 */
export const modelEditSchema = z
  .object(baseShape)
  .superRefine((value, ctx) => addCrossFieldRules(value, ctx, true))

export type ModelEditValues = z.input<typeof modelEditSchema>
export type ModelEditParsed = z.output<typeof modelEditSchema>

export const REASONING_EFFORTS = ['low', 'medium', 'high'] as const
