namespace Cove.PmvMaker;

internal sealed class OrderProgress(Cove.Core.Interfaces.IJobProgress parent, int count, long number)
{
    private readonly object _gate = new();
    private readonly double[] _values = new double[count];
    private readonly string?[] _messages = new string?[count];

    internal Cove.Core.Interfaces.IJobProgress ForVersion(int index) => new VersionProgress(this, index);

    private void Report(int index, double progress, string? message)
    {
        lock (_gate)
        {
            _values[index] = Math.Max(_values[index], Math.Clamp(progress, 0, 1));
            _messages[index] = message;
            var active = Enumerable.Range(0, count).Where(i => _messages[i] is not null && _values[i] < 1)
                .Select(i => $"v{i + 1}: {_messages[i]}");
            var done = _values.Count(value => value >= 1);
            var detail = string.Join(" | ", active);
            parent.Report(_values.Sum() / count,
                $"ORDER{number} · {done}/{count} finished" + (detail.Length == 0 ? "" : " · " + detail));
        }
    }

    private sealed class VersionProgress(OrderProgress owner, int index) : Cove.Core.Interfaces.IJobProgress
    {
        public void Report(double progress, string? subTask = null) => owner.Report(index, progress, subTask);
    }
}

internal sealed class PhaseProgress(Cove.Core.Interfaces.IJobProgress parent, double start, double length)
    : Cove.Core.Interfaces.IJobProgress
{
    public void Report(double progress, string? subTask = null) =>
        parent.Report(start + length * Math.Clamp(progress, 0, 1), subTask);
}
