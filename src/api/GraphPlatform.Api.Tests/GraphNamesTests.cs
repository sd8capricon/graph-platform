using GraphPlatform.Api.Services;

namespace GraphPlatform.Api.Tests;

/// <summary>Unit tests for <see cref="GraphNames.ForOrganization"/> (sanitising and the long-id hash fallback).</summary>
public class GraphNamesTests
{
    [Fact]
    public void Lowercases_and_prefixes_a_simple_id()
    {
        Assert.Equal("org_demo_org", GraphNames.ForOrganization("demo-org"));
    }

    [Fact]
    public void Replaces_characters_outside_a_z0_9_underscore_with_underscore()
    {
        var result = GraphNames.ForOrganization("Org 1!@#");

        Assert.Equal("org_org_1___", result);
    }

    [Fact]
    public void Is_case_insensitive()
    {
        Assert.Equal(GraphNames.ForOrganization("ABC"), GraphNames.ForOrganization("abc"));
    }

    [Fact]
    public void A_guid_shaped_id_sanitizes_to_a_valid_identifier_within_the_limit()
    {
        var id = Guid.NewGuid().ToString();

        var result = GraphNames.ForOrganization(id);

        Assert.StartsWith("org_", result);
        Assert.True(result.Length <= GraphNames.MaxIdentifierLength);
        Assert.DoesNotContain('-', result);
    }

    [Fact]
    public void An_id_long_enough_to_exceed_the_identifier_limit_falls_back_to_a_hash()
    {
        var longId = new string('a', 100);

        var result = GraphNames.ForOrganization(longId);

        Assert.StartsWith("org_", result);
        Assert.Equal(4 + 32, result.Length);
        Assert.True(result.Length <= GraphNames.MaxIdentifierLength);
    }

    [Fact]
    public void The_hash_fallback_is_deterministic_and_distinguishes_different_ids()
    {
        var longIdA = new string('a', 100);
        var longIdB = new string('b', 100);

        Assert.Equal(GraphNames.ForOrganization(longIdA), GraphNames.ForOrganization(longIdA));
        Assert.NotEqual(GraphNames.ForOrganization(longIdA), GraphNames.ForOrganization(longIdB));
    }

    [Fact]
    public void Throws_on_a_null_or_blank_id()
    {
        Assert.Throws<ArgumentException>(() => GraphNames.ForOrganization(""));
        Assert.Throws<ArgumentException>(() => GraphNames.ForOrganization("   "));
    }
}
