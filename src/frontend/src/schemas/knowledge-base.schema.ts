import { z } from 'zod'

export const knowledgeBaseNameSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, 'Enter a name.')
    .max(255, 'Use at most 255 characters.'),
})

export type KnowledgeBaseNameValues = z.infer<typeof knowledgeBaseNameSchema>
