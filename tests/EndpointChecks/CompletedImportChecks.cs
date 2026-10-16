using Cove.PmvMaker;

internal static class CompletedImportChecks
{
    internal static void Run()
    {
        var scan = CompletedPmvImport.FullScan("C:/library/order_1.mp4");
        Check(scan.Paths!.SequenceEqual(["C:/library/order_1.mp4"]) && scan.Rescan
            && scan.GenerateCovers && scan.GeneratePreviews && scan.GenerateSprites
            && scan.GeneratePhashes && scan.GenerateMd5, "Full import scan must include only the rendered file and all video assets, even after immediate import.");

        var sources = Enumerable.Range(1, 122).Select(id => new SourceVideo(id, $"source{id}.mp4", 200,
            1920, 1080, 30, null, null, [id, 200], [], [], [])).ToArray();
        var scope = new ScopeResult(sources, [], null, "video");
        var job = new CompanionJob("job", "complete", 100, null, "order_1.mp4", [2, 5, 2, 999], [], null);
        Check(CompletedPmvImport.Performers(job, scope).SetEquals([2, 5, 200]),
            "Only actually used source videos contribute their cast; duplicates and unknown videos are ignored.");
        Check(CompletedPmvImport.Performers(job with { MatchedPerformerIds = [2] }, scope).SetEquals([2, 5, 200]),
            "Face matching must not restrict the source-video cast.");
        Check(CompletedPmvImport.Performers(job with { UsedVideoIds = null }, scope).Count == 0,
            "Missing used-video provenance must not fall back to all selected videos.");
        Console.WriteLine("Full scan options and performer attribution across 122 selected videos passed.");
    }

    private static void Check(bool value, string message)
    {
        if (!value) throw new Exception(message);
    }
}
