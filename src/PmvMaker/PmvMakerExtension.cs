using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using Cove.Core.Entities;
using Cove.Core.Auth;
using Cove.Core.Interfaces;
using Cove.Data;
using Cove.Plugins;
using Cove.Sdk;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Routing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace Cove.PmvMaker;

public sealed class PmvMakerExtension : IExtension, IUIExtension, IApiExtension, IStatefulExtension
{
    public const string ExtensionId = "io.github.jiwenjimiran.auto-pmv-maker";
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private IExtensionStore? _store;
    private IExtensionServiceScopeFactory? _scopes;
    private LocalCompanion? _local;
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(20) };

    public string Id => ExtensionId;
    public string Name => "Auto PMV Maker";
    public string Version => "0.1.7";
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
            Results.Json(new { defaults = (await SettingsAsync(ctx.RequestAborted)).Defaults }, Json))
            .RequireCovePermission("videos.read");
        MapPutResult(endpoints, "/api/ext/pmv/settings", async (HttpContext ctx) =>
        {
            var settings = await ctx.Request.ReadFromJsonAsync<PmvSettings>(Json, ctx.RequestAborted) ?? new();
            if (settings.CompanionMode is not ("auto" or "external"))
                return Results.BadRequest(new { message = "Choose automatic or external companion mode." });
            if (settings.CompanionMode == "auto" && !LocalCompanion.IsSupported)
                return Results.BadRequest(new { message = "Automatic mode requires native Cove in a signed-in Windows desktop session." });
            if (settings.CompanionMode == "external" && (string.IsNullOrWhiteSpace(settings.CompanionUrl)
                || !Uri.TryCreate(settings.CompanionUrl, UriKind.Absolute, out var uri) || uri.Scheme != "http"))
                return Results.BadRequest(new { message = "Enter a local HTTP companion URL." });
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
                    "outputFolder" => "Choose PMV output folder",
                    "musicFolder" => "Choose music folder",
                    "projectFolder" => "Choose Resolve project folder",
                    _ => null
                };
                if (title is null) return Results.BadRequest(new { message = "Choose a supported folder setting." });
                var settings = await EffectiveSettingsAsync(ctx.RequestAborted);
                var initial = string.IsNullOrWhiteSpace(request.InitialPath) ? "" : ToHost(request.InitialPath, settings);
                using var post = NewRequest(HttpMethod.Post, settings, "pick-folder");
                post.Content = JsonContent.Create(new { title, initialPath = initial }, options: Json);
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
            var files = Directory.EnumerateFiles(path).Where(p => new[] { ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg" }.Contains(Path.GetExtension(p), StringComparer.OrdinalIgnoreCase))
                .Select(p => new { name = Path.GetFileName(p), path = Path.GetRelativePath(root, p), kind = "file" });
            return Results.Json(folders.Concat(files).OrderBy(x => x.kind).ThenBy(x => x.name), Json);
        }).RequireCovePermission("files.read");
        MapPostResult(endpoints, "/api/ext/pmv/preview", async (HttpContext ctx) =>
        {
            var request = await ctx.Request.ReadFromJsonAsync<PmvRequest>(Json, ctx.RequestAborted) ?? new();
            await using var scope = _scopes!.CreateAsyncScope();
            var principal = ctx.RequestServices.GetRequiredService<ICurrentPrincipalAccessor>().Current;
            ScopeResult result;
            try { result = await scope.ServiceProvider.GetRequiredService<SourceResolver>().ResolveAsync(request.Scope, principal, ctx.RequestAborted); }
            catch (UnauthorizedAccessException) { return Results.Forbid(); }
            var stem = result.Videos.Count == 0 ? "PMVMAKER_Multi" : PmvNaming.Stem(result, result.Videos, result.Videos.SelectMany(v => v.Segments).Select(s => s.Id).ToArray());
            var settings = await SettingsAsync(ctx.RequestAborted);
            return Results.Json(new { eligibleCount = result.Videos.Count, exclusions = result.Exclusions,
                proposedFilename = PmvNaming.Proposed(settings.OutputFolder, stem, settings.ProjectFolder,
                    request.Options?.SaveProject ?? settings.Defaults.SaveProject) }, Json);
        }).RequireCovePermission("videos.read");
        MapPostResult(endpoints, "/api/ext/pmv/create", async (HttpContext ctx) =>
        {
            var request = await ctx.Request.ReadFromJsonAsync<PmvRequest>(Json, ctx.RequestAborted) ?? new();
            if (string.IsNullOrWhiteSpace((await SettingsAsync(ctx.RequestAborted)).OutputFolder))
                return Results.BadRequest(new { message = "Set an output folder first." });
            PmvSettings settings;
            try { settings = await EffectiveSettingsAsync(ctx.RequestAborted); }
            catch (InvalidOperationException ex) { return Results.BadRequest(new { message = ex.Message }); }
            if (string.IsNullOrWhiteSpace(settings.CompanionToken)) return Results.BadRequest(new { message = "Set the companion token first." });
            await using var scope = _scopes!.CreateAsyncScope();
            var principal = ctx.RequestServices.GetRequiredService<ICurrentPrincipalAccessor>().Current;
            ScopeResult resolved;
            try { resolved = await scope.ServiceProvider.GetRequiredService<SourceResolver>().ResolveAsync(request.Scope, principal, ctx.RequestAborted); }
            catch (UnauthorizedAccessException) { return Results.Forbid(); }
            if (resolved.Videos.Count == 0) return Results.BadRequest(new { message = "No eligible sources.", exclusions = resolved.Exclusions });
            var health = await CompanionGetAsync(settings, "health", ctx.RequestAborted);
            if (!health.GetProperty("ok").GetBoolean()) return Results.BadRequest(new { message = "Resolve Studio companion is unhealthy.", health });
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
            preflight.Content = JsonContent.Create(new
            {
                sources = resolved.Videos.Select(v => new { path = ToHost(v.Path, settings) }),
                audio,
                outputFolder = ToHost(settings.OutputFolder, settings),
                projectFolder = string.IsNullOrWhiteSpace(settings.ProjectFolder) ? "" : ToHost(settings.ProjectFolder, settings)
            }, options: Json);
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

    private async Task RunAsync(PmvRequest request, PmvSettings settings, CovePrincipal? principal, Cove.Core.Interfaces.IJobProgress progress, CancellationToken ct)
    {
        await using var scope = _scopes!.CreateAsyncScope();
        var db = scope.ServiceProvider.GetRequiredService<CoveContext>();
        var resolved = await scope.ServiceProvider.GetRequiredService<SourceResolver>().ResolveAsync(request.Scope, principal, ct);
        if (resolved.Videos.Count == 0) throw new InvalidOperationException("All selected media became unavailable before the job started.");
        var options = request.Options ?? settings.Defaults;
        var payload = new
        {
            sources = resolved.Videos.Select(v => new { v.Id, path = ToHost(v.Path, settings), v.Duration, v.Width, v.Height, v.Fps,
                tagOnly = resolved.LaunchKind == "tag",
                v.StudioId, v.StudioName, v.PerformerIds, v.PerformerNames, v.Segments, v.SavedRanges }),
            launchName = resolved.LaunchName,
            launchKind = resolved.LaunchKind,
            audio = await AudioPayloadAsync(request.Audio, settings, db, scope.ServiceProvider.GetRequiredService<IAuthorizationService>(), principal, ct),
            options,
            outputFolder = ToHost(settings.OutputFolder, settings),
            projectFolder = string.IsNullOrWhiteSpace(settings.ProjectFolder) ? "" : ToHost(settings.ProjectFolder, settings)
        };
        progress.Report(2, "Submitting edit to Resolve Studio companion");
        using var post = NewRequest(HttpMethod.Post, settings, "jobs");
        post.Content = JsonContent.Create(payload, options: Json);
        using var response = await _http.SendAsync(post, ct);
        response.EnsureSuccessStatusCode();
        var submitted = await response.Content.ReadFromJsonAsync<CompanionJob>(Json, ct) ?? throw new InvalidOperationException("Companion gave no job ID.");
        try
        {
            while (true)
            {
                await Task.Delay(TimeSpan.FromSeconds(2), ct);
                var state = (await CompanionGetAsync(settings, "jobs/" + submitted.Id, ct)).Deserialize<CompanionJob>(Json)
                    ?? throw new InvalidOperationException("Companion job state missing.");
                progress.Report(Math.Clamp(state.Progress, 2, 98), state.Message);
                if (state.State == "failed") throw new InvalidOperationException(state.Error ?? state.Message ?? "Resolve render failed.");
                if (state.State == "cancelled") throw new OperationCanceledException("Resolve render cancelled.");
                if (state.State != "complete") continue;
                if (string.IsNullOrWhiteSpace(state.OutputPath)) throw new InvalidOperationException("Companion returned no output path.");
                var covePath = ToCove(state.OutputPath, settings);
                if (!File.Exists(covePath)) throw new InvalidOperationException("Cove cannot read rendered output: " + covePath);
                if (options.ScanToCove)
                {
                    progress.Report(98, "Importing PMV into Cove");
                    var importedId = await scope.ServiceProvider.GetRequiredService<IScanService>().ImportDownloadedVideoAsync(covePath, null, ct);
                    await ApplyMetadataAsync(db, importedId, state, resolved, options, ct);
                }
                progress.Report(100, "PMV saved: " + covePath);
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
            foreach (var id in used.SelectMany(v => v.PerformerIds).Distinct())
                db.Set<VideoPerformer>().Add(new VideoPerformer { VideoId = videoId, PerformerId = id });
        if (options.KeepTags)
            foreach (var id in used.SelectMany(v => v.Segments).Where(s => job.UsedSegmentIds?.Contains(s.Id) == true)
                .Where(s => s.TagId.HasValue).Select(s => s.TagId!.Value).Distinct())
                tagIds.Add(id);
        if (options.AddPmvTag)
        {
            var tag = await db.Tags.FirstOrDefaultAsync(t => t.Name == "PMV", ct);
            if (tag is null) { tag = new Tag { Name = "PMV" }; db.Tags.Add(tag); await db.SaveChangesAsync(ct); }
            tagIds.Add(tag.Id);
        }
        var existing = await db.Set<VideoTag>().Where(x => x.VideoId == videoId).Select(x => x.TagId).ToArrayAsync(ct);
        tagIds.ExceptWith(existing);
        foreach (var id in tagIds) db.Set<VideoTag>().Add(new VideoTag { VideoId = videoId, TagId = id });
        await db.SaveChangesAsync(ct);
    }

    private async Task<PmvSettings> SettingsAsync(CancellationToken ct)
    {
        var raw = _store is null ? null : await _store.GetAsync("settings", ct);
        if (raw is null) return new PmvSettings { CompanionMode = LocalCompanion.IsSupported ? "auto" : "external" };
        try
        {
            var settings = JsonSerializer.Deserialize<PmvSettings>(raw, Json) ?? new();
            using var document = JsonDocument.Parse(raw);
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
