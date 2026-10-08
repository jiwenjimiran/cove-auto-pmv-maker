using Cove.PmvMaker;

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
