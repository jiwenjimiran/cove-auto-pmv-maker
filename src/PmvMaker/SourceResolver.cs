using System.Text.Json;
using System.Text.Json.Serialization;
using Cove.Core.Entities;
using Cove.Core.Auth;
using Cove.Core.Interfaces;
using Cove.Data;
using Microsoft.EntityFrameworkCore;

namespace Cove.PmvMaker;

public sealed class SourceResolver(CoveContext db, IVideoRepository videoRepository, IAuthorizationService authorization)
{
    private static readonly JsonSerializerOptions FilterJson = new(JsonSerializerDefaults.Web)
    {
        Converters = { new JsonStringEnumConverter() }
    };

    public async Task<ScopeResult> ResolveAsync(SourceScope scope, CovePrincipal? principal, CancellationToken ct, PmvOptions? options = null)
    {
        var ids = scope.EntityIds.Where(id => id > 0).Distinct().ToArray();
        if (ids.Length == 0) throw new ArgumentException("Select at least one source.");
        var kind = scope.EntityType.ToLowerInvariant().TrimEnd('s');
        var (entityKind, permission) = kind switch
        {
            "video" => (EntityKinds.Video, "videos.read"),
            "performer" => (EntityKinds.Performer, "performers.read"),
            "studio" => (EntityKinds.Studio, "studios.read"),
            "tag" => (EntityKinds.Tag, "tags.read"),
            "segment" => (EntityKinds.Segment, "segments.read"),
            _ => throw new ArgumentException("Unsupported source type: " + scope.EntityType)
        };
        var selectedDecisions = await authorization.AuthorizeManyAsync(principal, permission,
            ids.Select(id => new EntityRef(entityKind, id.ToString())).ToArray(), ct);
        if (selectedDecisions.Any(d => !d.Allowed)) throw new UnauthorizedAccessException("Source selection is not accessible.");
        var selectedTagIds = options?.SegmentTagIds?.Where(id => id > 0).Distinct().ToArray() ?? [];
        if (selectedTagIds.Length > 0)
        {
            var tagDecisions = await authorization.AuthorizeManyAsync(principal, "tags.read",
                selectedTagIds.Select(id => new EntityRef(EntityKinds.Tag, id.ToString())).ToArray(), ct);
            if (tagDecisions.Any(d => !d.Allowed)) throw new UnauthorizedAccessException("Segment list contains a tag you cannot access.");
        }
        var launchName = ids.Length == 1 && kind is "performer" or "studio" or "tag"
            ? kind switch
            {
                "performer" => await db.Performers.Where(p => p.Id == ids[0]).Select(p => p.Name).FirstOrDefaultAsync(ct),
                "studio" => await db.Studios.Where(s => s.Id == ids[0]).Select(s => s.Name).FirstOrDefaultAsync(ct),
                _ => await db.Tags.Where(t => t.Id == ids[0]).Select(t => t.Name).FirstOrDefaultAsync(ct)
            } : null;

        int[] videoIds;
        if (scope.VideoFilter is { } filterJson && kind is "performer" or "studio" or "tag")
        {
            var filter = filterJson.Deserialize<VideoFilter>(FilterJson);
            var expression = scope.VideoFilterExpression is { } expressionJson
                ? expressionJson.Deserialize<FilterExpression<VideoFilter>>(FilterJson) : null;
            var matching = new List<int>();
            for (var page = 1; ; page++)
            {
                var (items, total) = await videoRepository.FindAsync(filter,
                    new FindFilter { Q = scope.FindQuery, Page = page, PerPage = 1000 }, ct, expression);
                matching.AddRange(items.Select(v => v.Id));
                if (items.Count == 0 || matching.Count >= total) break;
            }
            videoIds = matching.ToArray();
        }
        else videoIds = kind switch
        {
            "video" => ids,
            "performer" => await db.Set<VideoPerformer>().Where(x => ids.Contains(x.PerformerId)).Select(x => x.VideoId).Distinct().ToArrayAsync(ct),
            "studio" => await StudioVideoIdsAsync(ids, scope.IncludeChildStudios, ct),
            "tag" => await db.Segments.Where(s => s.HostType == SegmentHostType.Video && s.TagId.HasValue && ids.Contains(s.TagId.Value))
                .Select(s => s.HostId).Distinct().ToArrayAsync(ct),
            "segment" => await db.Segments.Where(s => s.HostType == SegmentHostType.Video && ids.Contains(s.Id))
                .Select(s => s.HostId).Distinct().ToArrayAsync(ct),
            _ => throw new ArgumentException("Unsupported source type: " + scope.EntityType)
        };
        if (kind == "tag" || kind == "performer" || kind == "studio")
        {
            // A detail filter narrows the entity relationship; it cannot broaden it.
            var related = kind switch
            {
                "performer" => await db.Set<VideoPerformer>().Where(x => ids.Contains(x.PerformerId)).Select(x => x.VideoId).Distinct().ToArrayAsync(ct),
                "studio" => await StudioVideoIdsAsync(ids, scope.IncludeChildStudios, ct),
                _ => await db.Segments.Where(s => s.HostType == SegmentHostType.Video && s.TagId.HasValue && ids.Contains(s.TagId.Value))
                    .Select(s => s.HostId).Distinct().ToArrayAsync(ct)
            };
            videoIds = videoIds.Intersect(related).ToArray();
        }
        if (videoIds.Length == 0) return new([], ["No videos match the selected source and filters."], launchName, kind);
        var allowed = new List<int>();
        foreach (var batch in videoIds.Chunk(1000))
        {
            var decisions = await authorization.AuthorizeManyAsync(principal, "videos.read",
                batch.Select(id => new EntityRef(EntityKinds.Video, id.ToString())).ToArray(), ct);
            allowed.AddRange(batch.Where((_, index) => decisions[index].Allowed));
        }
        videoIds = allowed.ToArray();

        var rows = await db.Videos.AsNoTracking().Where(v => videoIds.Contains(v.Id))
            .Include(v => v.Files).Include(v => v.Studio).Include(v => v.VideoPerformers).ThenInclude(x => x.Performer)
            .AsSplitQuery().ToListAsync(ct);
        var segments = await db.Segments.AsNoTracking().Where(s => s.HostType == SegmentHostType.Video && videoIds.Contains(s.HostId))
            .Include(s => s.Tag).ToListAsync(ct);
        var byVideo = segments.GroupBy(s => s.HostId).ToDictionary(g => g.Key, g => g.ToList());
        var result = new List<SourceVideo>();
        var exclusions = new List<string>();
        foreach (var video in rows)
        {
            if (video.Title?.Contains("PMVMAKER", StringComparison.OrdinalIgnoreCase) == true)
            {
                exclusions.Add($"Video {video.Id}: title contains PMVMAKER");
                continue;
            }
            var file = video.Files.OrderByDescending(f => f.Id == video.PrimaryFileId)
                .ThenByDescending(f => f.Width * (long)f.Height).FirstOrDefault();
            if (file is null || string.IsNullOrWhiteSpace(file.Path) || file.Duration <= 0)
            {
                exclusions.Add($"Video {video.Id}: no usable master file");
                continue;
            }
            if (!File.Exists(file.Path))
            {
                exclusions.Add($"Video {video.Id}: missing media {file.Path}");
                continue;
            }
            var ranges = byVideo.GetValueOrDefault(video.Id, [])
                .Where(s => !s.EndSec.HasValue || s.EndSec.Value > s.StartSec)
                .Select(s => new SourceSegment(s.Id, Math.Max(0, s.StartSec), Math.Min(file.Duration, s.EndSec ?? file.Duration), s.TagId, s.Tag?.Name))
                .Where(s => s.End > s.Start).ToArray();
            IReadOnlyList<SourceSegment>? allowedRanges = kind switch
            {
                "tag" => ranges.Where(s => s.TagId.HasValue && ids.Contains(s.TagId.Value)).ToArray(),
                "segment" => ranges.Where(s => ids.Contains(s.Id)).ToArray(),
                _ => null
            };
            if (selectedTagIds.Length > 0)
            {
                var tagged = ranges.Where(s => s.TagId.HasValue && selectedTagIds.Contains(s.TagId.Value)).ToArray();
                allowedRanges = allowedRanges is null ? tagged : allowedRanges
                    .SelectMany(selected => tagged.Select(taggedRange =>
                        new SourceSegment(selected.Id, Math.Max(selected.Start, taggedRange.Start),
                            Math.Min(selected.End, taggedRange.End), selected.TagId, selected.TagName)))
                    .Where(s => s.End > s.Start).ToArray();
            }
            if (allowedRanges is { Count: 0 })
            {
                exclusions.Add($"Video {video.Id}: no matching timed segment range");
                continue;
            }
            var savedRanges = video.ClipStartSec.HasValue && video.ClipEndSec.HasValue && video.ClipEndSec > video.ClipStartSec
                ? new[] { new SourceRange(Math.Max(0, video.ClipStartSec.Value), Math.Min(file.Duration, video.ClipEndSec.Value)) }
                : [];
            result.Add(new(video.Id, file.Path, file.Duration, file.Width, file.Height, file.FrameRate,
                video.StudioId, video.Studio?.Name, video.VideoPerformers.Select(x => x.PerformerId).ToArray(),
                video.VideoPerformers.Select(x => x.Performer?.Name ?? "").ToArray(), ranges, savedRanges, allowedRanges));
        }
        return new(result, exclusions, launchName, kind);
    }

    private async Task<int[]> StudioVideoIdsAsync(int[] ids, bool children, CancellationToken ct)
    {
        var selected = ids.ToHashSet();
        if (children)
        {
            // Traverse in batches; EF cannot translate a recursive CTE portably.
            var frontier = ids;
            while (frontier.Length > 0)
            {
                var next = await db.Studios.AsNoTracking().Where(s => s.ParentId.HasValue && frontier.Contains(s.ParentId.Value))
                    .Select(s => s.Id).ToArrayAsync(ct);
                frontier = next.Where(selected.Add).ToArray();
            }
        }
        return await db.Videos.AsNoTracking().Where(v => v.StudioId.HasValue && selected.Contains(v.StudioId.Value))
            .Select(v => v.Id).ToArrayAsync(ct);
    }
}

public static class PmvNaming
{
    public static string Proposed(string folder, string stem, string projectFolder = "", bool saveProject = false)
    {
        if (string.IsNullOrWhiteSpace(folder)) return stem + ".mp4";
        for (var suffix = 0; ; suffix++)
        {
            var name = stem + (suffix == 0 ? "" : $"({suffix})") + ".mp4";
            var path = Path.Combine(folder, name);
            var drp = Path.Combine(string.IsNullOrWhiteSpace(projectFolder) ? folder : projectFolder,
                Path.GetFileNameWithoutExtension(name) + ".drp");
            if (!File.Exists(path) && !File.Exists(path + ".reserve") && (!saveProject || !File.Exists(drp))) return name;
        }
    }

    public static string Stem(ScopeResult scope, IReadOnlyCollection<SourceVideo> used, IReadOnlyCollection<int> usedSegmentIds)
    {
        string? name = scope.LaunchName;
        if (string.IsNullOrWhiteSpace(name))
        {
            var commonPerformers = used.Select(v => v.PerformerIds.ToHashSet()).Aggregate((a, b) => { a.IntersectWith(b); return a; });
            var sharedNames = used.SelectMany(v => v.PerformerIds.Zip(v.PerformerNames)).Where(x => commonPerformers.Contains(x.First))
                .Select(x => x.Second).Distinct(StringComparer.OrdinalIgnoreCase).Order(StringComparer.OrdinalIgnoreCase).ToArray();
            name = sharedNames.Length == 0 ? null : string.Join("_", sharedNames);
            if (name is null && used.Select(v => v.StudioId).Distinct().Count() == 1)
                name = used.First().StudioName;
            if (name is null)
            {
                var commonTags = used.Select(v => v.Segments.Where(s => usedSegmentIds.Contains(s.Id) && s.TagId.HasValue)
                    .Select(s => s.TagName).Where(s => s is not null).ToHashSet(StringComparer.OrdinalIgnoreCase))
                    .Aggregate((a, b) => { a.IntersectWith(b); return a; });
                if (commonTags.Count > 0) name = string.Join("_", commonTags.Order(StringComparer.OrdinalIgnoreCase));
            }
        }
        name = string.IsNullOrWhiteSpace(name) ? "Multi" : name;
        var invalid = Path.GetInvalidFileNameChars().ToHashSet();
        var clean = new string(name.Select(c => invalid.Contains(c) || c is '<' or '>' or ':' or '"' or '/' or '\\' or '|' or '?' or '*' || char.IsControl(c) ? '_' : c).ToArray()).Trim(' ', '.');
        return "PMVMAKER_" + (string.IsNullOrWhiteSpace(clean) ? "Multi" : clean[..Math.Min(clean.Length, 120)]);
    }

}
