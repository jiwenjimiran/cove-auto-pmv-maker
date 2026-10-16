import React from "@cove/runtime/react";
import { extensionFetch } from "@cove/runtime/api";
import "./style.css";

const { useEffect, useRef, useState } = React;
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
  if (!response.ok) { const error = new Error(result?.message || result?.error || `Request failed (${response.status})`); error.status = response.status; throw error; }
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

async function uploadSongFile(file) {
  const extension = file.name.match(/\.[^.]+$/)?.[0]?.toLowerCase() || "";
  if (!/^(\.mp3|\.wav|\.flac|\.m4a|\.aac|\.ogg|\.opus|\.aiff)$/.test(extension) || file.size > 200 * 1024 * 1024)
    throw new Error("Choose an audio file under 200 MB (MP3, WAV, FLAC, M4A, AAC, OGG, OPUS, or AIFF).");
  const response = await extensionFetch(base + "/upload-audio", { method: "POST",
    headers: { "Content-Type": "application/octet-stream", "X-PMV-Extension": extension }, body: file });
  const raw = await response.text();
  let result = {};
  if (raw) {
    try { result = JSON.parse(raw); }
    catch { throw new Error(`Cove returned an invalid upload response (${response.status}).`); }
  }
  if (!response.ok) throw new Error(result.message || `Song upload failed (${response.status}).`);
  if (!result.uploadId) throw new Error("The companion did not return an uploaded song ID.");
  return result.uploadId;
}

export function openPmv(_action, payload) {
  window.dispatchEvent(new CustomEvent("pmvmaker:open", { detail: payload }));
  return { cancelled: true };
}

const styleHelp = {
  "rhythmic-polish": "Precise cuts and restrained accents.",
  "high-energy": "Faster cuts, stronger motion, and controlled accents.",
  cinematic: "Longer shots and softer pacing."
};
const stylePresets = {
  "rhythmic-polish": { motionIntensityMin: 0.15, motionIntensityMax: 0.35, transitionIntensityMin: 0.15, transitionIntensityMax: 0.35, flashIntensityMin: 0, flashIntensityMax: 0, glitchIntensityMin: 0, glitchIntensityMax: 0 },
  "high-energy": { motionIntensityMin: 0.5, motionIntensityMax: 0.8, transitionIntensityMin: 0.2, transitionIntensityMax: 0.5, flashIntensityMin: 0.2, flashIntensityMax: 0.45, glitchIntensityMin: 0.15, glitchIntensityMax: 0.35 },
  cinematic: { motionIntensityMin: 0.1, motionIntensityMax: 0.3, transitionIntensityMin: 0.35, transitionIntensityMax: 0.65, flashIntensityMin: 0, flashIntensityMax: 0, glitchIntensityMin: 0, glitchIntensityMax: 0 }
};
const optionHelp = {
  layoutModes: "Select any combination. Each selected mode appears in the song, changing at phrase boundaries. With none selected, the edit uses Full screen.",
  useVerticalVideosOnly: "Only portrait source videos may appear in the three-pane edit. Landscape videos are excluded before planning.",
  selectionMode: "For triple portrait only, choose a random vertical crop, the center crop, or a crop around a detected face. Grid uses whole shots.",
  keepFaceCentered: "Moves a full-height portrait crop horizontally with the chosen face. It never zooms in on the face.",
  matchSelectedPerformers: "Uses linked Cove face detections when they cover the slice. Otherwise compares sampled frames with Cove face covers or performer portraits. Only performers linked to that video qualify.",
  faceSimilarityThreshold: "For image matching when linked face data is unavailable, sampled faces must reach this SFace cosine similarity. Linked Cove face detections use their stored identity instead. 55% is the minimum; this is not an identity probability.",
  mirrorRepeatedSource: "When the same video occupies both outside panes, use the same moment and mirror the right pane.",
  sampledClipsProgress: "Move sampling through successive 5% sections of each video.",
  minimumTimestampSeconds: "Never sample source footage before this timestamp.",
  endBufferSeconds: "Keep this many seconds clear at the end of each source video.",
  cycleLongerClipIntoSegments: "Reuse different parts of a longer scene when returning to a video.",
  rotatedClipLengthSeconds: "Maximum source window retained for later excerpts.",
  beatsPerBar: "Auto estimates the song's meter. Set 3, 4, or 6 if needed.",
  style: "Applies a starting set of motion, transition, flash, glitch, and color controls. You can change them below.",
  sourceAudio: "Muted uses only the backing song. Mixed adds brief source accents. All keeps source audio throughout. The song level stays constant.",
  pacing: "Sets the slowest and fastest cutting pace. The editor moves within this range as beat spacing changes.",
  beatAdherence: "Higher values move cuts closer to detected song beats and phrase points.",
  sourceDiversity: "Higher values cycle through more different source videos before repeating one.",
  transitionIntensity: "Minimum and maximum length of stepped dissolves when dissolves are enabled.",
  motionIntensity: "Minimum and maximum zoom strength for High Energy accents and Cinematic shots.",
  flashIntensity: "Minimum and maximum brightness of brief flash accents on highlighted cuts.",
  glitchIntensity: "Minimum and maximum strength of offset and difference accents on highlighted cuts.",
  minClipSeconds: "Shortest allowed time between cuts, in seconds.",
  maxClipSeconds: "Longest preferred clip length, in seconds.",
  clipLength: "Sets the shortest and longest allowed time between cuts, in seconds.",
  songTrimStart: "Optional starting point in the backing song, in seconds. Leave blank to start at the beginning.",
  songTrimEnd: "Optional ending point in the backing song, in seconds. Leave blank to use the full track.",
  outputFps: "Choose Auto for 60 fps only when every eligible source is 60 fps, otherwise 30 fps. Or select a fixed frame rate.",
  outputCodec: "Render an MP4 with H.264, H.265, or AV1. AV1 uses hardware encoding only. If Resolve rejects direct AV1, an NVIDIA encoder converts a temporary high-quality Resolve render. Create checks availability before queueing.",
  reencodeIncompatibleContainers: "Re-encode selected WMV/ASF ranges as H.264. If Resolve rejects an MP4 that actually contains Matroska data, remux selected ranges into MP4 without re-encoding its video. Saved projects keep these clips beside the .drp.",
  transitionFamilies: "Cuts switch immediately. Dissolves briefly blend the next clip over the previous one.",
  colorTreatment: "None leaves source colors alone. Match brightness samples the first two seconds of each used video. Warm and Cool apply subtle color shifts.",
  saveProject: "Exports a Resolve .drp project to the project folder, or beside the MP4 if that folder is blank.",
  scanToCove: "Imports the finished MP4 into Cove after Resolve renders it.",
  keepPerformers: "Adds performers linked to footage that actually appears in the finished PMV.",
  keepTags: "Adds tags from timed segments that actually appear in the finished PMV. General video tags are not inherited.",
  addPmvTag: "Adds the PMV tag to the imported video.",
  addAutoPmvTag: "Adds the Auto_PMV tag to the imported video."
};

function InfoButton({ label, help }) {
  const [open, setOpen] = useState(false);
  const wrapper = useRef(null);
  const id = React.useId();
  useEffect(() => {
    if (!open) return;
    const closeOutside = event => { if (!wrapper.current?.contains(event.target)) setOpen(false); };
    const closeEscape = event => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeEscape);
    return () => { document.removeEventListener("pointerdown", closeOutside); document.removeEventListener("keydown", closeEscape); };
  }, [open]);
  return <span className="pmv-info" ref={wrapper}>
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

function FolderSetting({ label, help, value, onBrowse, onClear, optional }) {
  return <Control label={label} help={help}>{id => <div className="pmv-folder-row">
    <input id={id} type="text" readOnly value={value || ""} placeholder="Choose a folder" />
    <button type="button" onClick={onBrowse}>Browse folders</button>
    {optional && value && <button type="button" onClick={onClear}>Clear</button>}
  </div>}</Control>;
}

function RangeControl({ label, help, lower, upper, onChange, minValue = 0, maxValue = 1, step = 0.05 }) {
  return <Control label={label} help={help}>{id => <div className="pmv-range-pair">
    <label>Min <input id={id} type="number" min={minValue} max={maxValue} step={step} value={lower}
      onChange={e => onChange(Math.min(Number(e.target.value), upper), upper)} /></label>
    <label>Max <input type="number" min={minValue} max={maxValue} step={step} value={upper}
      onChange={e => onChange(lower, Math.max(Number(e.target.value), lower))} /></label>
  </div>}</Control>;
}

async function coveFolders(path) {
  const query = path ? `?path=${encodeURIComponent(path)}` : "";
  const response = await extensionFetch(`/api/metadata/library-folders${query}`);
  if (!response.ok) throw new Error(`Cove could not list library folders (${response.status}).`);
  return response.json();
}

function filesystemFolders(path) {
  return api(`/folders${path ? `?path=${encodeURIComponent(path)}` : ""}`);
}

function FolderNode({ folder, depth, selected, onSelect, loadChildren, radioName }) {
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (expanded && children === null) loadChildren(folder.path).then(setChildren).catch(e => setError(e.message));
  }, [expanded, folder.path, loadChildren]);
  return <>
    <div className={`pmv-tree-row ${selected === folder.path ? "is-selected" : ""}`} style={{ paddingLeft: 8 + depth * 18 }}>
      {folder.hasChildren ? <button type="button" className={`pmv-tree-expand ${expanded ? "is-open" : ""}`} onClick={() => setExpanded(value => !value)}
        aria-label={`${expanded ? "Collapse" : "Expand"} ${folder.name}`}><span className="pmv-chevron" /></button>
        : <span className="pmv-tree-spacer" />}
      <label title={folder.path}><input type="radio" name={radioName} checked={selected === folder.path}
        onChange={() => onSelect(folder.path)} /><svg className="pmv-folder-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M2.5 5.5h5l1.7 1.8h8.3v8.2H2.5z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" /></svg><span>{folder.name}</span></label>
    </div>
    {expanded && (error ? <p role="alert" className="pmv-tree-hint">{error}</p> : children === null ? <small className="pmv-tree-hint">Loading folders…</small>
      : children.length ? children.map(child => <FolderNode key={child.path} folder={child} depth={depth + 1} selected={selected} onSelect={onSelect} loadChildren={loadChildren} radioName={radioName} />)
        : <small className="pmv-tree-empty">No subfolders</small>)}
  </>;
}

function FolderPicker({ kind, current, onChoose, onClose }) {
  const [roots, setRoots] = useState(null);
  const [selected, setSelected] = useState(current || "");
  const [error, setError] = useState("");
  const output = kind === "outputFolder";
  const title = output ? "Cove library folders" : kind === "musicFolder" ? "Choose music folder" : "Choose project folder";
  const loadChildren = output ? coveFolders : filesystemFolders;
  useEffect(() => { (output ? api("/scan-roots") : filesystemFolders()).then(setRoots).catch(e => setError(e.message)); }, [output]);
  return <div className="pmv-folder-browser" role="region" aria-label={title}>
    <div className="pmv-folder-browser-head"><div><strong>{title}</strong><small>{output ? "Choose a folder Cove can scan for finished videos." : "Expand a drive and choose a folder Cove can read."}</small></div><button type="button" className="pmv-browser-close" onClick={onClose} aria-label="Close folder browser">×</button></div>
    <div className="pmv-tree">{error ? <p role="alert">{error}</p> : roots === null ? <p className="pmv-tree-hint">Loading Cove folders…</p>
      : roots.length ? roots.map(root => <FolderNode key={root.path} folder={root} depth={0} selected={selected} onSelect={setSelected} loadChildren={loadChildren} radioName={`pmv-${kind}`} />)
        : <p className="pmv-tree-hint">{output ? "No video-scanning library paths are configured in Cove." : "No folders are available to Cove."}</p>}</div>
    <div className="pmv-folder-browser-foot"><div><small>Selected folder</small><span title={selected}>{selected || "Choose a folder"}</span></div><button type="button" className="pmv-button-primary" disabled={!selected} onClick={() => onChoose(selected)}>Use folder</button></div>
  </div>;
}

const effectSections = [
  ["automaticPacing", "Musical pacing", "Builds, peaks, and breathing room follow the song automatically."],
  ["beatPunch", "Beat punches", "Quick subject-centered zooms on selected strong beats."],
  ["cameraDrift", "Camera movement", "Gentle continuous pushes and sideways movement."],
  ["impactRecoil", "Impact recoil", "Short movement kicks that settle after a hit."],
  ["speedRamps", "Speed ramps", "Accelerate and slow selected action without changing the edit length."],
  ["motionEcho", "Motion echoes", "Brief, subtle trails on selected energetic shots."],
  ["highlightBloom", "Highlight bloom", "Soft highlight glow on musical peaks."],
  ["rgbSplit", "Color-edge accents", "Brief RGB separation on occasional hits."],
  ["freezeAccents", "Freeze accents", "Short holds followed by forward motion."],
  ["smartFraming", "Shot variety", "Alternate shot scale while keeping the subject in view."],
  ["actionSync", "Action on the beat", "Align detected movement peaks with musical accents."],
  ["motionMatching", "Match movement", "Prefer compatible movement across equally timed shots."],
  ["colorPolish", "Color polish", "Match exposure from the selected shot and apply gentle consistent contrast."]
];

const defaultOptions = {
  ...Object.fromEntries(effectSections.map(([key]) => [key, true])), previewSeconds: null,
  layout: "full-screen", layoutModes: [], useVerticalVideosOnly: false, selectionMode: "face", segmentMode: "exclude", segmentTagIds: [], keepFaceCentered: true,
  matchSelectedPerformers: true, faceSimilarityThreshold: 0.55, mirrorRepeatedSource: true,
  sampledClipsProgress: true, minimumTimestampSeconds: 0, endBufferSeconds: 0,
  cycleLongerClipIntoSegments: true, rotatedClipLengthSeconds: 30, beatsPerBar: "auto",
  style: "rhythmic-polish", sourceAudio: "mixed", pacingMin: 0.4, pacingMax: 0.7,
  beatAdherence: 0.95, minClipSeconds: 1, maxClipSeconds: 5, sourceDiversity: 0.8,
  transitionFamilies: ["cut", "dissolve"], transitionIntensityMin: 0.15, transitionIntensityMax: 0.35,
  motionIntensityMin: 0.15, motionIntensityMax: 0.35, flashIntensityMin: 0, flashIntensityMax: 0,
  glitchIntensityMin: 0, glitchIntensityMax: 0, colorTreatment: "natural", songTrimStart: null,
  songTrimEnd: null, outputFps: null, outputCodec: "av1", reencodeIncompatibleContainers: true,
  saveProject: false, scanToCove: true,
  keepPerformers: true, keepTags: true, addPmvTag: true, addAutoPmvTag: true
};

function selectedModes(options) {
  return options.layoutModes?.length ? options.layoutModes : ["full-screen"];
}

function needsFaceReferences(options) {
  const modes = selectedModes(options);
  const sliceMode = options.selectionMode === "face" && modes.includes("three-pane")
    && !options.useVerticalVideosOnly;
  return options.matchSelectedPerformers !== false && sliceMode;
}

function SegmentTagPicker({ ids, onChange, mode, allowEmptyInclude = false }) {
  const [query, setQuery] = useState("");
  const [tags, setTags] = useState([]);
  const [selected, setSelected] = useState([]);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(0);
  const rootRef = useRef(null);
  const inputRef = useRef(null);
  const listId = useRef("pmv-segment-suggestions-" + Math.random().toString(36).slice(2)).current;
  const chosen = ids || [];
  useEffect(() => {
    if (!ids?.length) { setSelected([]); return; }
    let live = true;
    api("/segment-tags?ids=" + ids.join(","))
      .then(rows => { if (live) setSelected(rows); })
      .catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [JSON.stringify(ids || [])]);
  useEffect(() => {
    if (!open) return;
    let live = true;
    setLoading(true);
    const timer = window.setTimeout(() => api("/segment-tags?q=" + encodeURIComponent(query.trim()))
      .then(rows => { if (live) { setTags(rows); setActive(0); setError(""); } })
      .catch(e => { if (live) { setTags([]); setError(e.message); } })
      .finally(() => { if (live) setLoading(false); }), query.trim() ? 180 : 0);
    return () => { live = false; window.clearTimeout(timer); };
  }, [query, open]);
  useEffect(() => {
    if (!open) return;
    const closeOutside = event => { if (!rootRef.current?.contains(event.target)) setOpen(false); };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [open]);
  const suggestions = tags.filter(tag => !chosen.includes(tag.id));
  const choose = tag => {
    if (chosen.includes(tag.id)) return;
    setSelected(current => [...current.filter(item => item.id !== tag.id), tag]);
    onChange([...chosen, tag.id]);
    setQuery("");
    setActive(0);
    inputRef.current?.focus();
  };
  const handleKey = event => {
    if (event.key === "Escape") { setOpen(false); return; }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      setActive(index => Math.max(0, Math.min(suggestions.length - 1, index + (event.key === "ArrowDown" ? 1 : -1))));
    }
    if (event.key === "Enter" && open) {
      event.preventDefault();
      if (suggestions.length) choose(suggestions[Math.min(active, suggestions.length - 1)]);
    }
  };
  return <fieldset className="pmv-segment-picker"><legend>{mode === "include" ? "Included segment tags" : "Excluded segment tags"}</legend>
    <p>{mode === "include" ? allowEmptyInclude ? "Save Include as a default now; choose a tag before creating a PMV." : "Use Cove's full segments with any selected tag. Choose at least one." : "Use every full segment except time covered by a selected tag. Leave empty to use all full segments."}</p>
    <div ref={rootRef} className="pmv-segment-combobox">
      <div className="pmv-segment-input-wrap">
        {chosen.map(id => {
          const tag = selected.find(row => row.id === id) || tags.find(row => row.id === id) || { id, name: `Tag #${id}` };
          return <span key={id} className="pmv-segment-pill" title={tag.hasTimedSegments === false ? "This tag has no timed video segments" : undefined}>
            <span>{tag.name}{tag.hasTimedSegments === false ? " (no segments)" : ""}</span>
            <button type="button" aria-label={`Remove ${tag.name}`} title={`Remove ${tag.name}`} onClick={() => onChange(chosen.filter(value => value !== id))}>×</button>
          </span>;
        })}
        <input ref={inputRef} role="combobox" aria-label="Search segment tags" aria-autocomplete="list"
          aria-controls={listId} aria-expanded={open}
          aria-activedescendant={open && suggestions.length ? `${listId}-${suggestions[Math.min(active, suggestions.length - 1)].id}` : undefined}
          autoComplete="off" value={query}
          onFocus={() => setOpen(true)} onChange={event => { setQuery(event.target.value); setOpen(true); }}
          onKeyDown={handleKey} placeholder={chosen.length ? "Add another segment tag…" : "Search segment tags…"} />
      </div>
      {open && <div id={listId} role="listbox" aria-label="Segment tags with timed video segments" className="pmv-segment-suggestions">
        {loading ? <div className="pmv-segment-status">Searching segment tags…</div> : error ? <div className="pmv-segment-status" role="alert">{error}</div>
          : suggestions.length ? suggestions.map((tag, index) => <button id={`${listId}-${tag.id}`} type="button" role="option" aria-selected={index === active}
            key={tag.id} className={index === active ? "is-active" : ""} onMouseEnter={() => setActive(index)}
            onMouseDown={event => event.preventDefault()}
            onClick={() => choose(tag)}>{tag.name}</button>)
          : <div className="pmv-segment-status">{query.trim() ? "No matching segment tags" : "No more segment tags available"}</div>}
      </div>}
    </div>
  </fieldset>;
}

function SegmentSection({ options, setOptions, allowEmptyInclude = false }) {
  const mode = options.segmentMode || "exclude";
  const ids = options.segmentTagIds || [];
  return <section className="pmv-segment-section"><div className="pmv-form-heading"><h5>Segments to use</h5></div>
    <div className="pmv-segment-modes" role="group" aria-label="Segment mode">
      {[["include", "Include"], ["exclude", "Exclude"]].map(([value, label]) =>
        <button key={value} type="button" className={mode === value ? "is-active" : ""}
          aria-pressed={mode === value} onClick={() => setOptions(current => ({ ...current, segmentMode: value }))}>{label}</button>)}
    </div>
    <SegmentTagPicker ids={ids} mode={mode} allowEmptyInclude={allowEmptyInclude} onChange={segmentTagIds => setOptions(current => ({ ...current, segmentTagIds }))} />
    {!allowEmptyInclude && mode === "include" && ids.length === 0 && <p className="pmv-segment-required" role="status">Choose at least one segment tag to create a PMV.</p>}
  </section>;
}

function OptionForm({ options, setOptions, portraitFaceControls = null }) {
  const set = (key, value) => setOptions(current => ({ ...current, [key]: value }));
  const modes = selectedModes(options);
  const portrait = modes.includes("three-pane");
  const faceSlices = portrait && !options.useVerticalVideosOnly;
  const toggleMode = (mode, enabled) => setOptions(current => ({ ...current,
    layoutModes: enabled ? [...new Set([...(current.layoutModes || []), mode])] : (current.layoutModes || []).filter(item => item !== mode) }));
  return <>
    <div className="pmv-form-heading"><h5>Layout settings</h5><span>01</span></div>
    <fieldset className="pmv-layout-choices"><legend>Modes <InfoButton label="Modes" help={optionHelp.layoutModes} /></legend>
      <div className="pmv-checkbox-grid">
        {[["grid", "Grid (four videos)"], ["three-pane", "Triple portrait"], ["full-screen", "Full screen"]].map(([mode, label]) =>
          <Control key={mode} label={label} help={optionHelp.layoutModes} className="pmv-toggle">{id =>
            <input id={id} type="checkbox" checked={(options.layoutModes || []).includes(mode)} onChange={e => toggleMode(mode, e.target.checked)} />}</Control>)}
      </div>
      {!(options.layoutModes || []).length && <small>No modes checked: Full screen will be used.</small>}
    </fieldset>
    {portrait && <fieldset className="pmv-layout-choices pmv-portrait-settings"><legend>Triple portrait settings</legend><div className="pmv-grid">
      <Control label="Use vertical videos only" help={optionHelp.useVerticalVideosOnly} className="pmv-toggle">{id => <input id={id} type="checkbox" checked={!!options.useVerticalVideosOnly} onChange={e => set("useVerticalVideosOnly", e.target.checked)} />}</Control>
      {faceSlices && <Control label="Portrait slice selection mode" help={optionHelp.selectionMode}>{id => <select id={id} value={options.selectionMode || "center"} onChange={e => set("selectionMode", e.target.value)}><option value="random">Random slice</option><option value="center">Center slice</option><option value="face">Face slice</option></select>}</Control>}
      {faceSlices && options.selectionMode === "face" && <Control label="Keep face centered" help={optionHelp.keepFaceCentered} className="pmv-toggle">{id => <input id={id} type="checkbox" checked={options.keepFaceCentered !== false} onChange={e => set("keepFaceCentered", e.target.checked)} />}</Control>}
      {faceSlices && options.selectionMode === "face" && <Control label="Match performers in each video" help={optionHelp.matchSelectedPerformers} className="pmv-toggle">{id => <input id={id} type="checkbox" checked={options.matchSelectedPerformers !== false} onChange={e => set("matchSelectedPerformers", e.target.checked)} />}</Control>}
      <Control label="Mirror repeated source" help={optionHelp.mirrorRepeatedSource} className="pmv-toggle">{id => <input id={id} type="checkbox" checked={options.mirrorRepeatedSource !== false} onChange={e => set("mirrorRepeatedSource", e.target.checked)} />}</Control>
    </div>{needsFaceReferences(options) && portraitFaceControls}</fieldset>}
    <div className="pmv-form-heading"><h5>Creative direction</h5><span>02</span></div>
    <div className="pmv-grid">
      <Control label="Style" help={optionHelp.style}>{id => <><select id={id} value={options.style} onChange={e => setOptions(current => ({ ...current, style: e.target.value, ...stylePresets[e.target.value] }))}>{Object.keys(styleHelp).map(x => <option key={x} value={x}>{x.replaceAll("-", " ")}</option>)}</select><small>{styleHelp[options.style]}</small></>}</Control>


    </div>
    <Control label="Length" help="Use a short comparison preview before rendering the full song.">{id => <select id={id} value={options.previewSeconds || ""} onChange={e => set("previewSeconds", e.target.value ? 25 : null)}><option value="">Full song</option><option value="25">25-second comparison preview</option></select>}</Control>
    <details className="pmv-advanced"><summary>Automatic effects · {effectSections.filter(([key]) => options[key] !== false).length} enabled</summary>
      <p>Timing, strength, and combinations are automatic. Uncheck any section to leave it out.</p>
      <div className="pmv-checkbox-grid">{effectSections.map(([key, label, help]) => <Control key={key} label={label} help={help} className="pmv-toggle">{id => <input id={id} type="checkbox" checked={options[key] !== false} onChange={e => set(key, e.target.checked)} />}</Control>)}</div>
    </details>
    <details className="pmv-advanced"><summary>Advanced edit controls</summary><div className="pmv-grid">
      <Control label="Source audio" help={optionHelp.sourceAudio}>{id => <select id={id} value={options.sourceAudio} onChange={e => set("sourceAudio", e.target.value)}><option value="muted">Muted</option><option value="mixed">Mixed · brief accents</option><option value="all">All source audio</option></select>}</Control>
      <Control label="Render codec" help={optionHelp.outputCodec}>{id => <select id={id} value={options.outputCodec || "av1"} onChange={e => set("outputCodec", e.target.value)}><option value="h264">H.264 MP4</option><option value="h265">H.265 MP4</option><option value="av1">AV1 MP4</option></select>}</Control>
      {[["transitionIntensity", "Transition intensity"]].map(([key, label]) => <RangeControl key={key} label={label} help={optionHelp[key]} lower={options[`${key}Min`] ?? 0} upper={options[`${key}Max`] ?? 0} onChange={(lower, upper) => setOptions(current => ({ ...current, [`${key}Min`]: lower, [`${key}Max`]: upper }))} />)}
      <RangeControl label="Clip length (sec)" help={optionHelp.clipLength} lower={options.minClipSeconds} upper={options.maxClipSeconds} minValue={0.25} maxValue={30} step={0.25} onChange={(lower, upper) => setOptions(current => ({ ...current, minClipSeconds: lower, maxClipSeconds: upper }))} />
      <Control label="Sampled clips progress through video" help={optionHelp.sampledClipsProgress} className="pmv-toggle">{id => <input id={id} type="checkbox" checked={options.sampledClipsProgress !== false} onChange={e => set("sampledClipsProgress", e.target.checked)} />}</Control>
      <Control label="Re-encode incompatible containers" help={optionHelp.reencodeIncompatibleContainers} className="pmv-toggle">{id => <input id={id} type="checkbox" checked={options.reencodeIncompatibleContainers !== false} onChange={e => set("reencodeIncompatibleContainers", e.target.checked)} />}</Control>
      <Control label="Cycle longer clip into segments" help={optionHelp.cycleLongerClipIntoSegments} className="pmv-toggle">{id => <input id={id} type="checkbox" checked={options.cycleLongerClipIntoSegments !== false} onChange={e => set("cycleLongerClipIntoSegments", e.target.checked)} />}</Control>
      {[["minimumTimestampSeconds", "Clip minimum timestamp"], ["endBufferSeconds", "Keep clear before source end"], ["rotatedClipLengthSeconds", "Rotated scene length"]].map(([key, label]) => <Control key={key} label={`${label} (sec)`} help={optionHelp[key]}>{id => <input id={id} type="number" min="0" max={key === "rotatedClipLengthSeconds" ? 300 : undefined} step="0.5" value={options[key] ?? 0} onChange={e => set(key, Number(e.target.value))} />}</Control>)}
      <Control label="Beats per bar" help={optionHelp.beatsPerBar}>{id => <select id={id} value={options.beatsPerBar || "auto"} onChange={e => set("beatsPerBar", e.target.value)}><option value="auto">Auto</option><option value="3">3</option><option value="4">4</option><option value="6">6</option></select>}</Control>
      {faceSlices && options.selectionMode === "face" && options.matchSelectedPerformers !== false && <Control label="Performer face match minimum similarity" help={optionHelp.faceSimilarityThreshold}>{id => <div className="pmv-range"><input id={id} type="range" min="0.55" max="0.8" step="0.01" value={Math.max(0.55, options.faceSimilarityThreshold ?? 0.55)} onChange={e => set("faceSimilarityThreshold", Number(e.target.value))} /><output>{Math.round(100 * Math.max(0.55, options.faceSimilarityThreshold ?? 0.55))}%</output></div>}</Control>}
      {["beatAdherence", "sourceDiversity"].map(key => <Control key={key} label={key === "beatAdherence" ? "Beat adherence" : "Source diversity"} help={optionHelp[key]}>{id => <div className="pmv-range"><input id={id} type="range" min="0" max="1" step="0.05" value={options[key]} onChange={e => set(key, Number(e.target.value))} /><output>{Number(options[key]).toFixed(2)}</output></div>}</Control>)}
      {["songTrimStart", "songTrimEnd"].map((key, i) => <Control key={key} label={["Song start (sec)", "Song end (sec)"][i]} help={optionHelp[key]}>{id => <input id={id} type="number" min="0" step="any" value={options[key] ?? ""} onChange={e => set(key, e.target.value === "" ? null : Number(e.target.value))} />}</Control>)}
      <Control label="FPS override" help={optionHelp.outputFps}>{id => <select id={id} value={options.outputFps ?? ""} onChange={e => set("outputFps", e.target.value ? Number(e.target.value) : null)}><option value="">Auto</option><option value="24">24 fps</option><option value="25">25 fps</option><option value="30">30 fps</option><option value="50">50 fps</option><option value="60">60 fps</option></select>}</Control>
      <Control label="Transitions" help={optionHelp.transitionFamilies}>{id => <select id={id} value={options.transitionFamilies?.join(",") || "cut"} onChange={e => set("transitionFamilies", e.target.value.split(","))}><option value="cut">Cuts</option><option value="cut,dissolve">Cuts and dissolves</option></select>}</Control>
      <Control label="Color matching" help={optionHelp.colorTreatment}>{id => <select id={id} value={options.colorTreatment} onChange={e => set("colorTreatment", e.target.value)}><option value="natural">None</option><option value="matched">Match brightness</option><option value="warm">Warm</option><option value="cool">Cool</option></select>}</Control>
    </div><div className="pmv-form-heading"><h5>Output and Cove metadata</h5><span>03</span></div><div className="pmv-checkbox-grid">
      {[["saveProject", "Save project (.drp)"], ["scanToCove", "Scan to Cove"], ["keepPerformers", "Keep performers"], ["keepTags", "Keep used segment tags"], ["addPmvTag", "Add PMV tag"], ["addAutoPmvTag", "Add Auto_PMV tag"]].map(([key, label]) => <Control key={key} label={label} help={optionHelp[key]} className="pmv-toggle">{id => <input id={id} type="checkbox" checked={!!options[key]} onChange={e => set(key, e.target.checked)} />}</Control>)}
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
  const [browsing, setBrowsing] = useState(null);
  useEffect(() => { if (settings) setMappingText(JSON.stringify(settings.pathMappings || [], null, 2)); }, [!!settings]);
  useEffect(() => { if (settings?.companionMode === "auto") api("/local-companion").then(setLocal).catch(e => setError(e.message)); }, [settings?.companionMode]);
  useEffect(() => {
    if (!settings) return;
    const refresh = () => api("/validation").then(setValidation).catch(e => setError(e.message));
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => window.clearInterval(timer);
  }, [!!settings]);
  useEffect(() => { if (settings) api("/health").then(setHealth).catch(e => setHealth({ ok: false, error: e.message })); }, [!!settings, settings?.companionMode]);
  if (!settings) return <div className="pmv-settings">{error || "Loading PMV settings…"}</div>;
  const set = (key, value) => setSettings(current => ({ ...current, [key]: value }));
  const defaults = { ...defaultOptions, ...settings.defaults };
  const automatic = settings.companionMode === "auto";
  const ready = !!settings.skipSetupChecks || !!health?.ok && validation?.state === "complete";
  const chooseFolder = path => { set(browsing, path); setBrowsing(null); };
  return <div className="pmv-settings">
    {!ready && <div className="pmv-setup-banner"><strong>Setup required</strong><p>Connect Resolve and check compatibility, or skip setup and configure your first PMV.</p></div>}
    <details className="pmv-panel pmv-checks" open={!ready}><summary>Resolve setup checks</summary>
    {!ready && <p>These checks are optional at setup. Jobs still verify Resolve and media paths before rendering.</p>}
    <div className="pmv-actions">
      <HelpAction label="Check Resolve" help="Checks the Resolve connection and required media tools."><button type="button" onClick={async () => { try { setHealth(await api("/health")); setError(""); } catch (e) { setError(e.message); } }}>Check Resolve</button></HelpAction>
      <HelpAction label="Run Resolve compatibility check" help="Renders short fixtures to check the installed Resolve version."><button type="button" disabled={validation?.state === "queued" || validation?.state === "running"} onClick={async () => { try { setValidation(await api("/validation", "POST")); setError(""); } catch (e) { setError(e.message); } }}>Run Resolve compatibility check</button></HelpAction>
      {!ready && <button type="button" className="pmv-button-quiet" onClick={async () => { try { setSettings(await api("/settings", "PUT", { ...settings, skipSetupChecks: true })); setMessage("Setup checks skipped. PMV jobs will still check Resolve and media paths before rendering."); setError(""); } catch (e) { setError(e.message); } }}>Skip setup checks</button>}
    </div>
    {settings.skipSetupChecks && <p className="pmv-setup-note">Setup checks skipped. PMV jobs still check Resolve and media paths before rendering.</p>}
    {health && <p role="status">Resolve: {health.ok ? `${health.product} ${health.version} connected` : health.error}</p>}
    {validation && validation.state !== "idle" && <p role="status">Compatibility check: {validation.message}{validation.error ? ` — ${validation.error}` : ""}</p>}
    </details>
    {!ready && !automatic && <details><summary>External companion connection (Docker)</summary>
      <p>Download and start the bundled Windows companion, then save its URL and token before checking Resolve.</p>
      <button type="button" onClick={async () => { try { await downloadCompanion(); setMessage("Companion ZIP downloaded."); } catch (e) { setError(e.message); } }}>Download Windows companion</button>
      <div className="pmv-grid">
      <Control label="Companion URL" help="The address shown by the Windows companion.">{id => <input id={id} value={settings.companionUrl || ""} onChange={e => set("companionUrl", e.target.value)} />}</Control>
      <Control label="Companion token" help="The private token shown by the Windows companion.">{id => <input id={id} type="password" value={settings.companionToken || ""} onChange={e => set("companionToken", e.target.value)} />}</Control>
      <button type="button" onClick={async () => { try { setSettings(await api("/settings", "PUT", settings)); setHealth(await api("/health")); setError(""); } catch (e) { setError(e.message); } }}>Save connection</button>
    </div></details>}
    {ready && <>
    <section className="pmv-panel"><div className="pmv-section-heading"><h4>Connection</h4><p>How Cove reaches the Windows Resolve companion.</p></div>
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
    </section>
    <section className="pmv-panel"><div className="pmv-section-heading"><h4>Folders</h4><p>Output stays inside a Cove video library. Music and project files can live elsewhere.</p></div>
    <div className="pmv-grid">
      <FolderSetting label="Output folder" help="Where finished MP4 files are saved. Choose a Cove video library folder so Cove can scan the result." value={settings.outputFolder} onBrowse={() => setBrowsing("outputFolder")} />
      <FolderSetting label="Configured music folder (optional)" help="Choose the folder containing your backing songs. Its subfolders appear in Create PMV. You can also upload a song in that popup without configuring this folder." value={settings.musicFolder} onBrowse={() => setBrowsing("musicFolder")} onClear={() => set("musicFolder", "")} optional />
    </div>
    {browsing && browsing !== "projectFolder" && <FolderPicker kind={browsing} current={settings[browsing]} onChoose={chooseFolder} onClose={() => setBrowsing(null)} />}
    <details><summary>Advanced settings</summary><div className="pmv-grid"><FolderSetting label="Project folder (optional)" help="Where exported Resolve .drp files go when Save project is enabled. Leave blank to save beside the MP4." value={settings.projectFolder} onBrowse={() => setBrowsing("projectFolder")} onClear={() => set("projectFolder", "")} optional /></div>
      {browsing === "projectFolder" && <FolderPicker kind={browsing} current={settings.projectFolder} onChoose={chooseFolder} onClose={() => setBrowsing(null)} />}</details>
    </section>
    <section className="pmv-panel"><div className="pmv-section-heading"><h4>Job defaults</h4><p>These choices appear in each Create PMV popup and can be changed per job.</p></div>
      <div className="pmv-grid"><Control label="Default backing audio source" help="Choose the audio source shown when Create PMV opens.">{id => <select id={id} value={settings.defaultAudioKind || "cove"} onChange={e => set("defaultAudioKind", e.target.value)}><option value="cove">Cove audio</option><option value="folder">Configured music folder</option><option value="upload">Choose song file</option><option value="youtube">YouTube URL</option><option value="video">Cove video audio</option></select>}</Control></div>
      <SegmentSection options={defaults} allowEmptyInclude setOptions={value => set("defaults", typeof value === "function" ? value(defaults) : value)} />
      <OptionForm options={defaults} setOptions={value => set("defaults", typeof value === "function" ? value(defaults) : value)}
        portraitFaceControls={<Control label="Default face performer gender" help="Prefilters performers from each source video by Cove gender metadata when Triple portrait face matching is selected.">{id => <select id={id} value={settings.defaultFaceGender || "female"} onChange={e => set("defaultFaceGender", e.target.value)}><option value="female">Female</option><option value="male">Male</option><option value="trans">Trans performers</option><option value="all">All performers</option></select>}</Control>} /></section>
    <div className="pmv-settings-footer"><button className="pmv-button-primary" disabled={!automatic && !mappingValid} onClick={async () => { try { setSettings(await api("/settings", "PUT", settings)); if (automatic) setLocal(await api("/local-companion")); setMessage("Settings saved."); setError(""); } catch (e) { setError(e.message); } }}>Save settings</button></div>
    </>}
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
  </div>;
}

function formatTrackDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "–:–";
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor(total / 60) % 60;
  const rest = String(total % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
}

function TrackRow({ name, selected, playing, onSelect, onPreview, depth = 0, duration, previewUrl }) {
  const row = useRef(null);
  const [measured, setMeasured] = useState(null);
  useEffect(() => {
    setMeasured(null);
    if (Number.isFinite(duration) || !previewUrl) return;
    let audio, observer;
    const load = () => {
      audio = new Audio();
      audio.preload = "metadata";
      audio.onloadedmetadata = () => setMeasured(audio.duration);
      audio.src = previewUrl;
      audio.load();
    };
    if (window.IntersectionObserver && row.current) {
      observer = new IntersectionObserver(entries => {
        if (entries.some(entry => entry.isIntersecting)) { observer.disconnect(); load(); }
      }, { root: row.current.closest(".pmv-track-list") });
      observer.observe(row.current);
    } else load();
    return () => { observer?.disconnect(); if (audio) { audio.onloadedmetadata = null; audio.src = ""; } };
  }, [duration, previewUrl]);
  return <div ref={row} className={`pmv-track-row ${selected ? "is-selected" : ""}`} style={{ paddingLeft: 8 + depth * 18 }}>
    <button type="button" className="pmv-track-select" onClick={onSelect} title={name} aria-pressed={selected}>♫ <span>{name}</span></button>
    <span className="pmv-track-duration" aria-label={`Duration ${formatTrackDuration(Number.isFinite(duration) ? duration : measured)}`}>{formatTrackDuration(Number.isFinite(duration) ? duration : measured)}</span>
    <button type="button" className="pmv-track-play" onClick={onPreview} title={`${playing ? "Pause" : "Play"} ${name}`} aria-label={`${playing ? "Pause" : "Play"} ${name}`}>{playing ? "Ⅱ" : "▶"}</button>
  </div>;
}

function MusicNode({ item, depth, selectedPath, playingUrl, onSelect, onPreview }) {
  const [open, setOpen] = useState(false);
  const [children, setChildren] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open || children !== null) return;
    let active = true;
    api(`/music?path=${encodeURIComponent(item.path)}`).then(rows => { if (active) setChildren(rows); })
      .catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [open, item.path, children]);
  if (item.kind === "file") {
    const url = `/api/ext/pmv/music-preview?path=${encodeURIComponent(item.path)}`;
    return <TrackRow name={item.name} depth={depth} selected={selectedPath === item.path} playing={playingUrl === url} previewUrl={url}
      onSelect={() => onSelect(item.path)} onPreview={() => onPreview(url)} />;
  }
  return <>
    <div className="pmv-music-folder" style={{ paddingLeft: 8 + depth * 18 }}>
      <button type="button" onClick={() => setOpen(value => !value)} aria-expanded={open} title={item.path}>
        <span className={`pmv-chevron ${open ? "is-open" : ""}`} /> <span>▸</span> {item.name}
      </button>
    </div>
    {open && (error ? <p role="alert" className="pmv-tree-hint">{error}</p> : children === null ? <small className="pmv-tree-hint">Loading tracks…</small>
      : children.length ? children.map(child => <MusicNode key={child.path} item={child} depth={depth + 1}
        selectedPath={selectedPath} playingUrl={playingUrl} onSelect={onSelect} onPreview={onPreview} />)
        : <small className="pmv-tree-empty">Empty folder</small>)}
  </>;
}

function MusicTree({ selectedPath, playingUrl, onSelect, onPreview }) {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => { let active = true; api("/music").then(rows => { if (active) setItems(rows); })
    .catch(e => { if (active) setError(e.message); }); return () => { active = false; }; }, []);
  return <div className="pmv-track-browser">
    <div className="pmv-track-browser-head"><strong>Configured music folder</strong><small>Choose a song; use Play to listen first.</small></div>
    <div className="pmv-track-list" role="region" aria-label="Music folder tracks">
      {error ? <p role="alert" className="pmv-tree-hint">{error}</p> : items === null ? <p className="pmv-tree-hint">Loading music folder…</p>
        : items.length ? items.map(item => <MusicNode key={item.path} item={item} depth={0}
          selectedPath={selectedPath} playingUrl={playingUrl} onSelect={onSelect} onPreview={onPreview} />)
          : <p className="pmv-tree-hint">No songs in this folder.</p>}
    </div>
  </div>;
}

function PmvDialog({ context, close }) {
  const [settings, , settingsError] = useSettings("/defaults");
  const [options, setOptions] = useState(defaultOptions);
  const [audio, setAudio] = useState({ kind: "cove" });
  const [faceIds, setFaceIds] = useState([]);
  const [faceGender, setFaceGender] = useState("female");
  const initializedFaces = useRef(false);
  const [query, setQuery] = useState("");
  const [audioItems, setAudioItems] = useState([]);
  const [selectedAudioName, setSelectedAudioName] = useState("");
  const [audioLoading, setAudioLoading] = useState(false);
  const [audioError, setAudioError] = useState("");
  const [videoItems, setVideoItems] = useState([]);
  const [videoQuery, setVideoQuery] = useState("");
  const [previewUrl, setPreviewUrl] = useState("");
  const [playingUrl, setPlayingUrl] = useState("");
  const audioPlayer = useRef(null);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [cart, setCart] = useState([]);
  const [variantName, setVariantName] = useState("");
  const [queued, setQueued] = useState(null);
  const submission = useRef(null);
  const cartRef = useRef([]);
  cartRef.current = cart;
  const [editing, setEditing] = useState(null);
  const uploadGeneration = useRef(0);
  useEffect(() => { if (settings) { const kind = settings.defaultAudioKind || "cove";
    setOptions({ ...defaultOptions, ...settings.defaults });
    setAudio(kind === "video" && context.entityType === "video" && (context.entityIds || context.selectedIds || []).length === 1
      ? { kind, coveVideoId: (context.entityIds || context.selectedIds)[0] } : { kind });
    setFaceGender(settings.defaultFaceGender || "female"); } }, [settings]);
  const genderFits = (person, gender) => gender === "all" || (gender === "female" && (person.gender === 1 || person.gender === "female"))
    || (gender === "male" && (person.gender === 0 || person.gender === "male"))
    || (gender === "trans" && ([2, 3, "transgenderMale", "transgenderFemale"].includes(person.gender)));
  useEffect(() => {
    if (!preview?.performers || !settings) return;
    const available = new Set(preview.performers.filter(person => person.hasReference).map(person => person.id));
    if (initializedFaces.current) { setFaceIds(current => current.filter(id => available.has(id))); return; }
    initializedFaces.current = true;
    const initial = preview.performers.filter(person => person.hasReference && genderFits(person, settings.defaultFaceGender || "female")).map(person => person.id);
    const scoped = context.entityType === "performer" ? (context.entityIds || context.selectedIds || []).filter(id => preview.performers.some(p => p.id === id && p.hasReference)) : [];
    setFaceIds([...new Set([...scoped, ...initial])]);
  }, [preview?.performers, settings]);
  useEffect(() => {
    if (audio.kind !== "cove") return;
    let active = true;
    setAudioLoading(true); setAudioError("");
    const timer = window.setTimeout(() => api("/audio?q=" + encodeURIComponent(query))
      .then(rows => { if (active) setAudioItems(rows); })
      .catch(e => { if (active) { setAudioItems([]); setAudioError(e.message.includes("403") ? "Cove denied audio access. Your account needs Audios read permission." : e.message); } })
      .finally(() => { if (active) setAudioLoading(false); }), 250);
    return () => { active = false; window.clearTimeout(timer); };
  }, [audio.kind, query]);
  useEffect(() => { if (audio.kind === "video") api("/videos?q=" + encodeURIComponent(videoQuery)).then(setVideoItems).catch(e => setError(e.message)); }, [audio.kind, videoQuery]);
  const scope = { entityType: context.entityType, entityIds: context.entityIds || context.selectedIds,
    includeChildStudios: !!context.includeChildStudios, videoFilter: context.videoFilter || null,
    videoFilterExpression: context.videoFilterExpression || null, findQuery: context.findQuery || null };
  const request = { scope, audio, options, facePerformerIds: faceIds };
  const segmentsReady = options.segmentMode !== "include" || !!options.segmentTagIds?.length;
  const audioReady = audio.kind === "cove" ? Number(audio.coveAudioId) > 0 : audio.kind === "folder" ? !!audio.path
    : audio.kind === "upload" ? !!audio.uploadId : audio.kind === "video" ? Number(audio.coveVideoId) > 0
      : audio.kind === "youtube" && /^https:\/\//i.test(audio.url || "");
  const removeUpload = uploadId => { if (uploadId && !submission.current && !cartRef.current.some(line => line.audio.uploadId === uploadId)) api(`/uploads/${uploadId}`, "DELETE").catch(() => {}); };
  const playPreview = url => {
    const player = audioPlayer.current;
    if (!player) return;
    if (playingUrl === url && !player.paused) { player.pause(); setPlayingUrl(""); return; }
    if (previewUrl !== url) { player.src = url; setPreviewUrl(url); }
    setError("");
    player.play().then(() => setPlayingUrl(url)).catch(() => setError("Could not play this track in the browser."));
  };
  const changeAudioKind = kind => {
    uploadGeneration.current += 1;
    removeUpload(audio.uploadId);
    setSelectedAudioName("");
    audioPlayer.current?.pause(); setPreviewUrl(""); setPlayingUrl("");
    setUploading(false);
    setAudio(kind === "video" && context.entityType === "video" && scope.entityIds.length === 1
      ? { kind, coveVideoId: scope.entityIds[0] } : { kind });
  };
  const chooseSong = async file => {
    if (!file) return;
    const generation = ++uploadGeneration.current;
    removeUpload(audio.uploadId);
    setAudio({ kind: "upload" });
    setUploading(true); setError("");
    try {
      const uploadId = await uploadSongFile(file);
      if (generation !== uploadGeneration.current) { removeUpload(uploadId); return; }
      setAudio({ kind: "upload", uploadId, name: file.name });
    } catch (e) { if (generation === uploadGeneration.current) setError(e.message); }
    finally { if (generation === uploadGeneration.current) setUploading(false); }
  };
  const cancel = () => {
    if (busy) return;
    uploadGeneration.current += 1;
    const ids = new Set([audio.uploadId, ...cart.map(line => line.audio.uploadId)].filter(Boolean));
    cartRef.current = [];
    ids.forEach(removeUpload); audioPlayer.current?.pause(); close();
  };
  useEffect(() => {
    if (!segmentsReady) { setPreview(null); return; }
    let active = true;
    const timer = window.setTimeout(() => api("/preview", "POST", request)
      .then(result => { if (active) setPreview(result); })
      .catch(e => { if (active) setError(e.message); }), 150);
    return () => { active = false; window.clearTimeout(timer); };
  }, [JSON.stringify(scope), JSON.stringify(options), segmentsReady]);
  const validDraft = () => {
    if (!audioReady) { setError("Choose a backing track first."); return false; }
    if (!segmentsReady) { setError("Choose at least one segment tag in Include mode."); return false; }
    if (needsFaceReferences(options) && !faceIds.length) { setError("Choose a performer with a reference image, or turn off performer matching."); return false; }
    return true;
  };
  const snapshot = () => JSON.parse(JSON.stringify({ name: variantName.trim() || options.style,
    audio, options, facePerformerIds: faceIds, songName: selectedAudioName || audio.name || audio.path || audio.url || `Track ${audio.coveAudioId || audio.coveVideoId || ""}` }));
  const addOrder = () => {
    if (!validDraft()) return;
    setError(""); submission.current = null;
    const line = snapshot();
    setCart(current => editing === null ? [...current, line] : current.map((row, index) => index === editing ? line : row));
    setEditing(null); setVariantName("");
  };
  const removeOrder = index => {
    const removed = cart[index];
    const next = cart.filter((_, i) => i !== index);
    cartRef.current = next; setCart(next); setEditing(null); submission.current = null;
    if (removed.audio.uploadId !== audio.uploadId) removeUpload(removed.audio.uploadId);
  };
  const editOrder = index => {
    const row = JSON.parse(JSON.stringify(cart[index]));
    setOptions(row.options); setAudio(row.audio); setFaceIds(row.facePerformerIds || []);
    setVariantName(row.name); setSelectedAudioName(row.songName); setEditing(index);
  };
  const create = async () => {
    if (!cart.length && !validDraft()) return;
    setBusy(true); setError("");
    submission.current ||= crypto.randomUUID().replaceAll("-", "");
    try {
      const result = await api("/create", "POST", { scope, submissionId: submission.current, orders: cart.length ? cart : [snapshot()] });
      setQueued(result); cartRef.current = []; setCart([]);
      // Submitted uploads now belong to the queued order and must survive closing.
      const submittedIds = new Set((cart.length ? cart : [snapshot()]).map(line => line.audio.uploadId));
      if (!submittedIds.has(audio.uploadId)) removeUpload(audio.uploadId);
      setAudio({ kind: "cove" }); audioPlayer.current?.pause();
    } catch (e) {
      if (e.status >= 400 && e.status < 500) { submission.current = null; setError(e.message); }
      else setError(e.message + " Retry to recover this order. Its settings are held unchanged to prevent duplicates.");
    }
    finally { setBusy(false); }
  };
  const portraitFaceControls = <fieldset className="pmv-face-picker"><legend>Faces to follow</legend>
    <p>Uses linked Cove face data first. If it does not cover the slice, matching uses a Cove face cover or performer portrait. Only performers linked to that video qualify.</p>
    <div className="pmv-grid"><Control label="Select by gender" help="Filters linked performers by Cove metadata. It does not infer gender from video frames.">{id => <select id={id} value={faceGender} onChange={e => setFaceGender(e.target.value)}><option value="female">Female</option><option value="male">Male</option><option value="trans">Trans performers</option><option value="all">All performers</option></select>}</Control></div>
    <div className="pmv-face-actions"><button type="button" onClick={() => setFaceIds([...new Set([...(faceIds || []), ...(preview?.performers || []).filter(p => p.hasReference && genderFits(p, faceGender)).map(p => p.id)])])}>Select matching</button><button type="button" onClick={() => setFaceIds([])}>Deselect all</button><small>{faceIds.length} selected</small></div>
    <div className="pmv-face-list">{(preview?.performers || []).filter(person => genderFits(person, faceGender) || faceIds.includes(person.id)).map(person => <button type="button" key={person.id} className={faceIds.includes(person.id) ? "selected" : ""} disabled={!person.hasReference} onClick={() => setFaceIds(current => current.includes(person.id) ? current.filter(id => id !== person.id) : [...current, person.id])} aria-pressed={faceIds.includes(person.id)}>{person.name}{!person.hasReference ? " · no reference image" : ""}</button>)}</div>
  </fieldset>;
  if (queued) return <div className="pmv-overlay" role="dialog" aria-modal="true" aria-label="Order queued"><div className="pmv-dialog">
    <h2>ORDER{queued.orderNumber} queued</h2><p>{queued.message}</p>
    <p>Search Cove for <strong>PMVMAKER_ORDER{queued.orderNumber}_</strong> to compare the finished versions. Each output includes a settings receipt.</p>
    <button onClick={close}>Done</button>
  </div></div>;
  return <div className="pmv-overlay" role="dialog" aria-modal="true" aria-label="Create PMV"><div className="pmv-dialog">
    <header><h2>Create PMV</h2><button disabled={busy} onClick={cancel} aria-label="Close">×</button></header>
    <fieldset disabled={busy || !!submission.current} className="pmv-working">
    <p>{preview ? `${preview.eligibleCount} eligible sources · ${preview.proposedFilename}` : "Checking sources…"}</p>
    {preview?.eligibilityNote && <p role="alert">{preview.eligibilityNote}</p>}
    {!!preview?.exclusions?.length && <details><summary>{preview.exclusions.length} excluded sources</summary><ul>{preview.exclusions.map((x, i) => <li key={i}>{x}</li>)}</ul></details>}
    <details className="pmv-advanced"><summary>Scene filters</summary><SegmentSection options={options} setOptions={setOptions} /></details>
    <fieldset><legend>Backing audio</legend><div className="pmv-grid">
      <Control label="Source" help="Choose a backing song from Cove, the configured music folder, a local song file, YouTube, or a Cove video's audio.">{id => <select id={id} value={audio.kind} onChange={e => changeAudioKind(e.target.value)}><option value="cove">Cove audio</option><option value="folder">Configured music folder</option><option value="upload">Choose song file</option><option value="youtube">YouTube URL</option><option value="video">Cove video audio</option></select>}</Control>
      {audio.kind === "upload" && <Control label="Song file" help="Upload an audio file directly from your computer. The companion stores it temporarily and removes it after the PMV job.">{id => <><input id={id} type="file" accept=".mp3,.wav,.flac,.m4a,.aac,.ogg,.opus,.aiff,audio/*" onChange={e => chooseSong(e.target.files?.[0])} /><small>{uploading ? "Uploading song…" : audio.uploadId ? `${audio.name} ready` : "Choose an audio file up to 200 MB."}</small></>}</Control>}
      {audio.kind === "cove" && <div className="pmv-track-browser pmv-grid-span">
        <Control label="Search Cove audio" help="Search Cove's audio library. Select a result below to use it as the backing song.">{id => <input id={id} value={query} onChange={e => setQuery(e.target.value)} placeholder="Search by title" />}</Control>
        <div className="pmv-track-list" role="region" aria-label="Cove audio search results">
          {audioError ? <p role="alert" className="pmv-tree-hint">{audioError}</p> : audioLoading ? <p className="pmv-tree-hint">Searching…</p>
            : audioItems.length ? audioItems.map(x => { const url = `/api/audios/${x.id}/stream`; return <TrackRow key={x.id}
              name={x.title || x.minPath || `Audio ${x.id}`} duration={x.maxDuration} selected={audio.coveAudioId === x.id} playing={playingUrl === url}
              onSelect={() => { setAudio({ kind: "cove", coveAudioId: x.id }); setSelectedAudioName(x.title || x.minPath || `Audio ${x.id}`); }} onPreview={() => playPreview(url)} />; })
              : <p className="pmv-tree-hint">No matching audio tracks.</p>}
        </div>
        {audio.coveAudioId && <small className="pmv-selected-track">Selected: {selectedAudioName || `Audio ${audio.coveAudioId}`}</small>}
      </div>}
      {audio.kind === "folder" && <div className="pmv-grid-span"><MusicTree selectedPath={audio.path} playingUrl={playingUrl}
        onSelect={path => setAudio({ kind: "folder", path })} onPreview={playPreview} />
        {audio.path && <small className="pmv-selected-track">Selected: {audio.path}</small>}</div>}
      {audio.kind === "youtube" && <Control label="YouTube URL" help="Paste an HTTPS YouTube video URL. The companion downloads only its audio for the PMV.">{id => <input id={id} type="url" value={audio.url || ""} onChange={e => setAudio({ kind: "youtube", url: e.target.value })} />}</Control>}
      {audio.kind === "video" && <><Control label="Search Cove videos" help="Filter Cove videos by title to find the source of your backing audio.">{id => <input id={id} value={videoQuery} onChange={e => setVideoQuery(e.target.value)} />}</Control><Control label="Video" help="Extracts this Cove video's audio as the backing song.">{id => <select id={id} value={audio.coveVideoId || ""} onChange={e => setAudio({ kind: "video", coveVideoId: Number(e.target.value) })}><option value="">Choose video</option>{videoItems.map(x => <option key={x.id} value={x.id}>{x.title || x.minPath || `Video ${x.id}`}</option>)}</select>}</Control></>}
    </div>{!audioReady && <small className="pmv-audio-hint">Choose a backing track to enable Create.</small>}<audio ref={audioPlayer} className="pmv-audio-preview" controls style={{ display: previewUrl ? "block" : "none" }}
      onEnded={() => setPlayingUrl("")} onPause={() => setPlayingUrl("")}
      onError={() => { setPlayingUrl(""); setError("Could not play this track. Check that Cove can read it and your account can stream audio."); }} /></fieldset>
    <OptionForm options={options} setOptions={setOptions} portraitFaceControls={portraitFaceControls} />
    <fieldset className="pmv-cart"><legend>Comparison cart · {cart.length}/20</legend>
      <p>Add a version, change a few settings, and add another. Processing groups them under one searchable ORDER number.</p>
      <Control label="Version name (optional)" help="Included in the output filename alongside the order number and version index.">{id => <input id={id} value={variantName} maxLength={80} placeholder={options.style} onChange={e => setVariantName(e.target.value)} />}</Control>
      <button type="button" disabled={busy || uploading || (cart.length >= 20 && editing === null) || !audioReady || !segmentsReady || !preview?.canCreate} onClick={addOrder}>{editing === null ? "Add order to cart" : "Save version changes"}</button>
      {cart.map((line, index) => <div className="pmv-cart-line" key={index}>
        <div><strong>{index + 1}. {line.name}</strong><small>{line.songName} · {(line.options.layoutModes?.length ? line.options.layoutModes : ["full-screen"]).join(" + ")} · {line.options.previewSeconds ? "25 sec" : "full song"} · {effectSections.filter(([key]) => line.options[key] !== false).length} effects</small></div>
        <button type="button" disabled={busy} onClick={() => editOrder(index)}>Edit</button>
        <button type="button" disabled={busy} onClick={() => removeOrder(index)}>Remove</button>
      </div>)}
    </fieldset>
    {(error || settingsError) && <p role="alert">{error || settingsError}</p>}
    </fieldset>
    <footer><button disabled={busy} onClick={cancel}>Cancel</button><button disabled={busy || uploading || editing !== null || (!cart.length && (!audioReady || !segmentsReady || !preview?.canCreate))} onClick={create}>{busy ? "Queueing order…" : cart.length ? `Process orders (${cart.length})` : "Create PMV"}</button></footer>
  </div></div>;
}

export function PmvLauncher() {
  const [context, setContext] = useState(null);
  useEffect(() => { const open = e => setContext(e.detail); window.addEventListener("pmvmaker:open", open);
    return () => window.removeEventListener("pmvmaker:open", open); }, []);
  return context ? <PmvDialog context={context} close={() => setContext(null)} /> : null;
}

export default { components: { PmvLauncher, PmvSettingsPanel }, actionHandlers: { openPmv } };
