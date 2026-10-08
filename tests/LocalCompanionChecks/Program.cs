using System.IO.Compression;
using System.Net;
using System.Net.Http.Headers;
using Cove.PmvMaker;

if (!LocalCompanion.IsSupported)
{
    Console.WriteLine("Local companion lifecycle check skipped outside interactive Windows.");
    return;
}

var repo = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../"));
var source = Path.Combine(repo, "companion");
var temp = Path.Combine(Path.GetTempPath(), "pmv-local-check-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(temp);
try
{
    var archive = Path.Combine(temp, "AutoPmvMakerCompanion.zip");
    ZipFile.CreateFromDirectory(source, archive);
    await using var local = new LocalCompanion(archive);
    var status = await local.EnsureRunningAsync();
    if (!status.Running || local.Connection is null)
        throw new Exception("Local companion did not start: " + status.Error);
    var connection = local.Connection.Value;
    using var client = new HttpClient();
    using var denied = await client.GetAsync(connection.Url + "/ready");
    if (denied.StatusCode != HttpStatusCode.Unauthorized)
        throw new Exception("Unauthenticated local request was accepted.");
    using var ready = new HttpRequestMessage(HttpMethod.Get, connection.Url + "/ready");
    ready.Headers.Authorization = new AuthenticationHeaderValue("Bearer", connection.Token);
    using var accepted = await client.SendAsync(ready);
    if (!accepted.IsSuccessStatusCode) throw new Exception("Authenticated local request failed.");
    var restarted = await local.RestartAsync();
    if (!restarted.Running || local.Connection is null || local.Connection.Value.Token == connection.Token)
        throw new Exception("Local companion did not restart with a new token: " + restarted.Error);
    var fresh = local.Connection.Value;
    using var newReady = new HttpRequestMessage(HttpMethod.Get, fresh.Url + "/ready");
    newReady.Headers.Authorization = new AuthenticationHeaderValue("Bearer", fresh.Token);
    using var newAccepted = await client.SendAsync(newReady);
    if (!newAccepted.IsSuccessStatusCode) throw new Exception("Restarted local companion did not authenticate.");
    await local.StopAsync();
    if (local.Status.Running || local.Connection is not null)
        throw new Exception("Local companion did not stop.");
    Console.WriteLine("Local companion started, authenticated, restarted, and stopped.");
}
finally
{
    var root = Path.GetFullPath(Path.GetTempPath());
    var target = Path.GetFullPath(temp);
    if (!target.StartsWith(root, StringComparison.OrdinalIgnoreCase) || target == root)
        throw new Exception("Refusing to delete a path outside the temporary directory.");
    Directory.Delete(target, recursive: true);
}
