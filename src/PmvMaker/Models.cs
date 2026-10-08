using System.Text.Json;

namespace Cove.PmvMaker;

public sealed record PathMapping(string ContainerPrefix, string HostPrefix);

public sealed class FolderPickerRequest
{
    public string Kind { get; set; } = "";
    public string InitialPath { get; set; } = "";
}

public sealed class PmvSettings
{
    public string CompanionMode { get; set; } = "auto";
    public string CompanionUrl { get; set; } = "http://127.0.0.1:8765";
    public string CompanionToken { get; set; } = "";
    public bool CompanionConfigured { get; set; }
    public bool SkipSetupChecks { get; set; }
    public string OutputFolder { get; set; } = "";
    public string ProjectFolder { get; set; } = "";
    public string MusicFolder { get; set; } = "";
    public List<PathMapping> PathMappings { get; set; } = [];
    public int ColorDefaultsVersion { get; set; } = 1;
    public PmvOptions Defaults { get; set; } = new();
}

public sealed class PmvOptions
{
    public string Layout { get; set; } = "three-pane";
    public bool UseVerticalVideosOnly { get; set; }
    public string SelectionMode { get; set; } = "center";
    public bool KeepFaceCentered { get; set; } = true;
    public string Style { get; set; } = "rhythmic-polish";
    public string SourceAudio { get; set; } = "mixed";
    public double PacingMin { get; set; } = 0.4;
    public double PacingMax { get; set; } = 0.7;
    public double BeatAdherence { get; set; } = 0.95;
    public double MinClipSeconds { get; set; } = 1.0;
    public double MaxClipSeconds { get; set; } = 5.0;
    public double SourceDiversity { get; set; } = 0.8;
    public string[] TransitionFamilies { get; set; } = ["cut", "dissolve"];
    public double TransitionIntensityMin { get; set; } = 0.15;
    public double TransitionIntensityMax { get; set; } = 0.35;
    public double MotionIntensityMin { get; set; } = 0.15;
    public double MotionIntensityMax { get; set; } = 0.35;
    public double FlashIntensityMin { get; set; }
    public double FlashIntensityMax { get; set; }
    public double GlitchIntensityMin { get; set; }
    public double GlitchIntensityMax { get; set; }
    public string ColorTreatment { get; set; } = "natural";
    public double? SongTrimStart { get; set; }
    public double? SongTrimEnd { get; set; }
    public int? OutputFps { get; set; }
    public bool SaveProject { get; set; }
    public bool ScanToCove { get; set; } = true;
    public bool KeepPerformers { get; set; } = true;
    public bool KeepTags { get; set; } = true;
    public bool AddPmvTag { get; set; } = true;
    public bool AddAutoPmvTag { get; set; } = true;
}

public sealed class SourceScope
{
    public string EntityType { get; set; } = "video";
    public List<int> EntityIds { get; set; } = [];
    public bool IncludeChildStudios { get; set; }
    public JsonElement? VideoFilter { get; set; }
    public JsonElement? VideoFilterExpression { get; set; }
    public string? FindQuery { get; set; }
}

public sealed class AudioSelection
{
    public string Kind { get; set; } = "cove";
    public int? CoveAudioId { get; set; }
    public int? CoveVideoId { get; set; }
    public string? Path { get; set; }
    public string? Url { get; set; }
    public string? UploadId { get; set; }
}

public sealed class PmvRequest
{
    public SourceScope Scope { get; set; } = new();
    public AudioSelection Audio { get; set; } = new();
    public PmvOptions? Options { get; set; }
}

public sealed record SourceVideo(int Id, string Path, double Duration, int Width, int Height, double Fps,
    int? StudioId, string? StudioName, int[] PerformerIds, string[] PerformerNames, IReadOnlyList<SourceSegment> Segments,
    IReadOnlyList<SourceRange> SavedRanges);
public sealed record SourceSegment(int Id, double Start, double End, int? TagId, string? TagName);
public sealed record SourceRange(double Start, double End);
public sealed record ScopeResult(IReadOnlyList<SourceVideo> Videos, IReadOnlyList<string> Exclusions,
    string? LaunchName, string LaunchKind);

public sealed record CompanionJob(string Id, string State, double Progress, string? Message,
    string? OutputPath, int[]? UsedVideoIds, int[]? UsedSegmentIds, string? Error);
