namespace GraphPlatform.Api.Models;

/// <summary>
/// How a configured model authenticates with its provider. Mirrors the Python
/// <c>AuthMode</c> enum in <c>common/schemas/model.py</c>.
/// </summary>
/// <remarks>
/// Serialized to JSON and stored in the database as the lower snake-case value
/// (<c>api_key</c>, <c>managed_identity</c>) so the two stacks agree on the wire and in the shared
/// database. The mapping is applied by one global JSON converter (see <c>Program.cs</c>) and one
/// EF value converter (see <c>Data/Converters.cs</c>) rather than by casing conventions on
/// individual members, so renaming a member here cannot silently change the persisted value.
/// </remarks>
public enum AuthMode
{
    /// <summary>Authenticate using a static API key.</summary>
    ApiKey,

    /// <summary>Authenticate using a cloud-managed identity (no API key needed).</summary>
    ManagedIdentity,
}

/// <summary>
/// A capability a configured model can be used for. Mirrors the Python <c>ModelType</c> enum in
/// <c>common/schemas/model.py</c>; persisted as the lower snake-case value.
/// </summary>
public enum ModelType
{
    /// <summary>The model can compute text embeddings.</summary>
    Embedding,

    /// <summary>The model can process image inputs.</summary>
    Vision,

    /// <summary>The model supports extended/step-by-step reasoning.</summary>
    Thinking,
}

/// <summary>
/// A user's role <em>within one organization</em>. Mirrors ADR-0002, Decision 2's three roles.
/// </summary>
/// <remarks>
/// These are deliberately not ASP.NET Core Identity roles (<c>AspNetRoles</c>): Identity's roles are
/// global per user, while ADR-0002 defines every privilege as evaluated <em>within</em> one
/// organization, so the same user may be an Organization Admin in one organization and a plain User
/// in another. Membership and role therefore live in <see cref="UserOrganization"/>, and the issued
/// JWT carries identity only — see <c>Services/TokenService.cs</c>.
/// </remarks>
public enum OrganizationRole
{
    /// <summary>Every Contributor privilege plus organization governance (ADR-0002, Decision 2).</summary>
    OrganizationAdmin,

    /// <summary>Creates and manages model configs, agents and knowledge bases within the organization.</summary>
    Contributor,

    /// <summary>Read/consumption only: query agents, read graphs and knowledge bases.</summary>
    User,
}