using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using System.Reflection;
using Cove.PmvMaker;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;

var builder = WebApplication.CreateBuilder(args);
builder.Logging.ClearProviders();
builder.WebHost.UseUrls("http://127.0.0.1:0");
var app = builder.Build();
new PmvMakerExtension().MapEndpoints(app);
await app.StartAsync();
try
{
    var address = app.Services.GetRequiredService<IServer>()
        .Features.Get<IServerAddressesFeature>()!.Addresses.Single();
    using var client = new HttpClient();

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
    if (defaultsJson.RootElement.GetProperty("defaults").GetProperty("layout").GetString() != "three-pane")
        throw new Exception("Defaults endpoint did not return JSON.");

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

    using var create = await client.PostAsJsonAsync(address + "/api/ext/pmv/create", new PmvRequest());
    using var createJson = await ReadJson(create, HttpStatusCode.BadRequest);
    if (!createJson.RootElement.GetProperty("message").GetString()!.Contains("output folder"))
        throw new Exception("Create validation error was missing.");

    Console.WriteLine("PMV endpoints returned JSON for GET, PUT, and POST.");
}
finally
{
    await app.StopAsync();
}

static async Task<JsonDocument> ReadJson(HttpResponseMessage response, HttpStatusCode expected)
{
    var body = await response.Content.ReadAsStringAsync();
    if (response.StatusCode != expected || body.Length == 0 || response.Content.Headers.ContentType?.MediaType != "application/json")
        throw new Exception($"Expected {(int)expected} JSON, got {(int)response.StatusCode} {response.Content.Headers.ContentType}: '{body}'.");
    return JsonDocument.Parse(body);
}
