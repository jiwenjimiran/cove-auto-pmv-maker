namespace Cove.PmvMaker;

internal sealed class OrderProgress(Cove.Core.Interfaces.IJobProgress parent, int index, int count, long number)
    : Cove.Core.Interfaces.IJobProgress
{
    public void Report(double progress, string? subTask = null) =>
        parent.Report((index + Math.Clamp(progress, 0, 1)) / count,
            $"ORDER{number} · version {index + 1}/{count} · {subTask}");
}

internal sealed class PhaseProgress(Cove.Core.Interfaces.IJobProgress parent, double start, double length)
    : Cove.Core.Interfaces.IJobProgress
{
    public void Report(double progress, string? subTask = null) =>
        parent.Report(start + length * Math.Clamp(progress, 0, 1), subTask);
}
