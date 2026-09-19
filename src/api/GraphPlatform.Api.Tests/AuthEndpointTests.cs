using System.Net;
using System.Net.Http.Json;
using GraphPlatform.Api.Dtos;
using GraphPlatform.Api.Models;

namespace GraphPlatform.Api.Tests;

/// <summary>
/// Sign-up, login and identity behaviour.
/// </summary>
public class AuthEndpointTests(GraphPlatformApiFactory factory) : IClassFixture<GraphPlatformApiFactory>
{
    [Fact]
    public async Task Signup_creates_account_and_returns_a_usable_token()
    {
        var auth = await factory.SignupAsync();

        Assert.False(string.IsNullOrWhiteSpace(auth.AccessToken));
        Assert.True(auth.ExpiresAtUtc > DateTimeOffset.UtcNow);

        // A user with no memberships yet: privileges are per organization, so sign-up grants none.
        Assert.Empty(auth.User.Organizations);

        using var client = factory.AuthedClient(auth.AccessToken);
        var me = await client.GetAsync("/api/auth/me");

        Assert.Equal(HttpStatusCode.OK, me.StatusCode);
    }

    [Fact]
    public async Task Signup_rejects_a_duplicate_email_with_conflict()
    {
        var email = Api.UniqueEmail();
        await factory.SignupAsync(email);

        using var client = factory.AnonymousClient();
        var response = await client.PostAsJsonAsync(
            "/api/auth/signup",
            new SignupRequest { Email = email, Password = "correct-horse-battery" },
            Api.Json
        );

        Assert.Equal(HttpStatusCode.Conflict, response.StatusCode);
    }

    [Fact]
    public async Task Signup_rejects_a_short_password_with_a_validation_problem()
    {
        using var client = factory.AnonymousClient();
        var response = await client.PostAsJsonAsync(
            "/api/auth/signup",
            new SignupRequest { Email = Api.UniqueEmail(), Password = "short" },
            Api.Json
        );

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Login_returns_a_token_for_valid_credentials()
    {
        var email = Api.UniqueEmail();
        const string password = "correct-horse-battery";
        await factory.SignupAsync(email, password);

        using var client = factory.AnonymousClient();
        var response = await client.PostAsJsonAsync(
            "/api/auth/login",
            new LoginRequest { Email = email, Password = password },
            Api.Json
        );

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        var auth = (await response.Content.ReadFromJsonAsync<AuthResponse>(Api.Json))!;
        Assert.False(string.IsNullOrWhiteSpace(auth.AccessToken));
        Assert.Equal(email, auth.User.Email);
    }

    [Fact]
    public async Task Login_rejects_a_wrong_password_with_unauthorized()
    {
        var email = Api.UniqueEmail();
        await factory.SignupAsync(email, "correct-horse-battery");

        using var client = factory.AnonymousClient();
        var response = await client.PostAsJsonAsync(
            "/api/auth/login",
            new LoginRequest { Email = email, Password = "definitely-not-it" },
            Api.Json
        );

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Login_does_not_disclose_whether_an_account_exists()
    {
        var email = Api.UniqueEmail();
        await factory.SignupAsync(email, "correct-horse-battery");

        using var existingAccount = factory.AnonymousClient();
        var wrongPassword = await existingAccount.PostAsJsonAsync(
            "/api/auth/login",
            new LoginRequest { Email = email, Password = "definitely-not-it" },
            Api.Json
        );

        using var unknownAccount = factory.AnonymousClient();
        var noSuchUser = await unknownAccount.PostAsJsonAsync(
            "/api/auth/login",
            new LoginRequest { Email = Api.UniqueEmail(), Password = "definitely-not-it" },
            Api.Json
        );

        Assert.Equal(HttpStatusCode.Unauthorized, wrongPassword.StatusCode);
        Assert.Equal(HttpStatusCode.Unauthorized, noSuchUser.StatusCode);
        Assert.Equal(
            await wrongPassword.Content.ReadAsStringAsync(),
            await noSuchUser.Content.ReadAsStringAsync()
        );
    }

    [Fact]
    public async Task Anonymous_requests_are_rejected()
    {
        using var client = factory.AnonymousClient();

        var me = await client.GetAsync("/api/auth/me");
        var organizations = await client.GetAsync("/api/organizations");

        Assert.Equal(HttpStatusCode.Unauthorized, me.StatusCode);
        Assert.Equal(HttpStatusCode.Unauthorized, organizations.StatusCode);
    }

    [Fact]
    public async Task Me_reports_the_organizations_the_user_belongs_to()
    {
        var auth = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(auth.AccessToken);

        using var client = factory.AuthedClient(auth.AccessToken);
        var me = (await client.GetFromJsonAsync<UserDto>("/api/auth/me", Api.Json))!;

        var membership = Assert.Single(me.Organizations);
        Assert.Equal(organization.Id, membership.OrganizationId);
        Assert.Equal(organization.Name, membership.OrganizationName);

        // Creating an organization makes the creator its Organization Admin (ADR-0002, Decision 2).
        Assert.Equal(OrganizationRole.OrganizationAdmin, membership.Role);
    }

    [Fact]
    public async Task Password_material_is_never_returned()
    {
        const string password = "correct-horse-battery";
        var auth = await factory.SignupAsync(password: password);

        using var client = factory.AuthedClient(auth.AccessToken);
        var body = await client.GetStringAsync("/api/auth/me");

        Assert.DoesNotContain(password, body, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("passwordHash", body, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("securityStamp", body, StringComparison.OrdinalIgnoreCase);
    }
}