using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace GraphPlatform.Api.Data.Migrations
{
    /// <inheritdoc />
    public partial class AddIndexJobKind : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            // Every job created before this column existed was a publish; the default backfills
            // them and matches the worker mapping's server default.
            migrationBuilder.AddColumn<string>(
                name: "kind",
                table: "index_job",
                type: "character varying(32)",
                maxLength: 32,
                nullable: false,
                defaultValue: "publish");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "kind",
                table: "index_job");
        }
    }
}
