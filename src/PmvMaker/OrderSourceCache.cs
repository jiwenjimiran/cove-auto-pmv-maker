using System.Text.Json;
using System.Runtime.CompilerServices;

[assembly: InternalsVisibleTo("EndpointChecks")]

namespace Cove.PmvMaker;

// One cache per order and principal. Layout/effects are applied AFTER this cache;
// differing source scopes or segment filters must never reuse another selection.
internal sealed class OrderSourceCache
{
    private readonly Dictionary<string, ScopeResult> _sources = new();

    public async Task<ScopeResult> ResolveAsync(PmvRequest request,
        Func<CancellationToken, Task<ScopeResult>> resolve, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        var key = JsonSerializer.Serialize(new
        {
            request.Scope,
            request.Options!.SegmentMode,
            Tags = request.Options.SegmentTagIds.Distinct().Order().ToArray()
        });
        if (_sources.TryGetValue(key, out var sources)) return sources;
        sources = await resolve(ct);
        ct.ThrowIfCancellationRequested();
        _sources.Add(key, sources);
        return sources;
    }
}
