# Auto PMV Maker for Cove

Creates song-led PMVs from Cove videos using **DaVinci Resolve Studio 20.3.1** on the signed-in Windows desktop. The Cove extension can run natively or in Windows Docker. The installable extension ZIP includes the Windows companion download; the companion runs as a separate process beside Resolve. Master video files are read in place; the companion only writes temporary audio and analysis data.

## Setup

1. Install Resolve Studio 20.3.1, FFmpeg/FFprobe, and Python 3.11+ on the Windows PC. Open Resolve and enable local external scripting in **Preferences → System → General**.
2. Install `AutoPmvMaker.zip` from the [releases page](https://github.com/jiwenjimiran/cove-auto-pmv-maker/releases) using **Cove Settings → Extensions → Install from URL** or **Install from ZIP**. The extension ZIP contains the companion. In **Auto PMV Maker** settings, click **Download Windows companion** and extract that ZIP on the Windows PC running Resolve. For a source checkout, run `npm install` in `frontend`, then `powershell -File scripts/package.ps1` from the repository root to build both ZIPs.
3. Double-click `Start Companion.cmd` in the extracted folder. It generates a reusable token and shows the URL and token to enter in Cove. If Cove runs in Windows Docker, use `Start Companion Docker.cmd` and limit TCP 8765 in Windows Firewall to Docker's network. Keep the launcher window open while rendering. Run `python -m pip install -r requirements.txt` in that folder if you want YouTube audio.
4. In Cove extension settings, enter the URL and token shown by the launcher and an output folder. For Docker, add container-to-Windows path mappings for each media root and the output folder. The output folder must be readable by Cove for scan import.

When updating the extension, download its companion again and extract it over the existing companion folder. This keeps the saved `.companion-token`; keep that token private. The companion ZIP is also published as a separate release asset for PCs that cannot access Cove's settings page.

The current Cove UI needs [the included host patch](patches/cove-ui.patch) for performer/studio/tag bulk actions and detail Videos-tab actions. It is already applied to the sibling `cove` checkout in this workspace; another sibling checkout can run `git apply ../cove-auto-pmv-maker/patches/cove-ui.patch` from its root, then rebuild the Cove UI.

Run `Validate Resolve.cmd` from the extracted companion folder (or `python companion/smoke.py` from a source checkout) once after setup and after each Resolve version change. It renders short fixtures before writing a local validation marker. The companion health endpoint requires a token and checks scripting access, Studio, FFmpeg, and that marker. Cove refuses to queue a render without a healthy companion or output folder.

This is a preview release. The Resolve Studio render and compatibility checks still require a Studio installation and have not yet been validated in Studio.

## Current implementation notes

- Source selection supports videos, performers, studios, and tags. Tag actions use only timed video segments. Detail Videos tabs pass their current video filter and search query to the server, which resolves all matching pages.
- The popup supports Cove audio search, recursive folder browsing, YouTube URL, and selected Cove video audio. Per-job controls override saved defaults.
- Jobs are exclusive in Cove and serialized again in the companion. Cancellation propagates to FFmpeg and Resolve. The companion returns used video and segment IDs for metadata import.
- Default render is H.264 MP4 with a song-led cut grid, 9:16 three-pane or 16:9 full-screen layout, and a final audio limiter. Three-pane clips are placed on separate Resolve tracks. Resolve timeline overlays implement stepped dissolves, flashes, and glitches; color treatment uses CDL.
- Resolve's scripting API must be tested with a short render on the target Studio installation before relying on crop, scaling, grading, and compositing behavior. Run `python companion/smoke.py` to render all three styles, both layouts, and all source-audio modes. It checks H.264/AAC output and samples pane colors.

## Checks

Run `python -m unittest discover tests`, `python -m py_compile companion/*.py`, `dotnet run --project tests/PathChecks/PathChecks.csproj`, `dotnet run --project tests/EndpointChecks/EndpointChecks.csproj`, `dotnet build src/PmvMaker/PmvMaker.csproj`, and `cd frontend; npm run build`.
