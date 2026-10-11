using Cove.PmvMaker;
using Cove.Core.DTOs;
using Cove.Core.Entities;
using System.Reflection;

var settings = new PmvSettings
{
    PathMappings =
    [
        new("/media", @"D:\Media"),
        new("/media/music", @"E:\Music")
    ]
};
Assert(PmvMakerExtension.ToHost("/media/video/a.mp4", settings), @"D:\Media\video\a.mp4");
Assert(PmvMakerExtension.ToHost("/media/music/song.wav", settings), @"E:\Music\song.wav");
Assert(PmvMakerExtension.ToHost("/mediax/no.mp4", settings), "/mediax/no.mp4");
Assert(PmvMakerExtension.ToCove(@"D:\Media\output\PMVMAKER_Multi.mp4", settings), "/media/output/PMVMAKER_Multi.mp4");

SourceSegment[] timed = [new(1, 0, 10, 10, "A"), new(2, 4, 6, 20, "B"), new(3, 8, 12, null, null)];
var included = SegmentSelection.Apply(timed, timed, "include", [10]);
if (included.Count != 1 || included[0].Id != 1) throw new Exception("Include must use selected timed tags only.");
var excluded = SegmentSelection.Apply(timed, timed, "exclude", [20]);
if (excluded.Count != 3 || excluded.Any(s => s.Id == 2)
    || excluded[0].Start != 0 || excluded[0].End != 4
    || excluded[1].Start != 6 || excluded[1].End != 10)
    throw new Exception("Exclude must subtract selected tag time from overlapping segments.");
if (SegmentSelection.Apply([], [], "exclude", []).Count != 0)
    throw new Exception("Videos without timed segments must be ineligible.");
var sourceFilter = typeof(PmvMakerExtension).GetMethod("FilterSourcesForLayout", BindingFlags.NonPublic | BindingFlags.Static)
    ?? throw new Exception("Source eligibility filter unavailable.");
SourceVideo TestVideo(int id, string path) => new(id, path, 20, 1920, 1080, 30,
    null, null, [], [], [], []);
var sourceScope = new ScopeResult([
    TestVideo(1, @"\\server\share\E030 - Sandra.WMV"),
    TestVideo(2, @"\\server\share\E032 - Carmen.asf"),
    TestVideo(3, @"\\server\share\usable.mp4")], ["Earlier exclusion"], null, "video");
var filteredSources = (ScopeResult)(sourceFilter.Invoke(null, [sourceScope, new PmvOptions { ReencodeIncompatibleContainers = false }])
    ?? throw new Exception("Source eligibility filter returned null."));
if (filteredSources.Videos.Select(v => v.Id).Single() != 3
    || filteredSources.Exclusions.Count != 3
    || !filteredSources.Exclusions[1].Contains("E030 - Sandra.WMV")
    || !filteredSources.Exclusions[2].Contains("E032 - Carmen.asf"))
    throw new Exception("Unsupported Windows Media must be excluded before rendering with visible reasons.");
var reencodedSources = (ScopeResult)(sourceFilter.Invoke(null, [sourceScope, new PmvOptions()])
    ?? throw new Exception("Source eligibility filter returned null."));
if (reencodedSources.Videos.Count != 3 || reencodedSources.Exclusions.Count != 1)
    throw new Exception("Windows Media must stay eligible when range conversion is enabled.");
int nextSpanId = 0;
ResolvedSpan[] displayed =
[
    new("merged", SegmentHostType.Video, 7, 10, 28, "user", null, 10, "A", null, null, false, [101, 102]),
    new("point", SegmentHostType.Video, 7, 31, 31, "user", null, 20, "B", null, null, true, [103])
];
var fullRanges = FullSegmentRanges.Build(displayed, 25, ref nextSpanId);
if (fullRanges.Count != 1 || fullRanges[0].Source.Start != 10 || fullRanges[0].Source.End != 25
    || fullRanges[0].Source.TagId != 10 || fullRanges[0].Span.SegmentIds.Count != 2)
    throw new Exception("PMV must use clipped, merged display spans and ignore raw point records.");

var root = Path.Combine(Path.GetTempPath(), "pmv-path-check-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
try
{
    Assert(PmvNaming.Proposed(root, "PMVMAKER_Multi"), "PMVMAKER_Multi.mp4");
    File.WriteAllText(Path.Combine(root, "PMVMAKER_Multi.mp4"), "fixture");
    Assert(PmvNaming.Proposed(root, "PMVMAKER_Multi"), "PMVMAKER_Multi(1).mp4");
    File.WriteAllText(Path.Combine(root, "PMVMAKER_Multi(1).drp"), "fixture");
    Assert(PmvNaming.Proposed(root, "PMVMAKER_Multi", saveProject: true), "PMVMAKER_Multi(2).mp4");
}
finally
{
    File.Delete(Path.Combine(root, "PMVMAKER_Multi.mp4"));
    File.Delete(Path.Combine(root, "PMVMAKER_Multi(1).drp"));
    Directory.Delete(root);
}
Console.WriteLine("Path mappings and filename collisions passed.");

static void Assert(string actual, string expected)
{
    if (actual != expected) throw new Exception($"Expected {expected}, got {actual}");
}
