/**
 * The one query-key factory.
 *
 * Everything organization-scoped nests under that organization's detail key, so
 * a single `invalidateQueries` can drop an organization's whole subtree. Keys
 * are never written inline at a call site.
 */
export const qk = {
  auth: {
    me: () => ['auth', 'me'] as const,
  },

  orgs: {
    all: () => ['orgs'] as const,
    list: () => ['orgs', 'list'] as const,
    detail: (organizationId: string) => ['orgs', 'detail', organizationId] as const,
    members: (organizationId: string) =>
      ['orgs', 'detail', organizationId, 'members'] as const,
  },

  models: {
    all: (organizationId: string) =>
      ['orgs', 'detail', organizationId, 'models'] as const,
    list: (organizationId: string) =>
      ['orgs', 'detail', organizationId, 'models', 'list'] as const,
    detail: (organizationId: string, modelId: string) =>
      ['orgs', 'detail', organizationId, 'models', 'detail', modelId] as const,
  },

  knowledgeBases: {
    all: (organizationId: string) => ['orgs', 'detail', organizationId, 'kbs'] as const,
    list: (organizationId: string) =>
      ['orgs', 'detail', organizationId, 'kbs', 'list'] as const,
    detail: (organizationId: string, knowledgeBaseId: string) =>
      ['orgs', 'detail', organizationId, 'kbs', 'detail', knowledgeBaseId] as const,
    files: (organizationId: string, knowledgeBaseId: string) =>
      ['orgs', 'detail', organizationId, 'kbs', 'detail', knowledgeBaseId, 'files'] as const,
  },
} as const
