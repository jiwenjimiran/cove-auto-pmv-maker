namespace Cove.PmvMaker;

internal static class OrderPipeline
{
    // Two submitted versions keep preparation fed while Resolve renders. The
    // companion enforces the shared limits across different orders/clients.
    internal static async Task RunAsync(int count, Func<int, CancellationToken, Task> run, CancellationToken ct)
    {
        using var stopped = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var pending = new List<Task>();
        async Task RunVersion(int index)
        {
            try { await run(index, stopped.Token); }
            catch (OperationCanceledException) { stopped.Cancel(); throw; }
        }
        try
        {
            for (var index = 0; index < count; index++)
            {
                stopped.Token.ThrowIfCancellationRequested();
                if (pending.Count == 2)
                {
                    var finished = await Task.WhenAny(pending);
                    await finished;
                    pending.Remove(finished);
                }
                stopped.Token.ThrowIfCancellationRequested();
                pending.Add(RunVersion(index));
            }
            await Task.WhenAll(pending);
        }
        catch
        {
            stopped.Cancel();
            // Drain siblings before their shared uploads are released.
            try { await Task.WhenAll(pending); } catch { }
            throw;
        }
    }
}
