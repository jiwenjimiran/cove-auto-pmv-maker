using System.Net;
using System.Net.Http.Json;
using System.IO.Compression;
using System.Text.Json;
using System.Reflection;
using Cove.PmvMaker;
using Cove.Plugins;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.Extensions.Logging.Abstractions;

var builder = WebApplication.CreateBuilder(args);
builder.Logging.ClearProviders();
builder.WebHost.UseUrls("http://127.0.0.1:0");
var app = builder.Build();
var fixtureRoot = Directory.CreateTempSubdirectory("pmv-preview-check-").FullName;
var musicRoot = Directory.CreateDirectory(Path.Combine(fixtureRoot, "music")).FullName;
await File.WriteAllBytesAsync(Path.Combine(musicRoot, "song.mp3"), [1, 2, 3, 4, 5, 6]);
await File.WriteAllBytesAsync(Path.Combine(fixtureRoot, "outside.mp3"), [7, 8, 9]);
var pmvExtension = new PmvMakerExtension();
pmvExtension.SetStore(new MemoryStore(JsonSerializer.Serialize(new { musicFolder = musicRoot,
    defaults = new { colorTreatment = "matched", layout = "grid-full", segmentTagIds = new[] { 10 }, outputCodec = "h264", faceSimilarityThreshold = 0.45 } })));
pmvExtension.MapEndpoints(app);
var retryPolls = 0;
var submissionAttempts = 0;
string? submissionId = null;
app.MapPost("/jobs", async (HttpContext context) =>
{
    var requestId = context.Request.Headers["X-PMV-Request-Id"].ToString();
    if (string.IsNullOrWhiteSpace(requestId) || context.Request.Headers.ContentEncoding != "gzip")
        throw new Exception("PMV submissions need a stable request ID and compressed body.");
    if (submissionId is not null && submissionId != requestId)
        throw new Exception("A retry changed its idempotency key.");
    submissionId = requestId;
    if (Interlocked.Increment(ref submissionAttempts) == 1) { context.Abort(); return; }
    using var expanded = new GZipStream(context.Request.Body, CompressionMode.Decompress);
    using var submittedBody = await JsonDocument.ParseAsync(expanded);
    if (submittedBody.RootElement.GetProperty("sources").GetArrayLength() != 348
        || submittedBody.RootElement.GetProperty("padding").GetString()!.Length != 5_000_000)
        throw new Exception("Companion request did not retain the complete large JSON payload.");
    await context.Response.WriteAsJsonAsync(new { id = "original-job", state = "queued", progress = 0, message = "Queued" });
});
app.MapGet("/jobs/retry-test", async (HttpContext context) =>
{
    if (Interlocked.Increment(ref retryPolls) == 1) { context.Abort(); return; }
    await context.Response.WriteAsJsonAsync(new { state = "running", marker = "recovered" });
});
await app.StartAsync();
try
{
    var address = app.Services.GetRequiredService<IServer>()
        .Features.Get<IServerAddressesFeature>()!.Addresses.Single();
    using var client = new HttpClient();

    var pollMethod = typeof(PmvMakerExtension).GetMethod("CompanionJobGetWithRetryAsync", BindingFlags.NonPublic | BindingFlags.Instance)!;
    var pollTask = (Task<JsonElement>)pollMethod.Invoke(pmvExtension,
        [new PmvSettings { CompanionMode = "external", CompanionUrl = address, CompanionToken = "test" },
         "retry-test", 0L, NullLogger.Instance, CancellationToken.None])!;
    var recovered = await pollTask;
    if (retryPolls != 2 || recovered.GetProperty("marker").GetString() != "recovered")
        throw new Exception("PMV job polling did not recover from a dropped connection.");

    var submitMethod = typeof(PmvMakerExtension).GetMethod("SubmitJobWithRetryAsync", BindingFlags.NonPublic | BindingFlags.Instance)!;
    var submittedTask = (Task<CompanionJob>)submitMethod.Invoke(pmvExtension,
        [new PmvSettings { CompanionMode = "external", CompanionUrl = address, CompanionToken = "test" },
         new { sources = Enumerable.Range(1, 348).Select(id => new { id }).ToArray(), padding = new string('x', 5_000_000) },
         NullLogger.Instance, CancellationToken.None])!;
    var submitted = await submittedTask;
    if (submissionAttempts != 2 || submitted.Id != "original-job")
        throw new Exception("A dropped POST response must retry the same PMV submission.");

    var bodyFactory = typeof(PmvMakerExtension).GetMethod("JsonBody", BindingFlags.NonPublic | BindingFlags.Static)!
        .MakeGenericMethod(typeof(FolderPickerRequest));
    using var folderBody = (HttpContent)bodyFactory.Invoke(null, [new FolderPickerRequest { Kind = "musicFolder" }])!;
    var folderBytes = await folderBody.ReadAsByteArrayAsync();
    if (folderBody.Headers.ContentLength != folderBytes.Length || folderBytes.Length == 0)
        throw new Exception("Companion JSON requests must include a fixed Content-Length.");

    using var settings = await client.GetAsync(address + "/api/ext/pmv/settings");
    using var settingsJson = await ReadJson(settings, HttpStatusCode.OK);
    if (settingsJson.RootElement.GetProperty("defaults").GetProperty("sourceAudio").GetString() != "mixed")
        throw new Exception("Settings endpoint did not return the expected defaults.");
    if (settingsJson.RootElement.GetProperty("defaults").GetProperty("colorTreatment").GetString() != "natural")
        throw new Exception("Older saved settings should adopt the new None color matching default.");
    if (!settingsJson.RootElement.GetProperty("defaults").GetProperty("reencodeIncompatibleContainers").GetBoolean())
        throw new Exception("Windows Media range conversion must default on.");

    using var audioPreview = new HttpRequestMessage(HttpMethod.Get, address + "/api/ext/pmv/music-preview?path=song.mp3");
    audioPreview.Headers.Range = new System.Net.Http.Headers.RangeHeaderValue(0, 2);
    using var previewResponse = await client.SendAsync(audioPreview);
    if (previewResponse.StatusCode != HttpStatusCode.PartialContent ||
        !((await previewResponse.Content.ReadAsByteArrayAsync()).SequenceEqual(new byte[] { 1, 2, 3 })))
        throw new Exception("Music preview must support browser range playback.");
    using var escapedPreview = await client.GetAsync(address + "/api/ext/pmv/music-preview?path=" + Uri.EscapeDataString("../outside.mp3"));
    if (escapedPreview.StatusCode != HttpStatusCode.NotFound)
        throw new Exception("Music preview must not stream files outside the configured folder.");

    using var drives = await client.GetAsync(address + "/api/ext/pmv/folders");
    using var drivesJson = await ReadJson(drives, HttpStatusCode.OK);
    if (drivesJson.RootElement.GetArrayLength() == 0)
        throw new Exception("Folder browser returned no filesystem roots.");
    using var browse = await client.GetAsync(address + "/api/ext/pmv/folders?path=" + Uri.EscapeDataString(Directory.GetCurrentDirectory()));
    using var browseJson = await ReadJson(browse, HttpStatusCode.OK);
    var firstFolder = Directory.EnumerateDirectories(Directory.GetCurrentDirectory()).Select(Path.GetFileName).First();
    if (!browseJson.RootElement.EnumerateArray().Any(folder => folder.GetProperty("name").GetString() == firstFolder))
        throw new Exception("Folder browser did not return the requested directory's subfolders.");
    using var unavailable = await client.GetAsync(address + "/api/ext/pmv/folders?path=" + Uri.EscapeDataString(Path.Combine(Directory.GetCurrentDirectory(), Guid.NewGuid().ToString("N"))));
    using var unavailableJson = await ReadJson(unavailable, HttpStatusCode.BadRequest);
    if (!unavailableJson.RootElement.TryGetProperty("message", out _))
        throw new Exception("Folder browser must explain unavailable folders.");
    using var invalidSong = new HttpRequestMessage(HttpMethod.Post, address + "/api/ext/pmv/upload-audio")
        { Content = new ByteArrayContent([1, 2, 3]) };
    invalidSong.Headers.Add("X-PMV-Extension", ".exe");
    using var invalidSongResponse = await client.SendAsync(invalidSong);
    using var invalidSongJson = await ReadJson(invalidSongResponse, HttpStatusCode.BadRequest);
    if (!invalidSongJson.RootElement.GetProperty("message").GetString()!.Contains("audio file"))
        throw new Exception("Song upload should reject unsupported file types.");

    using var defaults = await client.GetAsync(address + "/api/ext/pmv/defaults");
    using var defaultsJson = await ReadJson(defaults, HttpStatusCode.OK);
    var migrated = defaultsJson.RootElement.GetProperty("defaults");
    if (migrated.GetProperty("layoutModes").EnumerateArray().Select(x => x.GetString()).SequenceEqual(["grid", "full-screen"]) == false
        || migrated.GetProperty("faceSimilarityThreshold").GetDouble() != 0.55
        || migrated.GetProperty("segmentMode").GetString() != "include"
        || migrated.GetProperty("outputCodec").GetString() != "av1")
        throw new Exception("Older layout, segment, face, and codec defaults were not migrated.");

    using var saveInclude = await client.PutAsJsonAsync(address + "/api/ext/pmv/settings",
        new PmvSettings { CompanionMode = "external", CompanionUrl = address, CompanionToken = "test",
            Defaults = new PmvOptions { SegmentMode = "include", SegmentTagIds = [] } });
    using var savedIncludeJson = await ReadJson(saveInclude, HttpStatusCode.OK);
    if (savedIncludeJson.RootElement.GetProperty("defaults").GetProperty("segmentMode").GetString() != "include")
        throw new Exception("Settings did not accept Include mode without tags.");
    using var reloadedInclude = await client.GetAsync(address + "/api/ext/pmv/settings");
    using var reloadedIncludeJson = await ReadJson(reloadedInclude, HttpStatusCode.OK);
    var savedSegments = reloadedIncludeJson.RootElement.GetProperty("defaults");
    if (savedSegments.GetProperty("segmentMode").GetString() != "include"
        || savedSegments.GetProperty("segmentTagIds").GetArrayLength() != 0)
        throw new Exception("Settings did not persist Include mode without tags.");
    using var createWithoutTags = await client.PostAsJsonAsync(address + "/api/ext/pmv/create", new PmvRequest());
    using var createWithoutTagsJson = await ReadJson(createWithoutTags, HttpStatusCode.BadRequest);
    if (!createWithoutTagsJson.RootElement.GetProperty("message").GetString()!.Contains("at least one segment tag"))
        throw new Exception("Creating a PMV must still require a tag in Include mode.");

    using var validation = await client.GetAsync(address + "/api/ext/pmv/validation");
    using var validationJson = await ReadJson(validation, HttpStatusCode.OK);
    if (validationJson.RootElement.GetProperty("state").GetString() != "failed")
        throw new Exception("Validation endpoint did not return its error state.");

    using var startValidation = await client.PostAsync(address + "/api/ext/pmv/validation", null);
    using var startJson = await ReadJson(startValidation, HttpStatusCode.BadRequest);
    if (!startJson.RootElement.TryGetProperty("message", out _))
        throw new Exception("Validation start endpoint did not return JSON.");

    using var invalidFolder = await client.PostAsJsonAsync(address + "/api/ext/pmv/pick-folder",
        new FolderPickerRequest { Kind = "unsupported" });
    using var invalidFolderJson = await ReadJson(invalidFolder, HttpStatusCode.BadRequest);
    if (!invalidFolderJson.RootElement.GetProperty("message").GetString()!.Contains("supported folder"))
        throw new Exception("Folder picker request validation was missing.");

    using var put = await client.PutAsJsonAsync(address + "/api/ext/pmv/settings",
        new PmvSettings { CompanionMode = "external", CompanionUrl = "invalid" });
    using var putJson = await ReadJson(put, HttpStatusCode.BadRequest);
    if (!putJson.RootElement.GetProperty("message").GetString()!.Contains("companion URL"))
        throw new Exception("Settings validation error was missing.");

    using var create = await client.PostAsJsonAsync(address + "/api/ext/pmv/create",
        new PmvRequest { Options = new PmvOptions() });
    using var createJson = await ReadJson(create, HttpStatusCode.BadRequest);
    if (!createJson.RootElement.GetProperty("message").GetString()!.Contains("output folder"))
        throw new Exception("Create validation error was missing.");

    Console.WriteLine("PMV endpoints returned JSON for GET, PUT, and POST.");
}
finally
{
    await app.StopAsync();
    Directory.Delete(fixtureRoot, recursive: true);
}

static async Task<JsonDocument> ReadJson(HttpResponseMessage response, HttpStatusCode expected)
{
    var body = await response.Content.ReadAsStringAsync();
    if (response.StatusCode != expected || body.Length == 0 || response.Content.Headers.ContentType?.MediaType != "application/json")
        throw new Exception($"Expected {(int)expected} JSON, got {(int)response.StatusCode} {response.Content.Headers.ContentType}: '{body}'.");
    return JsonDocument.Parse(body);
}

sealed class MemoryStore(string settingsJson) : IExtensionStore
{
    private string _settingsJson = settingsJson;
    public Task<string?> GetAsync(string key, CancellationToken ct = default) => Task.FromResult<string?>(key == "settings" ? _settingsJson : null);
    public Task SetAsync(string key, string value, CancellationToken ct = default) { if (key == "settings") _settingsJson = value; return Task.CompletedTask; }
    public Task DeleteAsync(string key, CancellationToken ct = default) { if (key == "settings") _settingsJson = ""; return Task.CompletedTask; }
    public Task<Dictionary<string, string>> GetAllAsync(CancellationToken ct = default) => Task.FromResult(new Dictionary<string, string> { ["settings"] = _settingsJson });
}
