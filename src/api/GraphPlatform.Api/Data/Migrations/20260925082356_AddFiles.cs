using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace GraphPlatform.Api.Data.Migrations
{
    /// <inheritdoc />
    public partial class AddFiles : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "file",
                columns: table => new
                {
                    Id = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: false),
                    OrganizationId = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: false),
                    FileName = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: false),
                    ContentType = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: false),
                    Size = table.Column<long>(type: "bigint", nullable: false),
                    StorageKey = table.Column<string>(type: "character varying(1024)", maxLength: 1024, nullable: false),
                    Status = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    CreatedAtUtc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    UpdatedAtUtc = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_file", x => x.Id);
                    table.ForeignKey(
                        name: "FK_file_organization_OrganizationId",
                        column: x => x.OrganizationId,
                        principalTable: "organization",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "knowledge_base_file",
                columns: table => new
                {
                    FileId = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: false),
                    KnowledgeBaseId = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_knowledge_base_file", x => x.FileId);
                    table.ForeignKey(
                        name: "FK_knowledge_base_file_file_FileId",
                        column: x => x.FileId,
                        principalTable: "file",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_knowledge_base_file_knowledge_base_KnowledgeBaseId",
                        column: x => x.KnowledgeBaseId,
                        principalTable: "knowledge_base",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_file_OrganizationId",
                table: "file",
                column: "OrganizationId");

            migrationBuilder.CreateIndex(
                name: "IX_file_StorageKey",
                table: "file",
                column: "StorageKey",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_knowledge_base_file_KnowledgeBaseId",
                table: "knowledge_base_file",
                column: "KnowledgeBaseId");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "knowledge_base_file");

            migrationBuilder.DropTable(
                name: "file");
        }
    }
}
