/**
 * Wire types for the GraphPlatform management API.
 *
 * Properties are camelCase (ASP.NET Core's web defaults) while enum values are
 * lower snake_case strings, matching the Python services exactly. Enums are
 * modelled as a const object plus a derived union because `erasableSyntaxOnly`
 * forbids TypeScript `enum`; the object also gives a runtime list for rendering
 * options and for `z.enum(...)`.
 */

export const OrganizationRole = {
  OrganizationAdmin: 'organization_admin',
  Contributor: 'contributor',
  User: 'user',
} as const
export type OrganizationRole = (typeof OrganizationRole)[keyof typeof OrganizationRole]

export const AuthMode = {
  ApiKey: 'api_key',
  ManagedIdentity: 'managed_identity',
} as const
export type AuthMode = (typeof AuthMode)[keyof typeof AuthMode]

export const ModelType = {
  Embedding: 'embedding',
  Vision: 'vision',
  Thinking: 'thinking',
} as const
export type ModelType = (typeof ModelType)[keyof typeof ModelType]

export const KnowledgeBaseState = {
  Draft: 'draft',
  Indexing: 'indexing',
  Published: 'published',
  Failed: 'failed',
} as const
export type KnowledgeBaseState =
  (typeof KnowledgeBaseState)[keyof typeof KnowledgeBaseState]

export const FileStatus = {
  Uploaded: 'uploaded',
  Processing: 'processing',
  Processed: 'processed',
  Failed: 'failed',
} as const
export type FileStatus = (typeof FileStatus)[keyof typeof FileStatus]

/* -------------------------------------------------------------------------- */
/* Auth                                                                        */
/* -------------------------------------------------------------------------- */

export interface MembershipDto {
  organizationId: string
  organizationName: string
  role: OrganizationRole
}

export interface UserDto {
  id: string
  email: string | null
  displayName: string | null
  createdAtUtc: string
  organizations: MembershipDto[]
}

export interface AuthResponse {
  accessToken: string
  expiresAtUtc: string
  user: UserDto
}

export interface LoginRequest {
  email: string
  password: string
}

export interface SignupRequest {
  email: string
  password: string
  displayName?: string | null
}

/* -------------------------------------------------------------------------- */
/* Organizations and members                                                   */
/* -------------------------------------------------------------------------- */

export interface OrganizationDto {
  id: string
  name: string
  createdAtUtc: string
  activeEmbeddingModelId: string | null
}

export interface CreateOrganizationRequest {
  name: string
}

export type UpdateOrganizationRequest = CreateOrganizationRequest

export interface MemberDto {
  userId: string
  email: string | null
  displayName: string | null
  role: OrganizationRole
  joinedAtUtc: string
}

export interface AddMemberRequest {
  email: string
  role: OrganizationRole
}

export interface UpdateMemberRoleRequest {
  role: OrganizationRole
}

export interface SetActiveEmbeddingModelRequest {
  /** `null` clears the organization's active embedding model. */
  modelId: string | null
}

/* -------------------------------------------------------------------------- */
/* Model configurations                                                        */
/* -------------------------------------------------------------------------- */

export interface ModelDto {
  id: string
  organizationId: string
  displayName: string
  name: string
  provider: string
  connectionString: string | null
  authMode: AuthMode
  type: ModelType[]
  embeddingDimension: number | null
  reasoningEffort: string | null
  /** The stored key itself is never returned by the API. */
  hasApiKey: boolean
  createdAtUtc: string
  updatedAtUtc: string
}

export interface ModelWriteRequest {
  displayName: string
  name: string
  provider: string
  connectionString?: string | null
  type: ModelType[]
  /** Always required: the API only supports API-key authentication. */
  apiKey?: string | null
  embeddingDimension?: number | null
  reasoningEffort?: string | null
}

export interface CreateModelRequest extends ModelWriteRequest {
  /** Omit to let the API generate a UUID. */
  id?: string | null
}

export type UpdateModelRequest = ModelWriteRequest

/* -------------------------------------------------------------------------- */
/* Knowledge bases and files                                                   */
/* -------------------------------------------------------------------------- */

export interface FileDto {
  id: string
  fileName: string
  contentType: string
  size: number
  status: FileStatus
  createdAtUtc: string
  updatedAtUtc: string
}

export interface KnowledgeBaseDto {
  id: string
  organizationId: string
  name: string
  files: FileDto[]
  state: KnowledgeBaseState
  createdAtUtc: string
  updatedAtUtc: string
}

export interface CreateKnowledgeBaseRequest {
  name: string
  /** Omit to let the API generate a UUID. */
  id?: string | null
}

export interface UpdateKnowledgeBaseRequest {
  name: string
}
