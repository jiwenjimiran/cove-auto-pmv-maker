using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using Cove.Core.Entities;
using Cove.Core.Enums;
using Cove.Core.Auth;
using Cove.Core.Interfaces;
using Cove.Data;
using Cove.Plugins;
using Cove.Sdk;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.AspNetCore.Routing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;

namespace Cove.PmvMaker;

public sealed class PmvMakerExtension : IExtension, IUIExtension, IApiExtension, IStatefulExtension
{
    public const string ExtensionId = "io.github.jiwenjimiran.auto-pmv-maker";
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private static readonly HashSet<string> AudioUploadExtensions = new(StringComparer.OrdinalIgnoreCase)
        { ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".aiff" };
    private const long MaxAudioUploadBytes = 200L * 1024 * 1024;
    private IExtensionStore? _store;
    private IExtensionServiceScopeFactory? _scopes;
    private LocalCompanion? _local;
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(20) };

    public string Id => ExtensionId;
    public string Name => "Auto PMV Maker";
    public string Version => "0.1.16";
    public string? Description => "Song-led DaVinci Resolve Studio PMVs for Cove.";
    public string? Author => "jiwenji";
    public string? Url => null;
    public string? IconUrl => null;
    public string? MinCoveVersion => "1.5.1";
    public IReadOnlyList<string> Categories => ["video", "automation", "tools"];

    public void ConfigureServices(IServiceCollection services, ExtensionContext context)
    {
        services.AddScoped<SourceResolver>();
        _local ??= new LocalCompanion(Path.Combine(context.DataDirectory, ExtensionId, "companion", "AutoPmvMakerCompanion.zip"));
    }
    public void SetStore(IExtensionStore store) => _store = store;
    public async Task InitializeAsync(IServiceProvider services, CancellationToken ct = default)
    {
        _scopes = services.GetRequiredService<IExtensionServiceScopeFactory>();
        if ((await SettingsAsync(ct)).CompanionMode == "auto" && _local is not null)
            await _local.EnsureRunningAsync(ct);
    }
    public async Task ShutdownAsync(CancellationToken ct = default)
    {
        if (_local is not null) await _local.StopAsync(ct);
    }

    public UIManifest GetUIManifest() => new()
    {
        SettingsPanels = [new UISettingsPanel($"{ExtensionId}:settings", "Auto PMV Maker", ExtensionId, "PmvSettingsPanel", 270, "extensions")],
        Actions =
        [
            new("pmv-video-bulk", "Create PMV", ExtensionId, "bulk", ["video"], "Clapperboard", HandlerName: "openPmv") { RequiredPermission = "videos.read" },
            new("pmv-performer-bulk", "Create PMV", ExtensionId, "bulk", ["performer"], "Clapperboard", HandlerName: "openPmv") { RequiredPermission = "videos.read" },
            new("pmv-studio-bulk", "Create PMV", ExtensionId, "bulk", ["studio"], "Clapperboard", HandlerName: "openPmv") { RequiredPermission = "videos.read" },
            new("pmv-tag-bulk", "Create PMV", ExtensionId, "bulk", ["tag"], "Clapperboard", HandlerName: "openPmv") { RequiredPermission = "videos.read" },
            new("pmv-segment-bulk", "Create PMV", ExtensionId, "bulk", ["segment"], "Clapperboard", HandlerName: "openPmv") { RequiredPermission = "segments.read" },
            new("pmv-video-detail", "Create PMV", ExtensionId, "toolbar", ["video"], "Clapperboard", HandlerName: "openPmv") { RequiredPermission = "videos.read" }
            ,new("pmv-performer-detail", "Create PMV from filtered videos", ExtensionId, "toolbar", ["performer"], "Clapperboard", HandlerName: "openPmv") { RequiredPermission = "videos.read" }
            ,new("pmv-studio-detail", "Create PMV from filtered videos", ExtensionId, "toolbar", ["studio"], "Clapperboard", HandlerName: "openPmv") { RequiredPermission = "videos.read" }
            ,new("pmv-tag-detail", "Create PMV from filtered segments", ExtensionId, "toolbar", ["tag"], "Clapperboard", HandlerName: "openPmv") { RequiredPermission = "videos.read" }
        ],
        Slots = [new UISlotContribution($"{ExtensionId}:launcher", "app-floating-ui", ExtensionId, ComponentName: "PmvLauncher")]
    };

    public void MapEndpoints(IEndpointRouteBuilder endpoints)
    {
        MapGetResult(endpoints, "/api/ext/pmv/settings", async (HttpContext ctx) => Results.Json(PublicSettings(await SettingsAsync(ctx.RequestAborted)), Json))
            .RequireCovePermission("system.settings.write");
        MapGetResult(endpoints, "/api/ext/pmv/scan-roots", (HttpContext ctx) =>
        {
            var roots = ctx.RequestServices.GetService<CoveConfiguration>()?.CovePaths
                .Where(path => !path.ExcludeVideo && !string.IsNullOrWhiteSpace(path.Path))
                .Select(path => new { name = path.Path, path = path.Path, hasChildren = true })
                .ToArray() ?? [];
            return Task.FromResult<IResult>(Results.Json(roots, Json));
        }).RequireCovePermission("system.settings.write");
        MapGetResult(endpoints, "/api/ext/pmv/folders", (HttpContext ctx) =>
        {
            try
            {
                var requested = ctx.Request.Query["path"].ToString();
                if (string.IsNullOrWhiteSpace(requested))
                {
                    var drives = DriveInfo.GetDrives().Where(drive => Directory.Exists(drive.RootDirectory.FullName))
                        .Select(drive => new { name = drive.RootDirectory.FullName, path = drive.RootDirectory.FullName, hasChildren = true })
                        .ToArray();
                    return Task.FromResult<IResult>(Results.Json(drives, Json));
                }
                var full = Path.GetFullPath(requested);
                if (!Path.IsPathRooted(requested) || !Directory.Exists(full))
                    return Task.FromResult<IResult>(Results.BadRequest(new { message = "That folder is unavailable to Cove." }));
                var folders = Directory.EnumerateDirectories(full)
                    .Select(path => new { name = Path.GetFileName(Path.TrimEndingDirectorySeparator(path)), path, hasChildren = true })
                    .OrderBy(folder => folder.name, StringComparer.OrdinalIgnoreCase).ToArray();
                return Task.FromResult<IResult>(Results.Json(folders, Json));
            }
            catch (Exception ex) when (ex is ArgumentException or IOException or UnauthorizedAccessException)
            {
                return Task.FromResult<IResult>(Results.BadRequest(new { message = "Cove cannot browse this folder: " + ex.Message }));
            }
        }).RequireCovePermission("system.settings.write");
        MapPostResult(endpoints, "/api/ext/pmv/upload-audio", async (HttpContext ctx) =>
        {
            var extension = ctx.Request.Headers["X-PMV-Extension"].ToString().ToLowerInvariant();
            if (!AudioUploadExtensions.Contains(extension) || ctx.Request.ContentLength > MaxAudioUploadBytes)
                return Results.BadRequest(new { message = "Choose an audio file under 200 MB (MP3, WAV, FLAC, M4A, AAC, OGG, OPUS, or AIFF)." });
            var sizeFeature = ctx.Features.Get<IHttpMaxRequestBodySizeFeature>();
            if (sizeFeature is { IsReadOnly: false }) sizeFeature.MaxRequestBodySize = MaxAudioUploadBytes;
            var temp = Path.Combine(Path.GetTempPath(), "pmvmaker-song-" + Guid.NewGuid().ToString("N"));
            try
            {
                long length = 0;
                await using (var file = new FileStream(temp, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                {
                    var buffer = new byte[1024 * 1024];
                    int read;
                    while ((read = await ctx.Request.Body.ReadAsync(buffer, ctx.RequestAborted)) > 0)
                    {
                        length += read;
                        if (length > MaxAudioUploadBytes)
                            return Results.BadRequest(new { message = "The song file is larger than 200 MB." });
                        await file.WriteAsync(buffer.AsMemory(0, read), ctx.RequestAborted);
                    }
                }
                if (length == 0) return Results.BadRequest(new { message = "Choose an audio file first." });
                var settings = await EffectiveSettingsAsync(ctx.RequestAborted);
                using var post = NewRequest(HttpMethod.Post, settings, "uploads");
                post.Headers.TryAddWithoutValidation("X-PMV-Extension", extension);
                post.Content = new StreamContent(File.OpenRead(temp));
                post.Content.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
                post.Content.Headers.ContentLength = length;
                using var client = new HttpClient { Timeout = TimeSpan.FromMinutes(5) };
                using var response = await client.SendAsync(post, ctx.RequestAborted);
                var result = await response.Content.ReadFromJsonAsync<JsonElement>(Json, ctx.RequestAborted);
                if (!response.IsSuccessStatusCode)
                    return Results.BadRequest(new { message = result.TryGetProperty("message", out var error)
                        ? error.GetString() : "The companion could not read this song." });
                return Results.Json(result, Json);
            }
            catch (Exception ex) when (ex is IOException or HttpRequestException or InvalidOperationException)
            {
                return Results.BadRequest(new { message = "Song upload failed: " + ex.Message });
            }
            finally { File.Delete(temp); }
        }).RequireCovePermission("videos.read").RequireCovePermission("jobs.run");
        MapDeleteResult(endpoints, "/api/ext/pmv/uploads/{id}", async (HttpContext ctx) =>
        {
            var id = ctx.Request.RouteValues["id"]?.ToString() ?? "";
            if (!Guid.TryParseExact(id, "N", out _)) return Results.BadRequest(new { message = "Invalid uploaded song ID." });
            try
            {
                using var request = NewRequest(HttpMethod.Delete, await EffectiveSettingsAsync(ctx.RequestAborted), "uploads/" + id);
                using var response = await _http.SendAsync(request, ctx.RequestAborted);
                response.EnsureSuccessStatusCode();
                return Results.Json(new { deleted = true }, Json);
            }
            catch (Exception ex) { return Results.BadRequest(new { message = ex.Message }); }
        }).RequireCovePermission("videos.read").RequireCovePermission("jobs.run");
        MapGetResult(endpoints, "/api/ext/pmv/local-companion", async (HttpContext ctx) =>
        {
            var settings = await SettingsAsync(ctx.RequestAborted);
            if (settings.CompanionMode == "auto" && _local is not null)
                await _local.EnsureRunningAsync(ctx.RequestAborted);
            return Results.Json(_local?.Status ?? new LocalCompanionStatus(false, false, "Local companion control is unavailable."), Json);
        }).RequireCovePermission("system.settings.write");
        MapPostResult(endpoints, "/api/ext/pmv/local-companion/start", async (HttpContext ctx) =>
        {
            if ((await SettingsAsync(ctx.RequestAborted)).CompanionMode != "auto")
                return Results.BadRequest(new { message = "Switch to automatic local mode first." });
            return Results.Json(_local is null
                ? new LocalCompanionStatus(false, false, "Local companion control is unavailable.")
                : await _local.RestartAsync(ctx.RequestAborted), Json);
        }).RequireCovePermission("system.settings.write");
        MapGetResult(endpoints, "/api/ext/pmv/defaults", async (HttpContext ctx) =>
        {
            var settings = await SettingsAsync(ctx.RequestAborted);
            return Results.Json(new { settings.DefaultAudioKind, settings.DefaultFaceGender, settings.Defaults }, Json);
        })
            .RequireCovePermission("videos.read");
        MapGetResult(endpoints, "/api/ext/pmv/performers", async (HttpContext ctx) =>
        {
            var query = ctx.Request.Query["q"].ToString().Trim();
            if (query.Length < 2) return Results.Json(Array.Empty<object>(), Json);
            await using var scope = _scopes!.CreateAsyncScope();
            var db = scope.ServiceProvider.GetRequiredService<CoveContext>();
            var performers = await db.Performers.AsNoTracking().Where(p => p.Name.Contains(query))
                .OrderBy(p => p.Name).Take(30).Select(p => new { p.Id, p.Name, p.Gender,
                    HasReference = p.ImageBlobId != null || p.ImageOverrideBlobId != null || db.Faces.Any(f => f.PerformerId == p.Id && f.CoverBlobId != null && !f.Ignored) })
                .ToArrayAsync(ctx.RequestAborted);
            return Results.Json(performers, Json);
        }).RequireCovePermission("performers.read");
        MapGetResult(endpoints, "/api/ext/pmv/segment-tags", async (HttpContext ctx) =>
        {
            var query = ctx.Request.Query["q"].ToString().Trim();
            var ids = ctx.Request.Query["ids"].ToString().Split(',', StringSplitOptions.RemoveEmptyEntries)
                .Select(value => int.TryParse(value, out var id) ? id : 0).Where(id => id > 0).Distinct().Take(100).ToArray();
            await using var scope = _scopes!.CreateAsyncScope();
            var db = scope.ServiceProvider.GetRequiredService<CoveContext>();
            var tags = await db.Tags.AsNoTracking().Where(tag => ids.Contains(tag.Id) || query.Length >= 2 && tag.Name.Contains(query))
                .OrderBy(tag => tag.Name).Take(100).Select(tag => new { tag.Id, tag.Name }).ToArrayAsync(ctx.RequestAborted);
            var principal = ctx.RequestServices.GetRequiredService<ICurrentPrincipalAccessor>().Current;
            var decisions = await scope.ServiceProvider.GetRequiredService<IAuthorizationService>().AuthorizeManyAsync(principal,
                "tags.read", tags.Select(tag => new EntityRef(EntityKinds.Tag, tag.Id.ToString())).ToArray(), ctx.RequestAborted);
            return Results.Json(tags.Where((_, index) => decisions[index].Allowed), Json);
        }).RequireCovePermission("tags.read");
        MapPutResult(endpoints, "/api/ext/pmv/settings", async (HttpContext ctx) =>
        {
            var settings = await ctx.Request.ReadFromJsonAsync<PmvSettings>(Json, ctx.RequestAborted) ?? new();
            settings.Defaults ??= new PmvOptions();
            if (settings.DefaultAudioKind is not ("cove" or "folder" or "upload" or "youtube" or "video"))
                return Results.BadRequest(new { message = "Choose a supported default backing audio source." });
            if (settings.DefaultFaceGender is not ("female" or "male" or "trans" or "all"))
                return Results.BadRequest(new { message = "Choose a supported face performer gender preset." });
            if (NewOptionError(settings.Defaults) is { } optionError)
                return Results.BadRequest(new { message = optionError });
            if (settings.CompanionMode is not ("auto" or "external"))
                return Results.BadRequest(new { message = "Choose automatic or external companion mode." });
            if (settings.CompanionMode == "auto" && !LocalCompanion.IsSupported)
                return Results.BadRequest(new { message = "Automatic mode requires native Cove in a signed-in Windows desktop session." });
            if (settings.CompanionMode == "external" && (string.IsNullOrWhiteSpace(settings.CompanionUrl)
                || !Uri.TryCreate(settings.CompanionUrl, UriKind.Absolute, out var uri) || uri.Scheme != "http"))
                return Results.BadRequest(new { message = "Enter a local HTTP companion URL." });
            if (!string.IsNullOrWhiteSpace(settings.OutputFolder) && !OutputInScanRoot(settings.OutputFolder, ctx.RequestServices))
                return Results.BadRequest(new { message = "Choose an output folder inside a Cove library path that scans videos." });
            if (_store is null) return Results.Problem("Extension storage unavailable.");
            if (settings.CompanionMode == "external" && string.IsNullOrWhiteSpace(settings.CompanionToken))
                settings.CompanionToken = (await SettingsAsync(ctx.RequestAborted)).CompanionToken;
            if (settings.CompanionMode == "auto")
            {
                settings.CompanionUrl = "http://127.0.0.1:8765";
                settings.CompanionToken = "";
            }
            await _store.SetAsync("settings", JsonSerializer.Serialize(settings, Json), ctx.RequestAborted);
            if (settings.CompanionMode == "auto" && _local is not null)
                await _local.EnsureRunningAsync(ctx.RequestAborted);
            else if (_local is not null)
                await _local.StopAsync(ctx.RequestAborted);
            return Results.Json(PublicSettings(settings), Json);
        }).RequireCovePermission("system.settings.write");
        MapPostResult(endpoints, "/api/ext/pmv/pick-folder", async (HttpContext ctx) =>
        {
            try
            {
                var request = await ctx.Request.ReadFromJsonAsync<FolderPickerRequest>(Json, ctx.RequestAborted) ?? new();
                var title = request.Kind switch
                {
                    "musicFolder" => "Choose music folder",
                    "projectFolder" => "Choose Resolve project folder",
                    _ => null
                };
                if (title is null) return Results.BadRequest(new { message = "Choose a supported folder setting." });
                var settings = await EffectiveSettingsAsync(ctx.RequestAborted);
                var initial = string.IsNullOrWhiteSpace(request.InitialPath) ? "" : ToHost(request.InitialPath, settings);
                using var post = NewRequest(HttpMethod.Post, settings, "pick-folder");
                post.Content = JsonBody(new { title, initialPath = initial });
                using var pickerClient = new HttpClient { Timeout = TimeSpan.FromMinutes(11) };
                using var response = await pickerClient.SendAsync(post, ctx.RequestAborted);
                var result = await response.Content.ReadFromJsonAsync<JsonElement>(Json, ctx.RequestAborted);
                if (!response.IsSuccessStatusCode)
                    return Results.BadRequest(new { message = result.TryGetProperty("message", out var error)
                        ? error.GetString() : "Windows folder dialog failed." });
                if (result.TryGetProperty("cancelled", out var cancelled) && cancelled.GetBoolean())
                    return Results.Json(new { cancelled = true }, Json);
                var hostPath = result.GetProperty("path").GetString() ?? "";
                var covePath = ToCove(hostPath, settings);
                if (request.Kind != "projectFolder" && !Directory.Exists(covePath))
                    return Results.BadRequest(new { message = "The selected Windows folder is not readable by Cove. For Docker, add its container-to-Windows path mapping, save settings, then browse again." });
                return Results.Json(new { path = covePath }, Json);
            }
            catch (Exception ex) { return Results.BadRequest(new { message = ex.Message }); }
        }).RequireCovePermission("system.settings.write");
        MapGetResult(endpoints, "/api/ext/pmv/health", async (HttpContext ctx) =>
        {
            try { return Results.Json(await CompanionGetAsync(await EffectiveSettingsAsync(ctx.RequestAborted), "health", ctx.RequestAborted), Json); }
            catch (Exception ex) { return Results.Json(new { ok = false, error = ex.Message }, Json); }
        }).RequireCovePermission("videos.read");
        MapGetResult(endpoints, "/api/ext/pmv/validation", async (HttpContext ctx) =>
        {
            try { return Results.Json(await CompanionGetAsync(await EffectiveSettingsAsync(ctx.RequestAborted), "validation", ctx.RequestAborted), Json); }
            catch (Exception ex) { return Results.Json(new { state = "failed", error = ex.Message }, Json); }
        }).RequireCovePermission("system.settings.write");
        MapPostResult(endpoints, "/api/ext/pmv/validation", async (HttpContext ctx) =>
        {
            try
            {
                using var request = NewRequest(HttpMethod.Post, await EffectiveSettingsAsync(ctx.RequestAborted), "validation");
                using var response = await _http.SendAsync(request, ctx.RequestAborted);
                response.EnsureSuccessStatusCode();
                return Results.Json(await response.Content.ReadFromJsonAsync<JsonElement>(Json, ctx.RequestAborted), Json);
            }
            catch (Exception ex) { return Results.BadRequest(new { message = ex.Message }); }
        }).RequireCovePermission("system.settings.write");
        MapGetResult(endpoints, "/api/ext/pmv/audio", async (HttpContext ctx) =>
        {
            var q = ctx.Request.Query["q"].ToString();
            await using var scope = _scopes!.CreateAsyncScope();
            var db = scope.ServiceProvider.GetRequiredService<CoveContext>();
            var rows = await db.Audios.AsNoTracking().Where(a => q == "" || a.Title != null && a.Title.Contains(q))
                .OrderBy(a => a.Title).Take(100).Select(a => new { a.Id, a.Title, a.MaxDuration, a.MinPath }).ToListAsync(ctx.RequestAborted);
            var auth = scope.ServiceProvider.GetRequiredService<IAuthorizationService>();
            var principal = ctx.RequestServices.GetRequiredService<ICurrentPrincipalAccessor>().Current;
            var decisions = await auth.AuthorizeManyAsync(principal, "audios.read",
                rows.Select(a => new EntityRef(EntityKinds.Audio, a.Id.ToString())).ToArray(), ctx.RequestAborted);
            return Results.Json(rows.Where((_, i) => decisions[i].Allowed).Take(50), Json);
        }).RequireCovePermission("audios.read");
        MapGetResult(endpoints, "/api/ext/pmv/videos", async (HttpContext ctx) =>
        {
            var q = ctx.Request.Query["q"].ToString();
            await using var scope = _scopes!.CreateAsyncScope();
            var db = scope.ServiceProvider.GetRequiredService<CoveContext>();
            var rows = await db.Videos.AsNoTracking().Where(v => q == "" || v.Title != null && v.Title.Contains(q))
                .OrderBy(v => v.Title).Take(100).Select(v => new { v.Id, v.Title, v.MinPath }).ToListAsync(ctx.RequestAborted);
            var auth = scope.ServiceProvider.GetRequiredService<IAuthorizationService>();
            var principal = ctx.RequestServices.GetRequiredService<ICurrentPrincipalAccessor>().Current;
            var decisions = await auth.AuthorizeManyAsync(principal, "videos.read",
                rows.Select(v => new EntityRef(EntityKinds.Video, v.Id.ToString())).ToArray(), ctx.RequestAborted);
            return Results.Json(rows.Where((_, i) => decisions[i].Allowed).Take(50), Json);
        }).RequireCovePermission("videos.read");
        MapGetResult(endpoints, "/api/ext/pmv/music", async (HttpContext ctx) =>
        {
            var settings = await SettingsAsync(ctx.RequestAborted);
            if (string.IsNullOrWhiteSpace(settings.MusicFolder)) return Results.BadRequest(new { message = "Set a music folder first." });
            var root = Path.GetFullPath(settings.MusicFolder);
            var rel = ctx.Request.Query["path"].ToString();
            var path = Path.GetFullPath(Path.Combine(root, rel));
            if (!IsAtOrBelow(path, root) || !Directory.Exists(root) || !Directory.Exists(path)) return Results.BadRequest(new { message = "Invalid music folder." });
            var folders = Directory.EnumerateDirectories(path).Select(p => new { name = Path.GetFileName(p), path = Path.GetRelativePath(root, p), kind = "folder" });
            var files = Directory.EnumerateFiles(path).Where(p => AudioUploadExtensions.Contains(Path.GetExtension(p)))
                .Select(p => new { name = Path.GetFileName(p), path = Path.GetRelativePath(root, p), kind = "file" });
            return Results.Json(folders.Concat(files).OrderBy(x => x.kind).ThenBy(x => x.name), Json);
        }).RequireCovePermission("files.read");
        MapGetResult(endpoints, "/api/ext/pmv/music-preview", async (HttpContext ctx) =>
        {
            var settings = await SettingsAsync(ctx.RequestAborted);
            if (string.IsNullOrWhiteSpace(settings.MusicFolder)) return Results.BadRequest(new { message = "Set a music folder first." });
            var root = Path.GetFullPath(settings.MusicFolder);
            var relative = ctx.Request.Query["path"].ToString();
            if (string.IsNullOrWhiteSpace(relative) || Path.IsPathRooted(relative)) return Results.BadRequest(new { message = "Choose a track inside the music folder." });
            var path = Path.GetFullPath(Path.Combine(root, relative));
            if (!IsAtOrBelow(path, root) || !AudioUploadExtensions.Contains(Path.GetExtension(path)) || !File.Exists(path))
                return Results.NotFound();
            var contentType = Path.GetExtension(path).ToLowerInvariant() switch
            {
                ".mp3" => "audio/mpeg", ".wav" => "audio/wav", ".flac" => "audio/flac",
                ".m4a" => "audio/mp4", ".aac" => "audio/aac", ".ogg" => "audio/ogg",
                ".opus" => "audio/ogg", ".aiff" => "audio/aiff", _ => "application/octet-stream"
            };
            return Results.File(path, contentType, enableRangeProcessing: true);
        }).RequireCovePermission("files.read");
        MapPostResult(endpoints, "/api/ext/pmv/preview", async (HttpContext ctx) =>
        {
            var request = await ctx.Request.ReadFromJsonAsync<PmvRequest>(Json, ctx.RequestAborted) ?? new();
            if (request.Options is not null && NewOptionError(request.Options) is { } optionError)
                return Results.BadRequest(new { message = optionError });
            await using var scope = _scopes!.CreateAsyncScope();
            var principal = ctx.RequestServices.GetRequiredService<ICurrentPrincipalAccessor>().Current;
            var settings = await SettingsAsync(ctx.RequestAborted);
            var options = request.Options ?? settings.Defaults;
            ScopeResult result;
            try { result = await scope.ServiceProvider.GetRequiredService<SourceResolver>().ResolveAsync(request.Scope, principal, ctx.RequestAborted, options); }
            catch (UnauthorizedAccessException) { return Results.Forbid(); }
            result = FilterSourcesForLayout(result, options);
            var stem = result.Videos.Count == 0 ? "PMVMAKER_Multi" : PmvNaming.Stem(result, result.Videos, result.Videos.SelectMany(v => v.AllowedSegments ?? v.Segments).Select(s => s.Id).ToArray());
            var performerIds = result.Videos.SelectMany(v => v.PerformerIds).Distinct().ToArray();
            var db = scope.ServiceProvider.GetRequiredService<CoveContext>();
            var performers = await db.Performers.AsNoTracking()
                .Where(p => performerIds.Contains(p.Id)).OrderBy(p => p.Name)
                .Select(p => new { p.Id, p.Name, p.Gender,
                    HasReference = p.ImageBlobId != null || p.ImageOverrideBlobId != null || db.Faces.Any(f => f.PerformerId == p.Id && f.CoverBlobId != null && !f.Ignored) })
                .ToArrayAsync(ctx.RequestAborted);
            var gridShort = options.Layout is "grid" or "grid-full" && result.Videos.Count < 4;
            var portraitShort = options.Layout is "three-pane-full" && options.UseVerticalVideosOnly
                && !result.Videos.Any(video => video.Height > video.Width);
            return Results.Json(new { eligibleCount = result.Videos.Count, canCreate = result.Videos.Count > 0 && !gridShort && !portraitShort,
                eligibilityNote = gridShort ? "Grid needs at least four eligible landscape videos." : portraitShort
                    ? "Three-pane phases need at least one portrait video." : (string?)null,
                exclusions = result.Exclusions, performers,
                proposedFilename = PmvNaming.Proposed(settings.OutputFolder, stem, settings.ProjectFolder,
                    request.Options?.SaveProject ?? settings.Defaults.SaveProject) }, Json);
        }).RequireCovePermission("videos.read");
        MapPostResult(endpoints, "/api/ext/pmv/create", async (HttpContext ctx) =>
        {
            var request = await ctx.Request.ReadFromJsonAsync<PmvRequest>(Json, ctx.RequestAborted) ?? new();
            if (NewOptionError(request.Options ?? (await SettingsAsync(ctx.RequestAborted)).Defaults) is { } optionError)
                return Results.BadRequest(new { message = optionError });
            if (string.IsNullOrWhiteSpace((await SettingsAsync(ctx.RequestAborted)).OutputFolder))
                return Results.BadRequest(new { message = "Set an output folder first." });
            if (!OutputInScanRoot((await SettingsAsync(ctx.RequestAborted)).OutputFolder, ctx.RequestServices))
                return Results.BadRequest(new { message = "Choose an output folder inside a Cove library path that scans videos." });
            PmvSettings settings;
            try { settings = await EffectiveSettingsAsync(ctx.RequestAborted); }
            catch (InvalidOperationException ex) { return Results.BadRequest(new { message = ex.Message }); }
            if (string.IsNullOrWhiteSpace(settings.CompanionToken)) return Results.BadRequest(new { message = "Set the companion token first." });
            await using var scope = _scopes!.CreateAsyncScope();
            var principal = ctx.RequestServices.GetRequiredService<ICurrentPrincipalAccessor>().Current;
            ScopeResult resolved;
            try { resolved = await scope.ServiceProvider.GetRequiredService<SourceResolver>().ResolveAsync(request.Scope, principal, ctx.RequestAborted, request.Options ?? settings.Defaults); }
            catch (UnauthorizedAccessException) { return Results.Forbid(); }
            resolved = FilterSourcesForLayout(resolved, request.Options ?? settings.Defaults);
            var requestedOptions = request.Options ?? settings.Defaults;
            if (NeedsFaceReferences(requestedOptions)
                && !scope.ServiceProvider.GetRequiredService<IAuthorizationService>().Has(principal, "performers.read"))
                return Results.Forbid();
            if (resolved.Videos.Count == 0) return Results.BadRequest(new { message = "No eligible sources.", exclusions = resolved.Exclusions });
            if (requestedOptions.Layout is "grid" or "grid-full" && resolved.Videos.Count < 4)
                return Results.BadRequest(new { message = "Grid needs at least four eligible landscape videos.", exclusions = resolved.Exclusions });
            if (requestedOptions.Layout == "three-pane-full" && requestedOptions.UseVerticalVideosOnly
                && !resolved.Videos.Any(video => video.Height > video.Width))
                return Results.BadRequest(new { message = "Three-pane phases need a portrait video.", exclusions = resolved.Exclusions });
            var health = await CompanionGetAsync(settings, "health", ctx.RequestAborted);
            if (!health.GetProperty("ok").GetBoolean()) return Results.BadRequest(new { message = "Resolve Studio companion is unhealthy.", health });
            if (!settings.SkipSetupChecks && (!health.TryGetProperty("validated", out var validated) || !validated.GetBoolean()))
                return Results.BadRequest(new { message = "Run the Resolve compatibility check before creating a PMV." });
            var outputFolder = Path.GetFullPath(settings.OutputFolder);
            if (request.Options?.ScanToCove ?? settings.Defaults.ScanToCove)
            {
                Directory.CreateDirectory(outputFolder);
                var marker = Path.Combine(outputFolder, ".pmv-preflight-" + Guid.NewGuid().ToString("N"));
                try { await File.WriteAllTextAsync(marker, "preflight", ctx.RequestAborted); }
                finally { if (File.Exists(marker)) File.Delete(marker); }
            }
            var db = scope.ServiceProvider.GetRequiredService<CoveContext>();
            object audio;
            try { audio = await AudioPayloadAsync(request.Audio, settings, db, scope.ServiceProvider.GetRequiredService<IAuthorizationService>(), principal, ctx.RequestAborted); }
            catch (UnauthorizedAccessException) { return Results.Forbid(); }
            using var preflight = NewRequest(HttpMethod.Post, settings, "preflight");
            preflight.Content = JsonBody(new
            {
                sources = resolved.Videos.Select(v => new { path = ToHost(v.Path, settings) }),
                audio,
                outputFolder = ToHost(settings.OutputFolder, settings),
                projectFolder = string.IsNullOrWhiteSpace(settings.ProjectFolder) ? "" : ToHost(settings.ProjectFolder, settings)
            });
            using var checkedResponse = await _http.SendAsync(preflight, ctx.RequestAborted);
            if (!checkedResponse.IsSuccessStatusCode)
                return Results.BadRequest(new { message = await checkedResponse.Content.ReadAsStringAsync(ctx.RequestAborted) });
            var jobs = ctx.RequestServices.GetRequiredService<IJobService>();
            var id = jobs.Enqueue($"ext:{ExtensionId}:render", "[PMV] Render " + resolved.Videos.Count + " sources",
                (progress, ct) => RunAsync(request, settings, principal, progress, ct), exclusive: true);
            return Results.Accepted(value: new { jobId = id, message = "PMV queued.", exclusions = resolved.Exclusions });
        }).RequireCovePermission("videos.read").RequireCovePermission("videos.write").RequireCovePermission("jobs.run");
    }

    // Use the Delegate overload. The RequestDelegate overload accepts the async lambda but drops
    // its IResult, producing HTTP 200 with an empty body.
    private static RouteHandlerBuilder MapGetResult(IEndpointRouteBuilder endpoints, string pattern, Func<HttpContext, Task<IResult>> handler)
        => endpoints.MapGet(pattern, (Delegate)handler);

    private static RouteHandlerBuilder MapPutResult(IEndpointRouteBuilder endpoints, string pattern, Func<HttpContext, Task<IResult>> handler)
        => endpoints.MapPut(pattern, (Delegate)handler);

    private static RouteHandlerBuilder MapPostResult(IEndpointRouteBuilder endpoints, string pattern, Func<HttpContext, Task<IResult>> handler)
        => endpoints.MapPost(pattern, (Delegate)handler);

    private static RouteHandlerBuilder MapDeleteResult(IEndpointRouteBuilder endpoints, string pattern, Func<HttpContext, Task<IResult>> handler)
        => endpoints.MapDelete(pattern, (Delegate)handler);

    private static string? NewOptionError(PmvOptions options)
    {
        if (options.Layout is not ("three-pane" or "full-screen" or "grid" or "three-pane-full" or "grid-full"))
            return "Choose a supported PMV layout.";
        if (options.FullSelectionMode is not ("scene" or "face"))
            return "Full-screen selection must be Scene or Face match.";
        if (options.SegmentTagIds is null || options.SegmentTagIds.Length > 100 || options.SegmentTagIds.Any(id => id <= 0))
            return "Segment list must contain at most 100 valid tags.";
        if (options.FaceSimilarityThreshold is < 0.3 or > 0.8 || !double.IsFinite(options.FaceSimilarityThreshold))
            return "Face similarity threshold must be between 0.30 and 0.80.";
        if (options.MinimumTimestampSeconds < 0 || options.EndBufferSeconds < 0
            || !double.IsFinite(options.MinimumTimestampSeconds) || !double.IsFinite(options.EndBufferSeconds))
            return "Clip timestamp and end buffer must be nonnegative seconds.";
        if (options.RotatedClipLengthSeconds is < 1 or > 300 || !double.IsFinite(options.RotatedClipLengthSeconds))
            return "Rotated scene length must be between 1 and 300 seconds.";
        if (options.CycleLongerClipIntoSegments && options.RotatedClipLengthSeconds < options.MaxClipSeconds)
            return "Rotated scene length must be at least the maximum clip length when cycling is enabled.";
        if (options.BeatsPerBar is not ("auto" or "3" or "4" or "6"))
            return "Beats per bar must be Auto, 3, 4, or 6.";
        return null;
    }

    private static HttpContent JsonBody<T>(T value)
    {
        var bytes = JsonSerializer.SerializeToUtf8Bytes(value, Json);
        var content = new ByteArrayContent(bytes);
        content.Headers.ContentType = new MediaTypeHeaderValue("application/json");
        content.Headers.ContentLength = bytes.Length;
        return content;
    }

    private async Task RunAsync(PmvRequest request, PmvSettings settings, CovePrincipal? principal, Cove.Core.Interfaces.IJobProgress progress, CancellationToken ct)
    {
        await using var scope = _scopes!.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<CoveContext>();
        var logger = scope.ServiceProvider.GetRequiredService<ILogger<PmvMakerExtension>>();
        var options = request.Options ?? settings.Defaults;
        var resolved = FilterSourcesForLayout(await scope.ServiceProvider.GetRequiredService<SourceResolver>().ResolveAsync(request.Scope, principal, ct, options), options);
        if (resolved.Videos.Count == 0) throw new InvalidOperationException("All selected media became unavailable before the job started.");
        logger.LogInformation("[PMV] Resolved {SourceCount} eligible videos; {ExclusionCount} excluded; layout {Layout}, selection {Selection}, audio {AudioKind}",
            resolved.Videos.Count, resolved.Exclusions.Count, options.Layout, options.SelectionMode, request.Audio.Kind);
        var referenceIds = new List<string>();
        try
        {
        var faceMode = NeedsFaceReferences(options);
        var references = faceMode
            ? await UploadFaceReferencesAsync(db, scope.ServiceProvider.GetRequiredService<IBlobService>(),
                request.FacePerformerIds, resolved, settings, referenceIds, ct)
            : new List<FaceReference>();
        if (faceMode && references.Count == 0)
            throw new InvalidOperationException("No reference face images were found for the selected performers. Choose performers with portraits or Cove face images, or disable performer matching.");
        if (faceMode)
            logger.LogInformation("[PMV] Uploaded {ReferenceCount} face reference images for {PerformerCount} performers; similarity threshold {Threshold:P0}",
                references.Count, references.Select(row => row.PerformerId).Distinct().Count(), options.FaceSimilarityThreshold);
        var payload = new
        {
            sources = resolved.Videos.Select(v => new { v.Id, path = ToHost(v.Path, settings), v.Duration, v.Width, v.Height, v.Fps,
                tagOnly = v.AllowedSegments is not null,
                v.StudioId, v.StudioName, v.PerformerIds, v.PerformerNames,
                segments = v.AllowedSegments ?? v.Segments, allSegments = v.Segments, v.SavedRanges }),
            launchName = resolved.LaunchName,
            launchKind = resolved.LaunchKind,
            audio = await AudioPayloadAsync(request.Audio, settings, db, scope.ServiceProvider.GetRequiredService<IAuthorizationService>(), principal, ct),
            options,
            references,
            outputFolder = ToHost(settings.OutputFolder, settings),
            projectFolder = string.IsNullOrWhiteSpace(settings.ProjectFolder) ? "" : ToHost(settings.ProjectFolder, settings),
            skipSetupChecks = settings.SkipSetupChecks
        };
        progress.Report(0.02, "Submitting edit to Resolve Studio companion");
        using var post = NewRequest(HttpMethod.Post, settings, "jobs");
        post.Content = JsonBody(payload);
        using var response = await _http.SendAsync(post, ct);
        response.EnsureSuccessStatusCode();
        var submitted = await response.Content.ReadFromJsonAsync<CompanionJob>(Json, ct) ?? throw new InvalidOperationException("Companion gave no job ID.");
        logger.LogInformation("[PMV {CompanionJobId}] Companion accepted render job", submitted.Id[..Math.Min(8, submitted.Id.Length)]);
        long eventCursor = 0;
        try
        {
            while (true)
            {
                await Task.Delay(TimeSpan.FromSeconds(1), ct);
                CompanionJob state;
                do
                {
                    state = (await CompanionGetAsync(settings, "jobs/" + submitted.Id + "?after=" + eventCursor, ct)).Deserialize<CompanionJob>(Json)
                        ?? throw new InvalidOperationException("Companion job state missing.");
                    foreach (var entry in state.Events ?? [])
                    {
                        if (entry.Sequence <= eventCursor) continue;
                        eventCursor = entry.Sequence;
                        if (entry.Level == "error")
                            logger.LogError("[PMV {CompanionJobId}] {Diagnostic}", submitted.Id[..Math.Min(8, submitted.Id.Length)], entry.Message);
                        else if (entry.Level == "warning")
                            logger.LogWarning("[PMV {CompanionJobId}] {Diagnostic}", submitted.Id[..Math.Min(8, submitted.Id.Length)], entry.Message);
                        else
                            logger.LogInformation("[PMV {CompanionJobId}] {Diagnostic}", submitted.Id[..Math.Min(8, submitted.Id.Length)], entry.Message);
                    }
                } while (state.Events?.Count == 250);
                progress.Report(Math.Clamp(state.Progress, 2, 98) / 100.0, state.Message);
                if (state.State == "failed") throw new InvalidOperationException(state.Error ?? state.Message ?? "Resolve render failed.");
                if (state.State == "cancelled") throw new OperationCanceledException("Resolve render cancelled.");
                if (state.State != "complete") continue;
                if (string.IsNullOrWhiteSpace(state.OutputPath)) throw new InvalidOperationException("Companion returned no output path.");
                var covePath = ToCove(state.OutputPath, settings);
                if (!File.Exists(covePath)) throw new InvalidOperationException("Cove cannot read rendered output: " + covePath);
                if (options.ScanToCove)
                {
                    progress.Report(0.98, "Importing PMV into Cove");
                    logger.LogInformation("[PMV {CompanionJobId}] Importing finished MP4 into Cove", submitted.Id[..Math.Min(8, submitted.Id.Length)]);
                    var importedId = await scope.ServiceProvider.GetRequiredService<IScanService>().ImportDownloadedVideoAsync(covePath, null, ct);
                    await ApplyMetadataAsync(db, importedId, state, resolved, options, ct);
                    logger.LogInformation("[PMV {CompanionJobId}] Cove import complete: video {VideoId}", submitted.Id[..Math.Min(8, submitted.Id.Length)], importedId);
                }
                progress.Report(1.0, "PMV saved: " + covePath);
                return;
            }
        }
        catch (OperationCanceledException)
        {
            using var cancel = NewRequest(HttpMethod.Delete, settings, "jobs/" + submitted.Id);
            try { await _http.SendAsync(cancel, CancellationToken.None); } catch { }
            throw;
        }
        }
        finally
        {
            foreach (var id in referenceIds)
            {
                using var delete = NewRequest(HttpMethod.Delete, settings, "references/" + id);
                try { await _http.SendAsync(delete, CancellationToken.None); } catch { }
            }
        }
    }

    private async Task<List<FaceReference>> UploadFaceReferencesAsync(CoveContext db, IBlobService blobs,
        List<int>? selectedIds, ScopeResult scope, PmvSettings settings, List<string> uploaded, CancellationToken ct)
    {
        var ids = selectedIds?.Distinct().ToArray() ?? scope.Videos.SelectMany(v => v.PerformerIds).Distinct().ToArray();
        if (ids.Length == 0) return [];
        var performers = await db.Performers.AsNoTracking().Where(p => ids.Contains(p.Id))
            .Select(p => new { p.Id, p.Name, p.Gender, p.ImageBlobId, p.ImageOverrideBlobId }).ToArrayAsync(ct);
        if (selectedIds is null)
            performers = performers.Where(p => settings.DefaultFaceGender switch
            {
                "female" => p.Gender == GenderEnum.Female,
                "male" => p.Gender == GenderEnum.Male,
                "trans" => p.Gender is GenderEnum.TransgenderFemale or GenderEnum.TransgenderMale,
                _ => true
            }).ToArray();
        var result = new List<FaceReference>();
        foreach (var performer in performers)
        {
            var faceBlob = await db.Faces.AsNoTracking().Where(f => f.PerformerId == performer.Id && !f.Ignored && f.CoverBlobId != null)
                .OrderByDescending(f => f.DetectionCount).Select(f => f.CoverBlobId).FirstOrDefaultAsync(ct);
            foreach (var blobId in new[] { faceBlob, performer.ImageOverrideBlobId, performer.ImageBlobId }.OfType<string>().Distinct().Take(2))
            {
                var blob = await blobs.GetBlobAsync(blobId, ct);
                if (blob is null) continue;
                await using var stream = blob.Value.Stream;
                using var buffer = new MemoryStream();
                await stream.CopyToAsync(buffer, ct);
                if (buffer.Length == 0 || buffer.Length > 10_000_000) continue;
                using var post = NewRequest(HttpMethod.Post, settings, "references");
                post.Headers.Add("X-PMV-Performer-Id", performer.Id.ToString());
                post.Content = new ByteArrayContent(buffer.ToArray());
                using var response = await _http.SendAsync(post, ct);
                response.EnsureSuccessStatusCode();
                var reply = await response.Content.ReadFromJsonAsync<JsonElement>(Json, ct);
                var id = reply.GetProperty("referenceId").GetString()!;
                uploaded.Add(id);
                result.Add(new FaceReference(performer.Id, id, performer.Name));
            }
        }
        return result;
    }

    private async Task<object> AudioPayloadAsync(AudioSelection audio, PmvSettings settings, CoveContext db, IAuthorizationService authorization, CovePrincipal? principal, CancellationToken ct)
    {
        if (audio.Kind == "cove" && (!audio.CoveAudioId.HasValue ||
            !(await authorization.AuthorizeAsync(principal, "audios.read", new EntityRef(EntityKinds.Audio, audio.CoveAudioId.Value.ToString()), ct)).Allowed))
            throw new UnauthorizedAccessException("Backing Cove audio is not accessible.");
        if (audio.Kind == "video" && (!audio.CoveVideoId.HasValue ||
            !(await authorization.AuthorizeAsync(principal, "videos.read", new EntityRef(EntityKinds.Video, audio.CoveVideoId.Value.ToString()), ct)).Allowed))
            throw new UnauthorizedAccessException("Backing Cove video is not accessible.");
        if (audio.Kind == "folder" && !authorization.Has(principal, "files.read"))
            throw new UnauthorizedAccessException("Music folder access requires files.read.");
        if (audio.Kind == "upload")
        {
            if (!Guid.TryParseExact(audio.UploadId, "N", out _))
                throw new ArgumentException("Choose a song file to upload.");
            return new { kind = "upload", uploadId = audio.UploadId };
        }
        if (audio.Kind == "youtube")
        {
            if (!Uri.TryCreate(audio.Url, UriKind.Absolute, out var uri) || uri.Scheme != "https" ||
                !(uri.Host.Equals("youtube.com", StringComparison.OrdinalIgnoreCase) || uri.Host.EndsWith(".youtube.com", StringComparison.OrdinalIgnoreCase) || uri.Host.Equals("youtu.be", StringComparison.OrdinalIgnoreCase)))
                throw new ArgumentException("Enter an HTTPS YouTube URL.");
            return new { kind = "youtube", url = audio.Url };
        }
        string? path = audio.Kind switch
        {
            "cove" => await db.AudioFiles.Where(f => f.AudioId == audio.CoveAudioId).OrderByDescending(f => f.BitRate).Select(f => f.Path).FirstOrDefaultAsync(ct),
            "video" => await db.VideoFiles.Where(f => f.VideoId == audio.CoveVideoId).OrderByDescending(f => f.Id).Select(f => f.Path).FirstOrDefaultAsync(ct),
            "folder" => Path.GetFullPath(Path.Combine(settings.MusicFolder, audio.Path ?? "")),
            _ => null
        };
        if (path is null || !File.Exists(path)) throw new ArgumentException("Selected backing audio is missing.");
        if (audio.Kind == "folder" && !IsAtOrBelow(path, Path.GetFullPath(settings.MusicFolder))) throw new ArgumentException("Music path is outside the configured folder.");
        return new { kind = audio.Kind, path = ToHost(path, settings) };
    }

    private static async Task ApplyMetadataAsync(CoveContext db, int videoId, CompanionJob job, ScopeResult scope, PmvOptions options, CancellationToken ct)
    {
        var used = scope.Videos.Where(v => job.UsedVideoIds?.Contains(v.Id) == true).ToList();
        var tagIds = new HashSet<int>();
        if (options.KeepPerformers)
            foreach (var id in (options.Layout == "three-pane" && options.SelectionMode == "face" && options.MatchSelectedPerformers
                ? job.MatchedPerformerIds ?? [] : used.SelectMany(v => v.PerformerIds).Distinct()))
                db.Set<VideoPerformer>().Add(new VideoPerformer { VideoId = videoId, PerformerId = id });
        if (options.KeepTags)
            foreach (var id in used.SelectMany(v => v.Segments).Where(s => job.UsedSegmentIds?.Contains(s.Id) == true)
                .Where(s => s.TagId.HasValue).Select(s => s.TagId!.Value).Distinct())
                tagIds.Add(id);
        foreach (var name in new[] { options.AddPmvTag ? "PMV" : null, options.AddAutoPmvTag ? "Auto_PMV" : null }.OfType<string>())
        {
            var tag = await db.Tags.FirstOrDefaultAsync(t => t.Name == name, ct);
            if (tag is null) { tag = new Tag { Name = name }; db.Tags.Add(tag); await db.SaveChangesAsync(ct); }
            tagIds.Add(tag.Id);
        }
        var existing = await db.Set<VideoTag>().Where(x => x.VideoId == videoId).Select(x => x.TagId).ToArrayAsync(ct);
        tagIds.ExceptWith(existing);
        foreach (var id in tagIds) db.Set<VideoTag>().Add(new VideoTag { VideoId = videoId, TagId = id });
        await db.SaveChangesAsync(ct);
    }

    private static ScopeResult FilterSourcesForLayout(ScopeResult source, PmvOptions options)
    {
        var excluded = new List<string>(source.Exclusions);
        var eligible = new List<SourceVideo>();
        foreach (var video in source.Videos)
        {
            var lower = Math.Max(0, options.MinimumTimestampSeconds);
            var upper = video.Duration - Math.Max(0, options.EndBufferSeconds);
            if (upper - lower < options.MinClipSeconds)
            {
                excluded.Add($"Video {video.Id}: timestamp limits leave less than the minimum clip length");
                continue;
            }
            if (video.AllowedSegments is not null && !video.AllowedSegments.Any(s =>
                Math.Min(upper, s.End) - Math.Max(lower, s.Start) >= options.MinClipSeconds))
            {
                excluded.Add($"Video {video.Id}: no matching timed segment inside timestamp limits");
                continue;
            }
            if (options.Layout is "grid" or "grid-full" && video.Height > video.Width)
            {
                excluded.Add($"Video {video.Id}: portrait source excluded from grid");
                continue;
            }
            if (options.Layout == "three-pane" && options.UseVerticalVideosOnly && video.Height <= video.Width)
            {
                excluded.Add($"Video {video.Id}: not vertical");
                continue;
            }
            eligible.Add(video);
        }
        return new ScopeResult(eligible, excluded, source.LaunchName, source.LaunchKind);
    }

    private static bool NeedsFaceReferences(PmvOptions options)
    {
        var multiFace = options.Layout is "three-pane" or "three-pane-full" or "grid" or "grid-full"
            && (options.Layout is "grid" or "grid-full" || !options.UseVerticalVideosOnly)
            && options.SelectionMode == "face";
        var fullFace = options.Layout is "full-screen" or "three-pane-full" or "grid-full"
            && options.FullSelectionMode == "face";
        return options.MatchSelectedPerformers && (multiFace || fullFace);
    }

    private static bool OutputInScanRoot(string path, IServiceProvider services)
    {
        var config = services.GetService<CoveConfiguration>();
        if (config is null) return false;
        try
        {
            var full = Path.GetFullPath(path);
            return config.CovePaths.Where(root => !root.ExcludeVideo && !string.IsNullOrWhiteSpace(root.Path))
                .Any(root => IsAtOrBelow(full, Path.GetFullPath(root.Path)));
        }
        catch { return false; }
    }

    private async Task<PmvSettings> SettingsAsync(CancellationToken ct)
    {
        var raw = _store is null ? null : await _store.GetAsync("settings", ct);
        if (raw is null) return new PmvSettings { CompanionMode = LocalCompanion.IsSupported ? "auto" : "external" };
        try
        {
            var settings = JsonSerializer.Deserialize<PmvSettings>(raw, Json) ?? new();
            settings.Defaults ??= new PmvOptions();
            using var document = JsonDocument.Parse(raw);
            if (!document.RootElement.TryGetProperty("colorDefaultsVersion", out _) && settings.Defaults.ColorTreatment == "matched")
                settings.Defaults.ColorTreatment = "natural";
            settings.ColorDefaultsVersion = 1;
            if (!document.RootElement.TryGetProperty("faceDefaultsVersion", out _)
                && settings.Defaults.SelectionMode == "center")
                settings.Defaults.SelectionMode = "face";
            settings.FaceDefaultsVersion = 1;
            if (!document.RootElement.TryGetProperty("companionMode", out _))
                settings.CompanionMode = LocalCompanion.IsSupported
                    && settings.PathMappings.Count == 0
                    && Uri.TryCreate(settings.CompanionUrl, UriKind.Absolute, out var legacyUri)
                    && legacyUri.IsLoopback ? "auto" : "external";
            return settings;
        }
        catch { return new PmvSettings { CompanionMode = LocalCompanion.IsSupported ? "auto" : "external" }; }
    }

    private async Task<PmvSettings> EffectiveSettingsAsync(CancellationToken ct)
    {
        var settings = await SettingsAsync(ct);
        if (settings.CompanionMode != "auto") return settings;
        if (_local is null) throw new InvalidOperationException("Local companion control is unavailable.");
        var status = await _local.EnsureRunningAsync(ct);
        var connection = _local.Connection;
        if (connection is null) throw new InvalidOperationException(status.Error ?? "The local companion did not start.");
        settings.CompanionUrl = connection.Value.Url;
        settings.CompanionToken = connection.Value.Token;
        settings.PathMappings = [];
        return settings;
    }

    private PmvSettings PublicSettings(PmvSettings settings)
    {
        settings.CompanionConfigured = settings.CompanionMode == "auto"
            ? _local?.Connection is not null : !string.IsNullOrWhiteSpace(settings.CompanionToken);
        settings.CompanionToken = "";
        return settings;
    }
    private async Task<JsonElement> CompanionGetAsync(PmvSettings settings, string path, CancellationToken ct)
    {
        using var request = NewRequest(HttpMethod.Get, settings, path);
        using var response = await _http.SendAsync(request, ct);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<JsonElement>(Json, ct);
    }
    private static HttpRequestMessage NewRequest(HttpMethod method, PmvSettings settings, string path)
    {
        var baseUri = new Uri(settings.CompanionUrl.TrimEnd('/') + "/");
        if (!baseUri.IsLoopback && settings.PathMappings.Count == 0) throw new InvalidOperationException("Remote companion requires explicit path mappings.");
        var request = new HttpRequestMessage(method, new Uri(baseUri, path));
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", settings.CompanionToken);
        return request;
    }
    public static string ToHost(string path, PmvSettings settings) => Map(path, settings.PathMappings.Select(m => (m.ContainerPrefix, m.HostPrefix)));
    public static string ToCove(string path, PmvSettings settings) => Map(path, settings.PathMappings.Select(m => (m.HostPrefix, m.ContainerPrefix)));
    private static string Map(string path, IEnumerable<(string From, string To)> mappings)
    {
        foreach (var (from, to) in mappings.OrderByDescending(m => m.From.Length))
            if (IsAtOrBelow(path, from))
            {
                var slash = to.StartsWith('/') ? '/' : '\\';
                var suffix = path[from.TrimEnd('/', '\\').Length..].Replace('/', slash).Replace('\\', slash);
                return to.TrimEnd('/', '\\') + suffix;
            }
        return path;
    }
    private static bool IsAtOrBelow(string path, string root)
    {
        var a = path.TrimEnd('/', '\\'); var b = root.TrimEnd('/', '\\');
        return a.Equals(b, StringComparison.OrdinalIgnoreCase) || a.StartsWith(b + "/", StringComparison.OrdinalIgnoreCase) || a.StartsWith(b + "\\", StringComparison.OrdinalIgnoreCase);
    }
}
