using System.Security.Cryptography;
using System.Text;

namespace GraphPlatform.Api.Services;

/// <summary>
/// Computes the Apache Age graph name an organization's Knowledge Bases ingest into.
/// </summary>
/// <remarks>
/// <para>
/// Only the API computes this, at publish time (<c>KnowledgeBasesController.PublishKnowledgeBase</c>
/// stamps it onto <c>IndexJob.GraphName</c>); the Python ingestion worker only ever reads
/// <c>index_job.graph_name</c> back off the row it claims, so the two stacks cannot disagree about
/// which graph a job targets even though only one of them derives the name.
/// </para>
/// <para>
/// PostgreSQL identifiers (what Apache Age uses to name a graph's backing schema) are limited to 63
/// bytes, so a long or unusual organization id is hashed down instead of truncated — truncation could
/// collide two organizations whose ids share a long common prefix, while a SHA-256 hash does not.
/// </para>
/// </remarks>
public static class GraphNames
{
    private const string Prefix = "org_";

    /// <summary>PostgreSQL's identifier length limit, in bytes.</summary>
    public const int MaxIdentifierLength = 63;

    /// <summary>
    /// Builds the graph name for one organization.
    /// </summary>
    /// <param name="organizationId">The organization's id.</param>
    /// <returns>
    /// <c>"org_"</c> plus the lower-cased id with every character outside <c>[a-z0-9_]</c> replaced
    /// by <c>_</c>, or — when that would exceed <see cref="MaxIdentifierLength"/> — <c>"org_"</c>
    /// plus the first 32 hex characters of the SHA-256 hash of <paramref name="organizationId"/>.
    /// </returns>
    public static string ForOrganization(string organizationId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(organizationId);

        var sanitized = Sanitize(organizationId);
        var candidate = Prefix + sanitized;
        if (candidate.Length <= MaxIdentifierLength)
        {
            return candidate;
        }

        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(organizationId));
        var hex = Convert.ToHexStringLower(hash)[..32];
        return Prefix + hex;
    }

    private static string Sanitize(string organizationId)
    {
        var builder = new StringBuilder(organizationId.Length);
        foreach (var ch in organizationId.ToLowerInvariant())
        {
            builder.Append(ch is (>= 'a' and <= 'z') or (>= '0' and <= '9') or '_' ? ch : '_');
        }

        return builder.ToString();
    }
}
