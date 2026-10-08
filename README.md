# Auto PMV Maker for Cove

Creates song-led PMVs from Cove videos using **DaVinci Resolve Studio 20.3.1** on the signed-in Windows desktop. With native Windows Cove, the extension starts its bundled companion automatically in the same desktop session. Docker uses the included external companion. Master video files are read in place; the companion only writes temporary audio and analysis data.

## Setup

1. Install Resolve Studio 20.3.1, FFmpeg/FFprobe, and Python 3.11+ on the Windows PC. Open Resolve and enable local external scripting in **Preferences → System → General**. Install `yt-dlp` with `python -m pip install yt-dlp` only if you want YouTube audio.
2. Install `AutoPmvMaker.zip` from the [releases page](https://github.com/jiwenjimiran/cove-auto-pmv-maker/releases) using **Cove Settings → Extensions → Install from URL** or **Install from ZIP**. For a source checkout, run `npm install` in `frontend`, then `powershell -File scripts/package.ps1` from the repository root to build both ZIPs.
3. In **Auto PMV Maker** settings, keep **Automatic (native Windows Cove)**, set an output folder, and click **Check Resolve**. Cove extracts the bundled companion, starts it hidden, and manages its private connection token. If you change Resolve's external scripting preference, save it and use **Restart engine** in Cove before checking again. Once Studio is running, click **Run Resolve compatibility check**. This renders 18 short fixture combinations and saves the result for that Resolve version. Cove stops the companion when it exits.
4. For Windows Docker, choose **External**, click **Download Windows companion**, extract it on the Resolve PC, and run `Start Companion Docker.cmd`. Enter the displayed URL and token in Cove and add container-to-Windows path mappings for each media root and the output folder. The output folder must be readable by Cove for scan import. Limit TCP 8765 in Windows Firewall to Docker's network.

The automatic mode uses the companion bundled with the installed extension, so updating the extension updates that companion. In external mode, update the companion ZIP after upgrading the extension. The companion ZIP is also published separately for PCs that cannot access Cove's settings page.

The current Cove UI needs [the included host patch](patches/cove-ui.patch) for performer/studio/tag bulk actions and detail Videos-tab actions. It is already applied to the sibling `cove` checkout in this workspace; another sibling checkout can run `git apply ../cove-auto-pmv-maker/patches/cove-ui.patch` from its root, then rebuild the Cove UI.

The Resolve compatibility check runs from Cove settings after setup and after each Resolve version change. It checks the output format, duration, audio stream, and three-pane colors. Manual inspection of transition quality and beat timing is still needed before relying on the first Studio installation. The companion health endpoint checks scripting access, Studio, FFmpeg, and the check marker. Cove refuses to queue a render without a healthy companion or output folder.

This is a preview release. The Resolve Studio render and compatibility checks still require a Studio installation and have not yet been validated in Studio.

## Current implementation notes

- Source selection supports videos, performers, studios, and tags. Tag actions use only timed video segments. Detail Videos tabs pass their current video filter and search query to the server, which resolves all matching pages.
- The popup supports Cove audio search, recursive folder browsing, YouTube URL, and selected Cove video audio. Per-job controls override saved defaults.
- Jobs are exclusive in Cove and serialized again in the companion. Cancellation propagates to FFmpeg and Resolve. The companion returns used video and segment IDs for metadata import.
- Default render is H.264 MP4 with a song-led cut grid, 9:16 three-pane or 16:9 full-screen layout, and a final audio limiter. Three-pane clips are placed on separate Resolve tracks. Resolve timeline overlays implement stepped dissolves, flashes, and glitches; color treatment uses CDL.
- Resolve's scripting API must be tested with a short render on the target Studio installation before relying on crop, scaling, grading, and compositing behavior. Use **Run Resolve compatibility check** in Cove settings to render all three styles, both layouts, and all source-audio modes. It checks H.264/AAC output and samples pane colors.

## Checks

Run `python -m unittest discover tests`, `python -m py_compile companion/*.py`, `dotnet run --project tests/PathChecks/PathChecks.csproj`, `dotnet run --project tests/EndpointChecks/EndpointChecks.csproj`, `dotnet run --project tests/LocalCompanionChecks/LocalCompanionChecks.csproj`, `dotnet build src/PmvMaker/PmvMaker.csproj`, and `cd frontend; npm run build`.
