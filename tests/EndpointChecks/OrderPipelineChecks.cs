using Cove.PmvMaker;

internal static class OrderPipelineChecks
{
    internal static async Task RunAsync()
    {
        var entered = Enumerable.Range(0, 3).Select(_ => new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously)).ToArray();
        var release = Enumerable.Range(0, 3).Select(_ => new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously)).ToArray();
        var imported = new System.Collections.Concurrent.ConcurrentBag<int>();
        var pipeline = OrderPipeline.RunAsync(3, async (index, ct) =>
        {
            entered[index].SetResult();
            await release[index].Task.WaitAsync(ct);
            imported.Add(index);
        }, CancellationToken.None);
        await Task.WhenAll(entered[0].Task, entered[1].Task).WaitAsync(TimeSpan.FromSeconds(3));
        Check(!entered[2].Task.IsCompleted, "Only two versions may be submitted ahead.");
        release[0].SetResult();
        await entered[2].Task.WaitAsync(TimeSpan.FromSeconds(3));
        Check(imported.Contains(0) && !pipeline.IsCompleted, "A completed version must finish import while other versions are active.");
        release[1].SetResult();
        release[2].SetResult();
        await pipeline.WaitAsync(TimeSpan.FromSeconds(3));

        var siblingStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var drained = false;
        var calls = 0;
        try
        {
            await OrderPipeline.RunAsync(3, async (index, ct) =>
            {
                Interlocked.Increment(ref calls);
                if (index == 0)
                {
                    await siblingStarted.Task.WaitAsync(ct);
                    throw new OperationCanceledException("Companion cancelled");
                }
                siblingStarted.TrySetResult();
                try { await Task.Delay(Timeout.Infinite, ct); }
                finally { drained = true; }
            }, CancellationToken.None).WaitAsync(TimeSpan.FromSeconds(3));
            throw new Exception("Cancellation was lost.");
        }
        catch (OperationCanceledException) { }
        Check(drained && calls == 2, "Cancellation must drain the sibling before shared upload cleanup and stop later versions.");

        var progress = new CapturedProgress();
        var group = new OrderProgress(progress, 3, 42);
        group.ForVersion(0).Report(.8, "Rendering in Resolve");
        group.ForVersion(1).Report(.4, "Animating shot");
        Check(progress.Message.Contains("Rendering in Resolve") && progress.Message.Contains("Animating shot"), "Both active stages must be visible.");
        var previous = progress.Value;
        group.ForVersion(1).Report(.1, "Older event");
        Check(progress.Value == previous, "Interleaved stage reports must not move overall progress backward.");

        var cache = new OrderSourceCache();
        var lookupStarted = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var lookupRelease = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var lookups = 0;
        var request = new PmvRequest { Options = new PmvOptions() };
        async Task<ScopeResult> Resolve(CancellationToken ct)
        {
            Interlocked.Increment(ref lookups);
            lookupStarted.TrySetResult();
            await lookupRelease.Task.WaitAsync(ct);
            return new([], [], null, "video");
        }
        var first = cache.ResolveAsync(request, Resolve, CancellationToken.None);
        await lookupStarted.Task;
        var second = cache.ResolveAsync(request, Resolve, CancellationToken.None);
        lookupRelease.SetResult();
        await Task.WhenAll(first, second);
        Check(lookups == 1, "Concurrent versions must reuse a single source lookup.");
        Console.WriteLine("Pipeline overlap, bounded submissions, immediate completion, cancellation, concurrent caching, and aggregate progress passed.");
    }

    private static void Check(bool condition, string message) { if (!condition) throw new Exception(message); }
    private sealed class CapturedProgress : Cove.Core.Interfaces.IJobProgress
    {
        public double Value;
        public string Message = "";
        public void Report(double progress, string? subTask = null) { Value = progress; Message = subTask ?? ""; }
    }
}
