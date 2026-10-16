using Cove.Core.Interfaces;

namespace Cove.PmvMaker;

internal static class CompletedPmvImport
{
    internal static ScanOperationOptions FullScan(string path) => new()
    {
        Paths = [path],
        // Import already stored the file. Force it through the normal scan even
        // on Cove versions without IncludeUnchangedFilesInAssetGeneration.
        Rescan = true,
        GenerateCovers = true,
        GeneratePreviews = true,
        GenerateSprites = true,
        GeneratePhashes = true,
        GenerateMd5 = true
    };

    internal static HashSet<int> Performers(CompanionJob job, ScopeResult scope)
    {
        var usedIds = (job.UsedVideoIds ?? []).ToHashSet();
        return scope.Videos.Where(video => usedIds.Contains(video.Id))
            .SelectMany(video => video.PerformerIds).Where(id => id > 0).ToHashSet();
    }
}
