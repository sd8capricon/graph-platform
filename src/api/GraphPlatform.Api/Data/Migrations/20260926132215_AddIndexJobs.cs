using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace GraphPlatform.Api.Data.Migrations
{
    /// <inheritdoc />
    public partial class AddIndexJobs : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "index_job",
                columns: table => new
                {
                    id = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: false),
                    organization_id = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: false),
                    knowledge_base_id = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: false),
                    graph_name = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: false),
                    status = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    total_files = table.Column<int>(type: "integer", nullable: false, defaultValue: 0),
                    processed_files = table.Column<int>(type: "integer", nullable: false, defaultValue: 0),
                    failed_files = table.Column<int>(type: "integer", nullable: false, defaultValue: 0),
                    graph_dispatched = table.Column<bool>(type: "boolean", nullable: false, defaultValue: false),
                    embedding_model_id = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: true),
                    requested_by = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: true),
                    error = table.Column<string>(type: "text", nullable: true),
                    created_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: false),
                    started_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    completed_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_index_job", x => x.id);
                    table.ForeignKey(
                        name: "FK_index_job_knowledge_base_knowledge_base_id",
                        column: x => x.knowledge_base_id,
                        principalTable: "knowledge_base",
                        principalColumn: "Id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "index_file",
                columns: table => new
                {
                    id = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: false),
                    index_job_id = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: false),
                    file_id = table.Column<string>(type: "character varying(255)", maxLength: 255, nullable: false),
                    status = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    attempts = table.Column<int>(type: "integer", nullable: false, defaultValue: 0),
                    error = table.Column<string>(type: "text", nullable: true),
                    started_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true),
                    completed_at = table.Column<DateTimeOffset>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_index_file", x => x.id);
                    table.ForeignKey(
                        name: "FK_index_file_index_job_index_job_id",
                        column: x => x.index_job_id,
                        principalTable: "index_job",
                        principalColumn: "id",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_index_file_index_job_id",
                table: "index_file",
                column: "index_job_id");

            migrationBuilder.CreateIndex(
                name: "IX_index_job_knowledge_base_id",
                table: "index_job",
                column: "knowledge_base_id");

            migrationBuilder.CreateIndex(
                name: "IX_index_job_KnowledgeBaseId_Active",
                table: "index_job",
                column: "knowledge_base_id",
                unique: true,
                filter: "status IN ('queued','running')");

            migrationBuilder.CreateIndex(
                name: "IX_index_job_organization_id",
                table: "index_job",
                column: "organization_id");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "index_file");

            migrationBuilder.DropTable(
                name: "index_job");
        }
    }
}
