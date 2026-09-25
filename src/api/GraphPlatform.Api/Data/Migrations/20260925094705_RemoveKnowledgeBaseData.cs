using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace GraphPlatform.Api.Data.Migrations
{
    /// <inheritdoc />
    public partial class RemoveKnowledgeBaseData : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "Data",
                table: "knowledge_base");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "Data",
                table: "knowledge_base",
                type: "jsonb",
                nullable: false,
                defaultValue: "");
        }
    }
}
