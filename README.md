# Auto PMV Maker for Cove

Creates song-led PMVs from Cove videos using **DaVinci Resolve Studio** on the signed-in Windows desktop. With native Windows Cove, the extension starts its bundled companion automatically in the same desktop session. Docker uses the included external companion. Master video files are read in place; the companion only writes temporary audio and analysis data.

## Setup

1. Install Resolve Studio, FFmpeg/FFprobe, and Python 3.11+ on the Windows PC. Open Resolve and enable local external scripting in **Preferences â†’ System â†’ General**. Install `yt-dlp` for YouTube audio and `opencv-python-headless` for Face slice with `py -3 -m pip install -r companion/requirements.txt` from a source checkout, or from the extracted companion ZIP.
2. Install `AutoPmvMaker.zip` from the [releases page](https://github.com/jiwenjimiran/cove-auto-pmv-maker/releases) using **Cove Settings â†’ Extensions â†’ Install from URL** or **Install from ZIP**. For a source checkout, run `npm install` in `frontend`, then `powershell -File scripts/package.ps1` from the repository root to build both ZIPs.
3. In **Auto PMV Maker - Setup required**, click **Check Resolve**, then **Run Resolve compatibility check**. The job settings appear when both pass. You can choose **Skip setup checks** on first setup to open settings immediately; the choice is saved. PMV jobs still check Resolve and all media paths before rendering. Cove extracts the bundled companion, starts it hidden, and manages its private connection token. The optional compatibility check renders 18 short fixture combinations and saves the result for this Resolve version.
   Choose the output folder from Cove's video library tree. Music and optional project folders use an inline filesystem tree inside Cove; Project folder is under Advanced settings. You can also choose and upload a backing song directly in Create PMV without configuring a music folder. Information popovers close when clicked outside.
4. For Windows Docker, choose **External**, click **Download Windows companion**, extract it on the Resolve PC, and run `Start Companion Docker.cmd`. Enter the displayed URL and token in Cove and add container-to-Windows path mappings for each media root and the output folder. The output folder must be readable by Cove for scan import. Limit TCP 8765 in Windows Firewall to Docker's network.
   Save the companion connection and mappings before browsing music or project folders. Choose output from Cove's video library tree.

The automatic mode uses the companion bundled with the installed extension, so updating the extension updates that companion. In external mode, update the companion ZIP after upgrading the extension. The companion ZIP is also published separately for PCs that cannot access Cove's settings page.

The current Cove UI needs [the included host patch](patches/cove-ui.patch) for performer/studio/tag bulk actions and detail Videos-tab actions. It is already applied to the sibling `cove` checkout in this workspace; another sibling checkout can run `git apply ../cove-auto-pmv-maker/patches/cove-ui.patch` from its root, then rebuild the Cove UI.

The Resolve compatibility check is available from Cove settings after setup and after each Resolve version change. It checks the output format, duration, audio stream, and three-pane colors. Manual inspection of transition quality and beat timing is still needed before relying on the first Studio installation. The companion health endpoint checks scripting access and FFmpeg. Cove refuses to queue a render without a healthy companion or output folder, even when setup checks were skipped.

This is a preview release. The Resolve render and compatibility checks have been exercised with Studio 21.1.1.10; other versions require their own check.

## Current implementation notes

- Source selection supports videos, performers, studios, and tags. Tag actions use only timed video segments. Detail Videos tabs pass their current video filter and search query to the server, which resolves all matching pages.
- The popup supports Cove audio search with selectable, playable results; a scrollable music-folder tree with track previews; direct audio-file upload; YouTube URL; and selected Cove video audio. A backing track must be selected before Create is enabled. Uploaded songs (up to 200 MB) are sent to the Windows companion, removed after the PMV job, or removed when the popup is cancelled. Per-job controls override saved defaults.
- Jobs are exclusive in Cove and serialized again in the companion. Cancellation propagates to FFmpeg and Resolve. Cove job progress names the video being analyzed, face detection when enabled, the clip being assembled, and brightness sampling when selected. The companion returns used video and segment IDs for metadata import.
- Default render is H.264 MP4 with a song-led cut grid, three side-by-side portrait panes in a landscape frame or full screen, and a final audio limiter. A common 4:3 source ratio produces 4:3 output. Three-pane sources can be limited to portrait videos or cropped from landscape footage using random, center, or detected-face slices. Face slice rejects sampled ranges without a face and can follow face movement. Resolve timeline overlays implement stepped dissolves, flashes, and glitches; optional color adjustments use CDL.
- Color matching defaults to None. Match brightness samples the first two seconds of each used video; Warm and Cool apply subtle channel shifts without that sampling step.
- Resolve's scripting API must be tested with a short render on the target Studio installation before relying on crop, scaling, grading, and compositing behavior. Use **Run Resolve compatibility check** in Cove settings to render all three styles, both layouts, and all source-audio modes. It checks H.264/AAC output and samples pane colors.
- The Resolve adapter uses the current timeline-property API where available, retries a newly appended clip while Resolve initializes it, and sets project-level fill scaling so clips can inherit it if a per-clip scaling override is rejected. Any remaining property rejection identifies the video, track, timeline position, requested value, and Resolve's current value.

## Checks

Run `python -m unittest discover tests`, `python -m py_compile companion/*.py`, `dotnet run --project tests/PathChecks/PathChecks.csproj`, `dotnet run --project tests/EndpointChecks/EndpointChecks.csproj`, `dotnet run --project tests/LocalCompanionChecks/LocalCompanionChecks.csproj`, `dotnet build src/PmvMaker/PmvMaker.csproj`, and `cd frontend; npm run build`.
