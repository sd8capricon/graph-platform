using GraphPlatform.Api.Services;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.AspNetCore.Mvc.Filters;
using Microsoft.Extensions.Options;

namespace GraphPlatform.Api.Controllers;

/// <summary>
/// Applies <see cref="FileUploadOptions.MaxFileSizeBytes"/> to an upload endpoint's request-body
/// and multipart limits. Apply it with <c>[TypeFilter&lt;FileUploadLimitsFilter&gt;]</c>.
/// </summary>
/// <remarks>
/// A resource filter because it must run before model binding: binding an <c>IFormFile</c> reads the
/// whole form, so an action body would be too late to raise the limits. The
/// <c>[RequestSizeLimit]</c>/<c>[RequestFormLimits]</c> attributes would run early enough but need
/// compile-time constants, and this limit comes from configuration.
/// </remarks>
internal sealed class FileUploadLimitsFilter(IOptions<FileUploadOptions> options) : IResourceFilter
{
    /// <summary>Allowance for multipart boundaries and part headers on top of the file itself.</summary>
    internal const long MultipartOverheadBytes = 64 * 1024;

    /// <inheritdoc />
    public void OnResourceExecuting(ResourceExecutingContext context)
    {
        var limit = options.Value.MaxFileSizeBytes + MultipartOverheadBytes;
        var features = context.HttpContext.Features;

        if (features.Get<IHttpMaxRequestBodySizeFeature>() is { IsReadOnly: false } bodySize)
        {
            bodySize.MaxRequestBodySize = limit;
        }

        features.Set<IFormFeature>(
            new FormFeature(
                context.HttpContext.Request,
                new FormOptions { MultipartBodyLengthLimit = limit }
            )
        );
    }

    /// <inheritdoc />
    public void OnResourceExecuted(ResourceExecutedContext context) { }
}
