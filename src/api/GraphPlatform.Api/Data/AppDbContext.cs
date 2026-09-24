using GraphPlatform.Api.Models;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Identity.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore;

namespace GraphPlatform.Api.Data;

/// <summary>
/// The API's Entity Framework Core context: ASP.NET Core Identity's tables plus the organization,
/// membership and model-config tables this API owns.
/// </summary>
/// <remarks>
/// <para>
/// This context knows <em>nothing</em> about the Python <c>common</c> project's tables
/// (<c>graph_registry</c>, <c>node_embedding</c>, <c>schema_embedding</c>) or Apache Age's
/// <c>ag_catalog</c>. Both stacks share one PostgreSQL database, so keeping this context's model
/// limited to the tables it owns is what stops a migration here from altering or dropping a table
/// Python created with <c>Base.metadata.create_all</c>.
/// </para>
/// <para>
/// Identity's own tables keep their default <c>AspNet*</c> names. In particular there is no
/// <c>AspNetRoles</c> usage: ADR-0002's roles are per organization, which Identity's global role
/// model cannot express — see <see cref="OrganizationRole"/>.
/// </para>
/// </remarks>
/// <param name="options">Context options supplied by dependency injection.</param>
public class AppDbContext(DbContextOptions<AppDbContext> options) : IdentityDbContext<AppUser>(options)
{
    /// <summary>
    /// Name of the configuration entry holding the Npgsql connection string, under the standard
    /// <c>ConnectionStrings</c> section — i.e. the key <c>ConnectionStrings:PgConnectionString</c>.
    /// </summary>
    /// <remarks>
    /// The context owns the key name because it owns the connection: both the web host
    /// (<c>Program.cs</c>) and the design-time factory read the value straight from configuration
    /// with this constant, so a rename cannot drift between them.
    /// </remarks>
    public const string ConnectionStringName = "PgConnectionString";

    /// <summary>Organizations, the tenancy boundary (ADR-0002, Decision 1).</summary>
    public DbSet<Organization> Organizations => Set<Organization>();

    /// <summary>Per-organization user memberships and roles.</summary>
    public DbSet<UserOrganization> UserOrganizations => Set<UserOrganization>();

    /// <summary>Configured LLM/embedding provider connections, owned by one organization each.</summary>
    public DbSet<ModelConfig> ModelConfigs => Set<ModelConfig>();

    /// <inheritdoc />
    protected override void OnModelCreating(ModelBuilder builder)
    {
        base.OnModelCreating(builder);

        // Identity's global role model is deliberately unused (see the remarks on this class and on
        // OrganizationRole), so its tables are kept out of the schema entirely rather than created
        // empty in a database shared with the Python services. Nothing resolves a role store, because
        // AddIdentityCore without AddRoles leaves IdentityBuilder.RoleType null. Adding Identity roles
        // later means deleting these three ignores and adding a migration that creates the tables back.
        builder.Ignore<IdentityRole>();
        builder.Ignore<IdentityUserRole<string>>();
        builder.Ignore<IdentityRoleClaim<string>>();

        builder.Entity<Organization>(organization =>
        {
            organization.ToTable("organization");
            organization.HasKey(entity => entity.Id);
            organization.Property(entity => entity.Id).HasMaxLength(Organization.IdMaxLength);
            organization
                .Property(entity => entity.Name)
                .HasMaxLength(Organization.NameMaxLength)
                .IsRequired();
            organization.Property(entity => entity.CreatedAtUtc).IsRequired();
            organization
                .Property(entity => entity.ActiveEmbeddingModelId)
                .HasMaxLength(Organization.IdMaxLength);

            // Names are how a human addresses an organization, so two organizations sharing one would
            // be an operational trap (and would make "add member by name" ambiguous later).
            organization.HasIndex(entity => entity.Name).IsUnique();

            // The active embedding model is a governance setting, not ownership: deleting the model
            // config must not delete the organization. The API additionally refuses to delete a model
            // that is currently active (409), so this SET NULL is a backstop, not the normal path.
            organization
                .HasOne<ModelConfig>()
                .WithMany()
                .HasForeignKey(entity => entity.ActiveEmbeddingModelId)
                .OnDelete(DeleteBehavior.SetNull);
        });

        builder.Entity<UserOrganization>(membership =>
        {
            membership.ToTable("user_organization");

            // Composite key, not a surrogate id: the same user twice in the same organization is
            // never a valid row, so let the database enforce it.
            membership.HasKey(entity => new { entity.UserId, entity.OrganizationId });
            membership
                .Property(entity => entity.Role)
                .HasMaxLength(Converters.EnumMaxLength)
                .HasConversion(Converters.SnakeCaseEnum<OrganizationRole>())
                .IsRequired();
            membership.Property(entity => entity.JoinedAtUtc).IsRequired();
            membership.HasIndex(entity => entity.OrganizationId);

            membership
                .HasOne(entity => entity.User)
                .WithMany(user => user.Organizations)
                .HasForeignKey(entity => entity.UserId)
                .OnDelete(DeleteBehavior.Cascade);

            membership
                .HasOne(entity => entity.Organization)
                .WithMany(organization => organization.Members)
                .HasForeignKey(entity => entity.OrganizationId)
                .OnDelete(DeleteBehavior.Cascade);
        });

        builder.Entity<ModelConfig>(model =>
        {
            model.ToTable("model_config");
            model.HasKey(entity => entity.Id);
            model.Property(entity => entity.Id).HasMaxLength(ModelConfig.IdMaxLength);
            model
                .Property(entity => entity.OrganizationId)
                .HasMaxLength(Organization.IdMaxLength)
                .IsRequired();
            model
                .Property(entity => entity.DisplayName)
                .HasMaxLength(ModelConfig.NameMaxLength)
                .IsRequired();
            model
                .Property(entity => entity.Name)
                .HasMaxLength(ModelConfig.NameMaxLength)
                .IsRequired();
            model
                .Property(entity => entity.Provider)
                .HasMaxLength(ModelConfig.NameMaxLength)
                .IsRequired();
            model
                .Property(entity => entity.AuthMode)
                .HasMaxLength(Converters.EnumMaxLength)
                .HasConversion(Converters.SnakeCaseEnum<AuthMode>())
                .IsRequired();
            model.Property(entity => entity.ReasoningEffort).HasMaxLength(ModelConfig.NameMaxLength);
            model.Property(entity => entity.CreatedAtUtc).IsRequired();
            model.Property(entity => entity.UpdatedAtUtc).IsRequired();
            model.HasIndex(entity => entity.OrganizationId);

            // jsonb, matching the "one JSON column per list" convention the Python models use for
            // graph_registry.knowledge_base_ids. A jsonb column cannot be indexed or compared the way
            // a text column can, but nothing queries into this list today.
            model
                .Property(entity => entity.Type)
                .HasConversion(Converters.ModelTypeList(), Converters.ModelTypeListComparer)
                .HasColumnType("jsonb")
                .IsRequired();

            // Every model config is owned by exactly one organization, so an organization delete
            // takes its model configs with it (ADR-0002, Decision 1).
            model
                .HasOne(entity => entity.Organization)
                .WithMany(organization => organization.Models)
                .HasForeignKey(entity => entity.OrganizationId)
                .OnDelete(DeleteBehavior.Cascade);
        });
    }
}