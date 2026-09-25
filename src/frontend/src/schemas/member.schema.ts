import { z } from 'zod'

import { OrganizationRole } from '@/api/types'

const roleSchema = z.enum([
  OrganizationRole.OrganizationAdmin,
  OrganizationRole.Contributor,
  OrganizationRole.User,
])

export const addMemberSchema = z.object({
  email: z.email('Enter a valid email address.').max(256),
  role: roleSchema,
})

export type AddMemberValues = z.infer<typeof addMemberSchema>
