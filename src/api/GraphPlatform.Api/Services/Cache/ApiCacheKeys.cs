using System.Security.Cryptography;
using System.Text;

namespace GraphPlatform.Api.Services.Cache;

/// <summary>
/// Versioned key contract shared with the Python ingestion worker. Component
/// hashes prevent ids from introducing separators or leaking raw identifiers.
/// </summary>
public static class ApiCacheKeys
{
    /// <summary>The namespace shared with ingestion_worker.cache.</summary>
    public const string Namespace = "graph-platform:api:v1";

    /// <summary>Organization's model-config collection.</summary>
    public static string Models(string organizationId) =>
        $"{Namespace}:org:{Hash(organizationId)}:models";

    /// <summary>One model config.</summary>
    public static string Model(string organizationId, string modelId) =>
        $"{Namespace}:org:{Hash(organizationId)}:model:{Hash(modelId)}";

    /// <summary>Organization's Knowledge Base collection.</summary>
    public static string KnowledgeBases(string organizationId) =>
        $"{Namespace}:org:{Hash(organizationId)}:knowledge-bases";

    /// <summary>One Knowledge Base read model.</summary>
    public static string KnowledgeBase(string organizationId, string knowledgeBaseId) =>
        $"{Namespace}:org:{Hash(organizationId)}:knowledge-base:{Hash(knowledgeBaseId)}";

    /// <summary>One ingestion job's status read model.</summary>
    public static string IndexJob(string organizationId, string knowledgeBaseId, string jobId) =>
        $"{Namespace}:org:{Hash(organizationId)}:knowledge-base:{Hash(knowledgeBaseId)}:index-job:{Hash(jobId)}";

    private static string Hash(string value) =>
        Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(value))).ToLowerInvariant();
}
