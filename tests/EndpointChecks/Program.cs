using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
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

    using var settings = await client.GetAsync(address + "/api/ext/pmv/settings");
    using var settingsJson = await ReadJson(settings, HttpStatusCode.OK);
    if (settingsJson.RootElement.GetProperty("defaults").GetProperty("sourceAudio").GetString() != "mixed")
        throw new Exception("Settings endpoint did not return the expected defaults.");

    using var defaults = await client.GetAsync(address + "/api/ext/pmv/defaults");
    using var defaultsJson = await ReadJson(defaults, HttpStatusCode.OK);
    if (defaultsJson.RootElement.GetProperty("defaults").GetProperty("layout").GetString() != "three-pane")
        throw new Exception("Defaults endpoint did not return JSON.");

    using var put = await client.PutAsJsonAsync(address + "/api/ext/pmv/settings",
        new PmvSettings { CompanionUrl = "invalid" });
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
