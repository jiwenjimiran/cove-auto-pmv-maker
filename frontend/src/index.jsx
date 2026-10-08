import React from "@cove/runtime/react";
import { extensionFetch } from "@cove/runtime/api";
import "./style.css";

const { useEffect, useState } = React;
const base = "/api/ext/pmv";
const companionAsset = "/api/extensions/assets/io.github.jiwenjimiran.auto-pmv-maker/companion/AutoPmvMakerCompanion.zip";
async function api(path, method = "GET", body) {
  const response = await extensionFetch(base + path, { method,
    headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  const raw = await response.text();
  let result = null;
  if (raw) {
    try { result = JSON.parse(raw); }
    catch { throw new Error(`Cove returned an invalid response for ${path} (${response.status}).`); }
  }
  if (!response.ok) throw new Error(result?.message || result?.error || `Request failed (${response.status})`);
  if (result === null) throw new Error(`Cove returned an empty response for ${path} (${response.status}).`);
  return result;
}

async function downloadCompanion() {
  const response = await extensionFetch(companionAsset);
  if (!response.ok) throw new Error(`Companion download failed (${response.status}).`);
  const archive = await response.blob();
  if (!archive.size) throw new Error("Cove returned an empty companion ZIP.");
  const url = URL.createObjectURL(archive);
  const link = document.createElement("a");
  link.href = url;
  link.download = "AutoPmvMakerCompanion.zip";
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 60000);
}

export function openPmv(_action, payload) {
  window.dispatchEvent(new CustomEvent("pmvmaker:open", { detail: payload }));
  return { cancelled: true };
}

const styleHelp = {
  "rhythmic-polish": "Precise cuts, restrained accents, and matched color.",
  "high-energy": "Faster cuts, stronger motion, and controlled accents.",
  cinematic: "Longer shots, softer pacing, and cohesive color."
};
const stylePresets = {
  "rhythmic-polish": { motionIntensity: 0.25, transitionIntensity: 0.25, flashIntensity: 0, glitchIntensity: 0, colorTreatment: "matched" },
  "high-energy": { motionIntensity: 0.7, transitionIntensity: 0.3, flashIntensity: 0.35, glitchIntensity: 0.25, colorTreatment: "matched" },
  cinematic: { motionIntensity: 0.2, transitionIntensity: 0.5, flashIntensity: 0, glitchIntensity: 0, colorTreatment: "warm" }
};
const optionHelp = {
  layout: "Three portrait clips play side by side in a 16:9 frame. Full screen plays one clip across the frame.",
  style: "Applies a starting set of motion, transition, flash, glitch, and color controls. You can change them below.",
  sourceAudio: "Muted uses only the backing song. Mixed adds brief source accents. All keeps source audio throughout. The song level stays constant.",
  pacing: "Higher values make the edit change clips more often.",
  beatAdherence: "Higher values move cuts closer to detected song beats and phrase points.",
  sourceDiversity: "Higher values cycle through more different source videos before repeating one.",
  transitionIntensity: "Controls the length of the stepped dissolves when dissolves are enabled.",
  motionIntensity: "Controls the zoom used for High Energy accents and Cinematic shots.",
  flashIntensity: "Controls the brightness of brief flash accents on highlighted cuts.",
  glitchIntensity: "Controls the strength of brief offset and difference overlays on highlighted cuts.",
  minClipSeconds: "Shortest allowed time between cuts, in seconds.",
  maxClipSeconds: "Longest preferred clip length, in seconds.",
  songTrimStart: "Optional starting point in the backing song, in seconds. Leave blank to start at the beginning.",
  songTrimEnd: "Optional ending point in the backing song, in seconds. Leave blank to use the full track.",
  outputWidth: "Optional output width in pixels. Leave blank to use the resolution chosen from all eligible sources.",
  outputHeight: "Optional output height in pixels. Leave blank to use the resolution chosen from all eligible sources.",
  outputFps: "Optional output frame rate. Leave blank for 60 fps only when every source is 60 fps, otherwise 30 fps.",
  transitionFamilies: "Cuts switch immediately. Dissolves briefly blend the next clip over the previous one.",
  colorTreatment: "Matched balances source brightness; Warm and Cool add subtle color shifts; Natural leaves color alone.",
  saveProject: "Exports a Resolve .drp project to the project folder, or beside the MP4 if that folder is blank.",
  scanToCove: "Imports the finished MP4 into Cove after Resolve renders it.",
  keepPerformers: "Adds performers linked to footage that actually appears in the finished PMV.",
  keepTags: "Adds tags from timed segments that actually appear in the finished PMV. General video tags are not inherited.",
  addPmvTag: "Adds the PMV tag to the imported video."
};

function InfoButton({ label, help }) {
  const [open, setOpen] = useState(false);
  const id = React.useId();
  return <span className="pmv-info">
    <button type="button" className="pmv-info-button" aria-label={`About ${label}`} aria-expanded={open} aria-controls={id}
      onClick={() => setOpen(value => !value)}>i</button>
    {open && <span id={id} className="pmv-info-text" role="note">{help}</span>}
  </span>;
}

function Control({ label, help, children, className = "" }) {
  const id = React.useId();
  return <div className={`pmv-control ${className}`}>
    <div className="pmv-control-heading"><label htmlFor={id}>{label}</label><InfoButton label={label} help={help} /></div>
    {children(id)}
  </div>;
}

function HelpAction({ label, help, children }) {
  return <span className="pmv-action-help">{children}<InfoButton label={label} help={help} /></span>;
}

function FolderSetting({ label, help, value, onBrowse, onClear, loading, disabled, optional }) {
  return <Control label={label} help={help}>{id => <div className="pmv-folder-row">
    <input id={id} type="text" readOnly value={value || ""} placeholder="Choose a folder" />
    <button type="button" disabled={disabled} onClick={onBrowse}>{loading ? "Opening…" : "Browse…"}</button>
    {optional && value && <button type="button" onClick={onClear}>Clear</button>}
  </div>}</Control>;
}

const defaultOptions = {
  layout: "three-pane", style: "rhythmic-polish", sourceAudio: "mixed", pacing: 0.5,
  beatAdherence: 0.8, minClipSeconds: 1, maxClipSeconds: 5, sourceDiversity: 0.8,
  transitionFamilies: ["cut", "dissolve"], transitionIntensity: 0.25, motionIntensity: 0.25,
  flashIntensity: 0, glitchIntensity: 0, colorTreatment: "matched", songTrimStart: null,
  songTrimEnd: null, outputWidth: null, outputHeight: null, outputFps: null,
  saveProject: false, scanToCove: true, keepPerformers: true, keepTags: true, addPmvTag: true
};

function OptionForm({ options, setOptions }) {
  const set = (key, value) => setOptions(current => ({ ...current, [key]: value }));
  return <>
    <div className="pmv-grid">
      <Control label="Layout" help={optionHelp.layout}>{id => <select id={id} value={options.layout} onChange={e => set("layout", e.target.value)}><option value="three-pane">Three portrait panes · 16:9 frame</option><option value="full-screen">Full screen · 16:9</option></select>}</Control>
      <Control label="Style" help={optionHelp.style}>{id => <><select id={id} value={options.style} onChange={e => setOptions(current => ({ ...current, style: e.target.value, ...stylePresets[e.target.value] }))}>{Object.keys(styleHelp).map(x => <option key={x} value={x}>{x.replaceAll("-", " ")}</option>)}</select><small>{styleHelp[options.style]}</small></>}</Control>
      <Control label="Source audio" help={optionHelp.sourceAudio}>{id => <select id={id} value={options.sourceAudio} onChange={e => set("sourceAudio", e.target.value)}><option value="muted">Muted</option><option value="mixed">Mixed · brief accents</option><option value="all">All source audio</option></select>}</Control>
    </div>
    <details><summary>Advanced edit controls</summary><div className="pmv-grid">
      {[["pacing", "Pacing"], ["beatAdherence", "Beat adherence"], ["sourceDiversity", "Source diversity"], ["transitionIntensity", "Transition intensity"], ["motionIntensity", "Motion"], ["flashIntensity", "Flash"], ["glitchIntensity", "Glitch"]].map(([key, label]) => <Control key={key} label={label} help={optionHelp[key]}>{id => <div className="pmv-range"><input id={id} type="range" min="0" max="1" step="0.05" value={options[key]} onChange={e => set(key, Number(e.target.value))} /><output>{Number(options[key]).toFixed(2)}</output></div>}</Control>)}
      {[["minClipSeconds", "Minimum clip (sec)"], ["maxClipSeconds", "Maximum clip (sec)"], ["songTrimStart", "Song start (sec)"], ["songTrimEnd", "Song end (sec)"], ["outputWidth", "Width override"], ["outputHeight", "Height override"], ["outputFps", "FPS override"]].map(([key, label]) => <Control key={key} label={label} help={optionHelp[key]}>{id => <input id={id} type="number" min="0" step="any" value={options[key] ?? ""} onChange={e => set(key, e.target.value === "" ? null : Number(e.target.value))} />}</Control>)}
      <Control label="Transitions" help={optionHelp.transitionFamilies}>{id => <select id={id} value={options.transitionFamilies?.join(",") || "cut"} onChange={e => set("transitionFamilies", e.target.value.split(","))}><option value="cut">Cuts</option><option value="cut,dissolve">Cuts and dissolves</option></select>}</Control>
      <Control label="Color treatment" help={optionHelp.colorTreatment}>{id => <select id={id} value={options.colorTreatment} onChange={e => set("colorTreatment", e.target.value)}><option value="matched">Matched</option><option value="warm">Warm</option><option value="cool">Cool</option><option value="natural">Natural</option></select>}</Control>
      {[["saveProject", "Save project (.drp)"], ["scanToCove", "Scan to Cove"], ["keepPerformers", "Keep performers"], ["keepTags", "Keep used segment tags"], ["addPmvTag", "Add PMV tag"]].map(([key, label]) => <Control key={key} label={label} help={optionHelp[key]} className="pmv-toggle">{id => <input id={id} type="checkbox" checked={!!options[key]} onChange={e => set(key, e.target.checked)} />}</Control>)}
    </div></details>
  </>;
}

function useSettings(path = "/settings") {
  const [settings, setSettings] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => { api(path).then(setSettings).catch(e => setError(e.message)); }, [path]);
  return [settings, setSettings, error, setError];
}

export function PmvSettingsPanel() {
  const [settings, setSettings, error, setError] = useSettings();
  const [message, setMessage] = useState("");
  const [health, setHealth] = useState(null);
  const [local, setLocal] = useState(null);
  const [validation, setValidation] = useState(null);
  const [mappingText, setMappingText] = useState("[]");
  const [mappingValid, setMappingValid] = useState(true);
  const [picking, setPicking] = useState(null);
  useEffect(() => { if (settings) setMappingText(JSON.stringify(settings.pathMappings || [], null, 2)); }, [!!settings]);
  useEffect(() => { if (settings?.companionMode === "auto") api("/local-companion").then(setLocal).catch(e => setError(e.message)); }, [settings?.companionMode]);
  useEffect(() => {
    if (!settings) return;
    const refresh = () => api("/validation").then(setValidation).catch(e => setError(e.message));
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => window.clearInterval(timer);
  }, [!!settings]);
  if (!settings) return <div className="pmv-settings">{error || "Loading PMV settings…"}</div>;
  const set = (key, value) => setSettings(current => ({ ...current, [key]: value }));
  const defaults = { ...defaultOptions, ...settings.defaults };
  const automatic = settings.companionMode === "auto";
  const browseFolder = async key => {
    setPicking(key);
    setError("");
    try {
      const result = await api("/pick-folder", "POST", { kind: key, initialPath: settings[key] || "" });
      if (result.path) set(key, result.path);
    } catch (e) { setError(e.message); }
    finally { setPicking(null); }
  };
  return <div className="pmv-settings">
    <h3>Auto PMV Maker</h3>
    <Control label="Connection" help="Automatic starts the bundled Windows engine with Cove. External connects to the Windows companion when Cove runs in Docker or on another PC.">{id => <select id={id} value={settings.companionMode || "auto"} onChange={e => set("companionMode", e.target.value)}><option value="auto">Automatic (native Windows Cove)</option><option value="external">External (Docker or another PC)</option></select>}</Control>
    {automatic ? <>
      <p>Cove starts the bundled engine in your Windows desktop session. No download, launcher, URL, or token is needed.</p>
      <p role="status">Engine: {local ? local.running ? "running" : local.error || "stopped" : "checking…"}</p>
      <div className="pmv-actions"><HelpAction label="Restart engine" help="Restarts the bundled Windows engine after a Resolve scripting change. An active PMV job will be interrupted."><button type="button" onClick={async () => { try { setLocal(await api("/local-companion/start", "POST")); setHealth(null); setError(""); } catch (e) { setError(e.message); } }}>Restart engine</button></HelpAction></div>
      <small>Restart the engine after changing Resolve's scripting setting. This interrupts any active PMV render.</small>
    </> : <details open><summary>External companion setup</summary>
      <p>For Cove in Docker, run the bundled companion on the Windows desktop and connect it here.</p>
      <div className="pmv-actions"><HelpAction label="Download Windows companion" help="Downloads the matching Windows companion ZIP for external or Docker mode."><button type="button" onClick={async () => { try { await downloadCompanion(); setMessage("Companion ZIP downloaded."); } catch (e) { setError(e.message); } }}>Download Windows companion</button></HelpAction></div>
      <small>Extract the ZIP, run Start Companion Docker.cmd, then enter the displayed URL and token.</small>
      <div className="pmv-grid">
        {[["companionUrl", "Companion URL", "The local network address printed by the Windows companion."], ["companionToken", "Companion token", "The private token printed by the Windows companion. Leave blank to keep a saved token."]].map(([key, label, help]) => <Control key={key} label={label} help={help}>{id => <input id={id} type={key === "companionToken" ? "password" : "text"} value={settings[key] || ""} onChange={e => set(key, e.target.value)} />}</Control>)}
      </div>
      {settings.companionConfigured && <small>A companion token is saved. Leave the field blank to keep it.</small>}
      <Control label="Container → Windows path mappings (JSON)" help="For Docker, pair each Cove container path with the Windows path that points to the same files. Save mappings before browsing folders.">{id => <textarea id={id} rows="4" value={mappingText} onChange={e => {
        setMappingText(e.target.value);
        try { const value = JSON.parse(e.target.value); if (!Array.isArray(value)) throw new Error(); set("pathMappings", value); setMappingValid(true); setError(""); }
        catch { setMappingValid(false); setError("Path mappings must be a JSON array."); }
      }} />}</Control>
    </details>}
    <div className="pmv-grid">
      <FolderSetting label="Output folder" help="Where finished MP4 files are saved. Cove must also be able to read this folder to import the result." value={settings.outputFolder} onBrowse={() => browseFolder("outputFolder")} loading={picking === "outputFolder"} disabled={!!picking} />
      <FolderSetting label="Project folder (optional)" help="Where exported Resolve .drp files go when Save project is enabled. Leave blank to save beside the MP4." value={settings.projectFolder} onBrowse={() => browseFolder("projectFolder")} onClear={() => set("projectFolder", "")} loading={picking === "projectFolder"} disabled={!!picking} optional />
      <FolderSetting label="Music folder" help="Root folder for browsing backing songs in the Create PMV popup. Subfolders can be browsed there." value={settings.musicFolder} onBrowse={() => browseFolder("musicFolder")} onClear={() => set("musicFolder", "")} loading={picking === "musicFolder"} disabled={!!picking} optional />
    </div>
    <h4>Job defaults</h4><OptionForm options={defaults} setOptions={value => set("defaults", typeof value === "function" ? value(defaults) : value)} />
    <div className="pmv-actions">
      <HelpAction label="Check Resolve" help="Checks whether the companion can connect to an installed Resolve Studio and required media tools."><button onClick={async () => { try { setHealth(await api("/health")); } catch (e) { setError(e.message); } }}>Check Resolve</button></HelpAction>
      <HelpAction label="Run Resolve compatibility check" help="Renders 18 short test combinations in Resolve and validates their output for this Resolve version."><button disabled={validation?.state === "queued" || validation?.state === "running"} onClick={async () => { try { setValidation(await api("/validation", "POST")); setError(""); } catch (e) { setError(e.message); } }}>Run Resolve compatibility check</button></HelpAction>
      <HelpAction label="Save settings" help="Saves folders, companion connection, path mappings, and job defaults in Cove."><button disabled={!automatic && !mappingValid} onClick={async () => { try { setSettings(await api("/settings", "PUT", settings)); if (automatic) setLocal(await api("/local-companion")); setMessage("Settings saved."); setError(""); } catch (e) { setError(e.message); } }}>Save settings</button></HelpAction>
    </div>
    {health && <p role="status">{health.ok ? `${health.product} ${health.version} ready` : health.error}</p>}
    {validation && validation.state !== "idle" && <p role="status">Compatibility check: {validation.message}{validation.error ? ` — ${validation.error}` : ""}</p>}
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
  </div>;
}

function PmvDialog({ context, close }) {
  const [settings, , settingsError] = useSettings("/defaults");
  const [options, setOptions] = useState(defaultOptions);
  const [audio, setAudio] = useState({ kind: "cove" });
  const [query, setQuery] = useState("");
  const [audioItems, setAudioItems] = useState([]);
  const [videoItems, setVideoItems] = useState([]);
  const [videoQuery, setVideoQuery] = useState("");
  const [folderItems, setFolderItems] = useState([]);
  const [folderPath, setFolderPath] = useState("");
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (settings) setOptions({ ...defaultOptions, ...settings.defaults }); }, [settings]);
  useEffect(() => { if (audio.kind === "cove") api("/audio?q=" + encodeURIComponent(query)).then(setAudioItems).catch(e => setError(e.message)); }, [audio.kind, query]);
  useEffect(() => { if (audio.kind === "video") api("/videos?q=" + encodeURIComponent(videoQuery)).then(setVideoItems).catch(e => setError(e.message)); }, [audio.kind, videoQuery]);
  useEffect(() => { if (audio.kind === "folder") api("/music?path=" + encodeURIComponent(folderPath)).then(setFolderItems).catch(e => setError(e.message)); }, [audio.kind, folderPath]);
  const scope = { entityType: context.entityType, entityIds: context.entityIds || context.selectedIds,
    includeChildStudios: !!context.includeChildStudios, videoFilter: context.videoFilter || null,
    videoFilterExpression: context.videoFilterExpression || null, findQuery: context.findQuery || null };
  const request = { scope, audio, options };
  useEffect(() => { api("/preview", "POST", request).then(setPreview).catch(e => setError(e.message)); }, [JSON.stringify(scope)]);
  const create = async () => { setBusy(true); setError(""); try {
    const result = await api("/create", "POST", request);
    window.alert(`PMV queued. Job: ${result.jobId}`); close();
  } catch (e) { setError(e.message); } finally { setBusy(false); } };
  return <div className="pmv-overlay" role="dialog" aria-modal="true" aria-label="Create PMV"><div className="pmv-dialog">
    <header><h2>Create PMV</h2><button onClick={close} aria-label="Close">×</button></header>
    <p>{preview ? `${preview.eligibleCount} eligible sources · ${preview.proposedFilename}` : "Checking sources…"}</p>
    {!!preview?.exclusions?.length && <details><summary>{preview.exclusions.length} excluded sources</summary><ul>{preview.exclusions.map((x, i) => <li key={i}>{x}</li>)}</ul></details>}
    <fieldset><legend>Backing audio</legend><div className="pmv-grid">
      <Control label="Source" help="Choose a backing song from Cove, the configured music folder, YouTube, or a Cove video's audio.">{id => <select id={id} value={audio.kind} onChange={e => setAudio(e.target.value === "video" && context.entityType === "video" && scope.entityIds.length === 1
        ? { kind: "video", coveVideoId: scope.entityIds[0] } : { kind: e.target.value })}><option value="cove">Cove audio</option><option value="folder">Music folder</option><option value="youtube">YouTube URL</option><option value="video">Cove video audio</option></select>}</Control>
      {audio.kind === "cove" && <><Control label="Search" help="Filter Cove's audio library by title.">{id => <input id={id} value={query} onChange={e => setQuery(e.target.value)} />}</Control><Control label="Track" help="The Cove audio record used as the backing song.">{id => <select id={id} value={audio.coveAudioId || ""} onChange={e => setAudio({ kind: "cove", coveAudioId: Number(e.target.value) })}><option value="">Choose track</option>{audioItems.map(x => <option value={x.id} key={x.id}>{x.title || x.minPath}</option>)}</select>}</Control></>}
      {audio.kind === "folder" && <><Control label="Folder" help="Browse subfolders of the music folder set in Auto PMV Maker settings. Choose an audio file below.">{id => <div className="pmv-folder-row"><input id={id} readOnly value={folderPath || "Music folder"} /><button type="button" disabled={!folderPath} onClick={() => setFolderPath(folderPath.split(/[\\/]/).slice(0, -1).join("/"))}>Up</button></div>}</Control><div className="pmv-file-list">{folderItems.map(x => <button type="button" key={x.path} onClick={() => x.kind === "folder" ? setFolderPath(x.path) : setAudio({ kind: "folder", path: x.path })}>{x.kind === "folder" ? "📁" : "♫"} {x.name}</button>)}</div><p>{audio.path || "Choose a file"}</p></>}
      {audio.kind === "youtube" && <Control label="YouTube URL" help="Paste an HTTPS YouTube video URL. The companion downloads only its audio for the PMV.">{id => <input id={id} type="url" value={audio.url || ""} onChange={e => setAudio({ kind: "youtube", url: e.target.value })} />}</Control>}
      {audio.kind === "video" && <><Control label="Search Cove videos" help="Filter Cove videos by title to find the source of your backing audio.">{id => <input id={id} value={videoQuery} onChange={e => setVideoQuery(e.target.value)} />}</Control><Control label="Video" help="Extracts this Cove video's audio as the backing song.">{id => <select id={id} value={audio.coveVideoId || ""} onChange={e => setAudio({ kind: "video", coveVideoId: Number(e.target.value) })}><option value="">Choose video</option>{videoItems.map(x => <option key={x.id} value={x.id}>{x.title || x.minPath || `Video ${x.id}`}</option>)}</select>}</Control></>}
    </div></fieldset>
    <OptionForm options={options} setOptions={setOptions} />
    {(error || settingsError) && <p role="alert">{error || settingsError}</p>}
    <footer><HelpAction label="Cancel" help="Closes this popup without queueing a PMV."><button onClick={close}>Cancel</button></HelpAction><HelpAction label="Create" help="Starts a PMV job with the current source selection, backing audio, and edit controls."><button disabled={busy || !preview?.eligibleCount} onClick={create}>{busy ? "Queueing…" : "Create"}</button></HelpAction></footer>
  </div></div>;
}

export function PmvLauncher() {
  const [context, setContext] = useState(null);
  useEffect(() => { const open = e => setContext(e.detail); window.addEventListener("pmvmaker:open", open);
    return () => window.removeEventListener("pmvmaker:open", open); }, []);
  return context ? <PmvDialog context={context} close={() => setContext(null)} /> : null;
}

export default { components: { PmvLauncher, PmvSettingsPanel }, actionHandlers: { openPmv } };
