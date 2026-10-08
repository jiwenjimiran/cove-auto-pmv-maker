using System.Diagnostics;
using System.IO.Compression;
using System.Net;
using System.Net.Http.Headers;
using System.Net.Sockets;
using System.Security.Cryptography;

namespace Cove.PmvMaker;

public sealed record LocalCompanionStatus(bool Supported, bool Running, string? Error);

/// <summary>Owns the bundled Python companion in the signed-in Windows Cove session.</summary>
public sealed class LocalCompanion(string archivePath) : IAsyncDisposable
{
    private readonly SemaphoreSlim _gate = new(1, 1);
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromMilliseconds(500) };
    private readonly object _stateGate = new();
    private readonly Queue<string> _log = new();
    private Process? _process;
    private string? _token;
    private int _port;
    private string? _error;

    public static bool IsSupported => OperatingSystem.IsWindows()
        && Environment.UserInteractive
        && Process.GetCurrentProcess().SessionId != 0
        && !string.Equals(Environment.GetEnvironmentVariable("DOTNET_RUNNING_IN_CONTAINER"), "true", StringComparison.OrdinalIgnoreCase);

    public LocalCompanionStatus Status
    {
        get
        {
            lock (_stateGate)
            {
                var running = _process is { HasExited: false };
                var error = !running && _process is not null
                    ? _error ?? "The local PMV companion stopped unexpectedly. " + LastLog()
                    : _error;
                return new(IsSupported, running, error);
            }
        }
    }

    public (string Url, string Token)? Connection
    {
        get
        {
            lock (_stateGate)
                return _process is { HasExited: false } && _token is not null
                    ? ($"http://127.0.0.1:{_port}", _token)
                    : null;
        }
    }

    public async Task<LocalCompanionStatus> EnsureRunningAsync(CancellationToken ct = default)
    {
        if (!IsSupported)
            return new(false, false, "Automatic companion control requires native Cove in a signed-in Windows desktop session.");

        await _gate.WaitAsync(ct);
        try
        {
            if (Connection is not null) return Status;
            await StopCoreAsync();
            try
            {
                if (!File.Exists(archivePath))
                    throw new FileNotFoundException("The bundled Windows companion is missing. Reinstall the extension ZIP.", archivePath);
                var runtimeDir = Path.Combine(Path.GetDirectoryName(archivePath)!, "runtime");
                Directory.CreateDirectory(runtimeDir);
                ZipFile.ExtractToDirectory(archivePath, runtimeDir, overwriteFiles: true);
                var script = Path.Combine(runtimeDir, "server.py");
                if (!File.Exists(script)) throw new FileNotFoundException("The bundled companion has no server.py.");

                var launcher = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "py.exe");
                var python = File.Exists(launcher) ? launcher : "python";
                var useLauncher = File.Exists(launcher);
                await CheckPythonAsync(python, useLauncher, ct);

                var port = FreePort();
                var token = Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
                var start = new ProcessStartInfo(python)
                {
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    WindowStyle = ProcessWindowStyle.Hidden,
                    WorkingDirectory = runtimeDir,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true
                };
                if (useLauncher) start.ArgumentList.Add("-3");
                start.ArgumentList.Add(script);
                start.ArgumentList.Add("--host");
                start.ArgumentList.Add("127.0.0.1");
                start.ArgumentList.Add("--port");
                start.ArgumentList.Add(port.ToString());
                start.ArgumentList.Add("--parent-pid");
                start.ArgumentList.Add(Environment.ProcessId.ToString());
                start.Environment["COVE_PMV_TOKEN"] = token;

                var process = Process.Start(start) ?? throw new InvalidOperationException("Python did not start the bundled companion.");
                process.OutputDataReceived += (_, e) => AppendLog(e.Data);
                process.ErrorDataReceived += (_, e) => AppendLog(e.Data);
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                lock (_stateGate)
                {
                    _process = process;
                    _port = port;
                    _token = token;
                    _error = null;
                }
                await WaitForReadyAsync(process, port, token, ct);
            }
            catch (OperationCanceledException)
            {
                await StopCoreAsync();
                throw;
            }
            catch (Exception ex)
            {
                var detail = LastLog();
                await StopCoreAsync();
                lock (_stateGate) _error = string.IsNullOrWhiteSpace(detail) ? ex.Message : ex.Message + " " + detail;
            }
            return Status;
        }
        finally
        {
            _gate.Release();
        }
    }

    public async Task StopAsync(CancellationToken ct = default)
    {
        await _gate.WaitAsync(ct);
        try { await StopCoreAsync(); }
        finally { _gate.Release(); }
    }

    public async ValueTask DisposeAsync()
    {
        await StopAsync();
        _http.Dispose();
        _gate.Dispose();
    }

    private async Task WaitForReadyAsync(Process process, int port, string token, CancellationToken ct)
    {
        for (var attempt = 0; attempt < 40; attempt++)
        {
            if (process.HasExited) throw new InvalidOperationException($"The local companion exited with code {process.ExitCode}.");
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Get, $"http://127.0.0.1:{port}/ready");
                request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
                using var response = await _http.SendAsync(request, ct);
                if (response.IsSuccessStatusCode) return;
            }
            catch (HttpRequestException) { }
            catch (TaskCanceledException) when (!ct.IsCancellationRequested) { }
            await Task.Delay(100, ct);
        }
        throw new TimeoutException("The bundled companion did not become ready.");
    }

    private static async Task CheckPythonAsync(string python, bool useLauncher, CancellationToken ct)
    {
        var start = new ProcessStartInfo(python)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            WindowStyle = ProcessWindowStyle.Hidden,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        if (useLauncher) start.ArgumentList.Add("-3");
        start.ArgumentList.Add("-c");
        start.ArgumentList.Add("import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)");
        using var process = Process.Start(start) ?? throw new InvalidOperationException("Python did not start.");
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeout.CancelAfter(TimeSpan.FromSeconds(5));
        await process.WaitForExitAsync(timeout.Token);
        if (process.ExitCode != 0) throw new InvalidOperationException("Python 3.11 or newer is required for the local PMV companion.");
    }

    private async Task StopCoreAsync()
    {
        Process? process;
        lock (_stateGate)
        {
            process = _process;
            _process = null;
            _token = null;
            _port = 0;
        }
        if (process is null) return;
        try
        {
            if (!process.HasExited) process.Kill(entireProcessTree: true);
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3));
            await process.WaitForExitAsync(timeout.Token);
        }
        catch (InvalidOperationException) { }
        catch (OperationCanceledException) { }
        finally { process.Dispose(); }
    }

    private void AppendLog(string? line)
    {
        if (string.IsNullOrWhiteSpace(line)) return;
        lock (_stateGate)
        {
            _log.Enqueue(line);
            while (_log.Count > 12) _log.Dequeue();
        }
    }

    private string LastLog()
    {
        lock (_stateGate) return string.Join(" | ", _log.TakeLast(3));
    }

    private static int FreePort()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        try { return ((IPEndPoint)listener.LocalEndpoint).Port; }
        finally { listener.Stop(); }
    }
}
