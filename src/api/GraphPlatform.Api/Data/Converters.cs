using System.Text.Json;
using GraphPlatform.Api.Models;
using Microsoft.EntityFrameworkCore.ChangeTracking;
using Microsoft.EntityFrameworkCore.Storage.ValueConversion;

namespace GraphPlatform.Api.Data;

/// <summary>
/// The value converters that keep this API's persisted values byte-identical to the Python
/// <c>common</c> project's, so both stacks can read the same database rows.
/// </summary>
/// <remarks>
/// Enums are the whole reason this type exists. C# members are PascalCase (<c>ApiKey</c>) while
/// Python's are lower snake-case (<c>api_key</c>), so EF's default <c>HasConversion&lt;string&gt;()</c>
/// — which persists <c>ToString()</c> — would write <c>ApiKey</c> into a column Python reads as
/// <c>api_key</c>. One shared mapping function is used for storage here and for JSON in
/// <c>Program.cs</c>, so the persisted value, the wire value and the Python value cannot drift apart.
/// </remarks>
internal static class Converters
{
    private static readonly JsonSerializerOptions SerializerOptions = new(JsonSerializerDefaults.Web);

    /// <summary>Length of the longest persisted enum value.</summary>
    public const int EnumMaxLength = 32;

    /// <summary>
    /// Renders an enum member the way Python spells it: lower snake-case.
    /// </summary>
    /// <typeparam name="TEnum">The enum type.</typeparam>
    /// <param name="value">The member to render.</param>
    /// <returns>The lower snake-case name (e.g. <c>ApiKey</c> becomes <c>"api_key"</c>).</returns>
    public static string ToSnakeCase<TEnum>(TEnum value)
        where TEnum : struct, Enum =>
        JsonNamingPolicy.SnakeCaseLower.ConvertName(value.ToString()!);

    /// <summary>
    /// Parses a lower snake-case enum name back into its member.
    /// </summary>
    /// <typeparam name="TEnum">The enum type.</typeparam>
    /// <param name="value">A persisted value such as <c>"managed_identity"</c>.</param>
    /// <returns>The matching enum member.</returns>
    /// <exception cref="InvalidOperationException">
    /// Thrown when the stored value matches no member — an unknown value is a data problem worth
    /// surfacing rather than silently mapping to a default.
    /// </exception>
    public static TEnum FromSnakeCase<TEnum>(string value)
        where TEnum : struct, Enum
    {
        foreach (var candidate in Enum.GetValues<TEnum>())
        {
            if (string.Equals(ToSnakeCase(candidate), value, StringComparison.Ordinal))
            {
                return candidate;
            }
        }

        throw new InvalidOperationException(
            $"'{value}' is not a known persisted value of {typeof(TEnum).Name}."
        );
    }

    /// <summary>Builds the snake-case string converter for one enum property.</summary>
    /// <typeparam name="TEnum">The enum type.</typeparam>
    /// <returns>A converter mapping the enum to and from its Python spelling.</returns>
    public static ValueConverter<TEnum, string> SnakeCaseEnum<TEnum>()
        where TEnum : struct, Enum =>
        new(value => ToSnakeCase(value), value => FromSnakeCase<TEnum>(value));

    /// <summary>
    /// Builds the converter for <see cref="ModelConfig.Type"/>: a JSON array of snake-case names.
    /// </summary>
    /// <returns>A converter mapping the capability list to and from its JSON text.</returns>
    public static ValueConverter<List<ModelType>, string> ModelTypeList() =>
        new(
            types => JsonSerializer.Serialize(types.Select(ToSnakeCase).ToList(), SerializerOptions),
            json =>
                string.IsNullOrWhiteSpace(json)
                    ? new List<ModelType>()
                    : JsonSerializer
                        .Deserialize<List<string>>(json, SerializerOptions)!
                        .Select(FromSnakeCase<ModelType>)
                        .ToList()
        );

    /// <summary>
    /// Snapshot comparer for <see cref="ModelConfig.Type"/>.
    /// </summary>
    /// <remarks>
    /// EF needs this explicitly for a mutable collection mapped through a value converter: without
    /// it, changing the list in place is invisible to change tracking, because the converter's
    /// reference-equality snapshot still looks identical.
    /// </remarks>
    public static readonly ValueComparer<List<ModelType>> ModelTypeListComparer = new(
        (left, right) => left!.SequenceEqual(right!),
        types => types.Aggregate(0, (hash, type) => HashCode.Combine(hash, type.GetHashCode())),
        types => types.ToList()
    );
}