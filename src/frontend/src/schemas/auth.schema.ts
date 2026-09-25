import { z } from 'zod'

/** Mirrors the API's `SignupRequest`/`LoginRequest` DataAnnotations. */
export const loginSchema = z.object({
  email: z.email('Enter a valid email address.').max(256),
  password: z.string().min(1, 'Enter your password.').max(128),
})

export type LoginValues = z.infer<typeof loginSchema>

export const signupSchema = z.object({
  email: z.email('Enter a valid email address.').max(256),
  password: z
    .string()
    .min(8, 'Use at least 8 characters.')
    .max(128, 'Use at most 128 characters.'),
  displayName: z.string().max(255, 'Use at most 255 characters.').optional(),
})

export type SignupValues = z.infer<typeof signupSchema>
