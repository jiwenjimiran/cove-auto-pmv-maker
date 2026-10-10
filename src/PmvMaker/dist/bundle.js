// src/index.jsx
import React from "@cove/runtime/react";
import { extensionFetch } from "@cove/runtime/api";
var { useEffect, useRef, useState } = React;
var base = "/api/ext/pmv";
var companionAsset = "/api/extensions/assets/io.github.jiwenjimiran.auto-pmv-maker/companion/AutoPmvMakerCompanion.zip";
async function api(path, method = "GET", body) {
  const response = await extensionFetch(base + path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : void 0
  });
  const raw = await response.text();
  let result = null;
  if (raw) {
    try {
      result = JSON.parse(raw);
    } catch {
      throw new Error(`Cove returned an invalid response for ${path} (${response.status}).`);
    }
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
  window.setTimeout(() => URL.revokeObjectURL(url), 6e4);
}
async function uploadSongFile(file) {
  const extension = file.name.match(/\.[^.]+$/)?.[0]?.toLowerCase() || "";
  if (!/^(\.mp3|\.wav|\.flac|\.m4a|\.aac|\.ogg|\.opus|\.aiff)$/.test(extension) || file.size > 200 * 1024 * 1024)
    throw new Error("Choose an audio file under 200 MB (MP3, WAV, FLAC, M4A, AAC, OGG, OPUS, or AIFF).");
  const response = await extensionFetch(base + "/upload-audio", {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream", "X-PMV-Extension": extension },
    body: file
  });
  const raw = await response.text();
  let result = {};
  if (raw) {
    try {
      result = JSON.parse(raw);
    } catch {
      throw new Error(`Cove returned an invalid upload response (${response.status}).`);
    }
  }
  if (!response.ok) throw new Error(result.message || `Song upload failed (${response.status}).`);
  if (!result.uploadId) throw new Error("The companion did not return an uploaded song ID.");
  return result.uploadId;
}
function openPmv(_action, payload) {
  window.dispatchEvent(new CustomEvent("pmvmaker:open", { detail: payload }));
  return { cancelled: true };
}
var styleHelp = {
  "rhythmic-polish": "Precise cuts and restrained accents.",
  "high-energy": "Faster cuts, stronger motion, and controlled accents.",
  cinematic: "Longer shots and softer pacing."
};
var stylePresets = {
  "rhythmic-polish": { motionIntensityMin: 0.15, motionIntensityMax: 0.35, transitionIntensityMin: 0.15, transitionIntensityMax: 0.35, flashIntensityMin: 0, flashIntensityMax: 0, glitchIntensityMin: 0, glitchIntensityMax: 0 },
  "high-energy": { motionIntensityMin: 0.5, motionIntensityMax: 0.8, transitionIntensityMin: 0.2, transitionIntensityMax: 0.5, flashIntensityMin: 0.2, flashIntensityMax: 0.45, glitchIntensityMin: 0.15, glitchIntensityMax: 0.35 },
  cinematic: { motionIntensityMin: 0.1, motionIntensityMax: 0.3, transitionIntensityMin: 0.35, transitionIntensityMax: 0.65, flashIntensityMin: 0, flashIntensityMax: 0, glitchIntensityMin: 0, glitchIntensityMax: 0 }
};
var optionHelp = {
  layoutModes: "Select any combination. Each selected mode appears in the song, changing at phrase boundaries. With none selected, the edit uses Full screen.",
  useVerticalVideosOnly: "Only portrait source videos may appear in the three-pane edit. Landscape videos are excluded before planning.",
  selectionMode: "For landscape footage, choose a random vertical crop, the center crop, or a crop around a detected face.",
  fullSelectionMode: "Scene uses a usable shot. Face match also requires a selected performer's face throughout the full-screen shot.",
  keepFaceCentered: "Moves a full-height portrait crop horizontally with the chosen face. It never zooms in on the face.",
  matchSelectedPerformers: "Matches detected faces against the selected performers' Cove images. A range without a confident match is skipped.",
  faceSimilarityThreshold: "Every accepted sampled face must reach this SFace cosine similarity to a selected performer image. 55% is the minimum allowed. This is a model similarity score, not a probability of identity. Full-screen Scene mode does not perform face matching.",
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
  outputCodec: "Render an MP4 with H.264, H.265, or AV1. Available encoders depend on this PC's Resolve Studio and graphics hardware; Create checks the choice before queueing.",
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
    const closeOutside = (event) => {
      if (!wrapper.current?.contains(event.target)) setOpen(false);
    };
    const closeEscape = (event) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeEscape);
    };
  }, [open]);
  return /* @__PURE__ */ React.createElement("span", { className: "pmv-info", ref: wrapper }, /* @__PURE__ */ React.createElement(
    "button",
    {
      type: "button",
      className: "pmv-info-button",
      "aria-label": `About ${label}`,
      "aria-expanded": open,
      "aria-controls": id,
      onClick: () => setOpen((value) => !value)
    },
    "i"
  ), open && /* @__PURE__ */ React.createElement("span", { id, className: "pmv-info-text", role: "note" }, help));
}
function Control({ label, help, children, className = "" }) {
  const id = React.useId();
  return /* @__PURE__ */ React.createElement("div", { className: `pmv-control ${className}` }, /* @__PURE__ */ React.createElement("div", { className: "pmv-control-heading" }, /* @__PURE__ */ React.createElement("label", { htmlFor: id }, label), /* @__PURE__ */ React.createElement(InfoButton, { label, help })), children(id));
}
function HelpAction({ label, help, children }) {
  return /* @__PURE__ */ React.createElement("span", { className: "pmv-action-help" }, children, /* @__PURE__ */ React.createElement(InfoButton, { label, help }));
}
function FolderSetting({ label, help, value, onBrowse, onClear, optional }) {
  return /* @__PURE__ */ React.createElement(Control, { label, help }, (id) => /* @__PURE__ */ React.createElement("div", { className: "pmv-folder-row" }, /* @__PURE__ */ React.createElement("input", { id, type: "text", readOnly: true, value: value || "", placeholder: "Choose a folder" }), /* @__PURE__ */ React.createElement("button", { type: "button", onClick: onBrowse }, "Browse folders"), optional && value && /* @__PURE__ */ React.createElement("button", { type: "button", onClick: onClear }, "Clear")));
}
function RangeControl({ label, help, lower, upper, onChange, minValue = 0, maxValue = 1, step = 0.05 }) {
  return /* @__PURE__ */ React.createElement(Control, { label, help }, (id) => /* @__PURE__ */ React.createElement("div", { className: "pmv-range-pair" }, /* @__PURE__ */ React.createElement("label", null, "Min ", /* @__PURE__ */ React.createElement(
    "input",
    {
      id,
      type: "number",
      min: minValue,
      max: maxValue,
      step,
      value: lower,
      onChange: (e) => onChange(Math.min(Number(e.target.value), upper), upper)
    }
  )), /* @__PURE__ */ React.createElement("label", null, "Max ", /* @__PURE__ */ React.createElement(
    "input",
    {
      type: "number",
      min: minValue,
      max: maxValue,
      step,
      value: upper,
      onChange: (e) => onChange(lower, Math.max(Number(e.target.value), lower))
    }
  ))));
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
    if (expanded && children === null) loadChildren(folder.path).then(setChildren).catch((e) => setError(e.message));
  }, [expanded, folder.path, loadChildren]);
  return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: `pmv-tree-row ${selected === folder.path ? "is-selected" : ""}`, style: { paddingLeft: 8 + depth * 18 } }, folder.hasChildren ? /* @__PURE__ */ React.createElement(
    "button",
    {
      type: "button",
      className: `pmv-tree-expand ${expanded ? "is-open" : ""}`,
      onClick: () => setExpanded((value) => !value),
      "aria-label": `${expanded ? "Collapse" : "Expand"} ${folder.name}`
    },
    /* @__PURE__ */ React.createElement("span", { className: "pmv-chevron" })
  ) : /* @__PURE__ */ React.createElement("span", { className: "pmv-tree-spacer" }), /* @__PURE__ */ React.createElement("label", { title: folder.path }, /* @__PURE__ */ React.createElement(
    "input",
    {
      type: "radio",
      name: radioName,
      checked: selected === folder.path,
      onChange: () => onSelect(folder.path)
    }
  ), /* @__PURE__ */ React.createElement("svg", { className: "pmv-folder-icon", viewBox: "0 0 20 20", fill: "none", "aria-hidden": "true" }, /* @__PURE__ */ React.createElement("path", { d: "M2.5 5.5h5l1.7 1.8h8.3v8.2H2.5z", stroke: "currentColor", strokeWidth: "1.5", strokeLinejoin: "round" })), /* @__PURE__ */ React.createElement("span", null, folder.name))), expanded && (error ? /* @__PURE__ */ React.createElement("p", { role: "alert", className: "pmv-tree-hint" }, error) : children === null ? /* @__PURE__ */ React.createElement("small", { className: "pmv-tree-hint" }, "Loading folders\u2026") : children.length ? children.map((child) => /* @__PURE__ */ React.createElement(FolderNode, { key: child.path, folder: child, depth: depth + 1, selected, onSelect, loadChildren, radioName })) : /* @__PURE__ */ React.createElement("small", { className: "pmv-tree-empty" }, "No subfolders")));
}
function FolderPicker({ kind, current, onChoose, onClose }) {
  const [roots, setRoots] = useState(null);
  const [selected, setSelected] = useState(current || "");
  const [error, setError] = useState("");
  const output = kind === "outputFolder";
  const title = output ? "Cove library folders" : kind === "musicFolder" ? "Choose music folder" : "Choose project folder";
  const loadChildren = output ? coveFolders : filesystemFolders;
  useEffect(() => {
    (output ? api("/scan-roots") : filesystemFolders()).then(setRoots).catch((e) => setError(e.message));
  }, [output]);
  return /* @__PURE__ */ React.createElement("div", { className: "pmv-folder-browser", role: "region", "aria-label": title }, /* @__PURE__ */ React.createElement("div", { className: "pmv-folder-browser-head" }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("strong", null, title), /* @__PURE__ */ React.createElement("small", null, output ? "Choose a folder Cove can scan for finished videos." : "Expand a drive and choose a folder Cove can read.")), /* @__PURE__ */ React.createElement("button", { type: "button", className: "pmv-browser-close", onClick: onClose, "aria-label": "Close folder browser" }, "\xD7")), /* @__PURE__ */ React.createElement("div", { className: "pmv-tree" }, error ? /* @__PURE__ */ React.createElement("p", { role: "alert" }, error) : roots === null ? /* @__PURE__ */ React.createElement("p", { className: "pmv-tree-hint" }, "Loading Cove folders\u2026") : roots.length ? roots.map((root) => /* @__PURE__ */ React.createElement(FolderNode, { key: root.path, folder: root, depth: 0, selected, onSelect: setSelected, loadChildren, radioName: `pmv-${kind}` })) : /* @__PURE__ */ React.createElement("p", { className: "pmv-tree-hint" }, output ? "No video-scanning library paths are configured in Cove." : "No folders are available to Cove.")), /* @__PURE__ */ React.createElement("div", { className: "pmv-folder-browser-foot" }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("small", null, "Selected folder"), /* @__PURE__ */ React.createElement("span", { title: selected }, selected || "Choose a folder")), /* @__PURE__ */ React.createElement("button", { type: "button", className: "pmv-button-primary", disabled: !selected, onClick: () => onChoose(selected) }, "Use folder")));
}
var defaultOptions = {
  layout: "full-screen",
  layoutModes: [],
  useVerticalVideosOnly: false,
  selectionMode: "face",
  fullSelectionMode: "face",
  segmentTagIds: [],
  keepFaceCentered: true,
  matchSelectedPerformers: true,
  faceSimilarityThreshold: 0.55,
  mirrorRepeatedSource: true,
  sampledClipsProgress: true,
  minimumTimestampSeconds: 0,
  endBufferSeconds: 0,
  cycleLongerClipIntoSegments: true,
  rotatedClipLengthSeconds: 30,
  beatsPerBar: "auto",
  style: "rhythmic-polish",
  sourceAudio: "mixed",
  pacingMin: 0.4,
  pacingMax: 0.7,
  beatAdherence: 0.95,
  minClipSeconds: 1,
  maxClipSeconds: 5,
  sourceDiversity: 0.8,
  transitionFamilies: ["cut", "dissolve"],
  transitionIntensityMin: 0.15,
  transitionIntensityMax: 0.35,
  motionIntensityMin: 0.15,
  motionIntensityMax: 0.35,
  flashIntensityMin: 0,
  flashIntensityMax: 0,
  glitchIntensityMin: 0,
  glitchIntensityMax: 0,
  colorTreatment: "natural",
  songTrimStart: null,
  songTrimEnd: null,
  outputFps: null,
  outputCodec: "h264",
  saveProject: false,
  scanToCove: true,
  keepPerformers: true,
  keepTags: true,
  addPmvTag: true,
  addAutoPmvTag: true
};
function selectedModes(options) {
  return options.layoutModes?.length ? options.layoutModes : ["full-screen"];
}
function needsFaceReferences(options) {
  const modes = selectedModes(options);
  const sliceMode = options.selectionMode === "face" && (modes.includes("grid") || modes.includes("three-pane") && !options.useVerticalVideosOnly);
  const fullMode = modes.includes("full-screen") && options.fullSelectionMode === "face";
  return options.matchSelectedPerformers !== false && (sliceMode || fullMode);
}
function SegmentTagPicker({ ids, onChange }) {
  const [query, setQuery] = useState("");
  const [tags, setTags] = useState([]);
  const [selected, setSelected] = useState([]);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!ids?.length) {
      setSelected([]);
      return;
    }
    api("/segment-tags?ids=" + ids.join(",")).then(setSelected).catch((e) => setError(e.message));
  }, [JSON.stringify(ids || [])]);
  useEffect(() => {
    if (query.trim().length < 2) {
      setTags([]);
      return;
    }
    let active = true;
    const timer = window.setTimeout(() => api("/segment-tags?q=" + encodeURIComponent(query.trim())).then((rows) => {
      if (active) {
        setTags(rows);
        setError("");
      }
    }).catch((e) => {
      if (active) setError(e.message);
    }), 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [query]);
  const chosen = ids || [];
  return /* @__PURE__ */ React.createElement("fieldset", { className: "pmv-face-picker" }, /* @__PURE__ */ React.createElement("legend", null, "Segment list"), /* @__PURE__ */ React.createElement("p", null, "When populated, only time inside matching timed segment tags is eligible. Multiple tags match either tag."), /* @__PURE__ */ React.createElement("input", { "aria-label": "Search segment tags", value: query, onChange: (e) => setQuery(e.target.value), placeholder: "Search segment tags, e.g. fingers" }), error && /* @__PURE__ */ React.createElement("p", { role: "alert" }, error), /* @__PURE__ */ React.createElement("div", { className: "pmv-face-list" }, selected.map((tag) => /* @__PURE__ */ React.createElement("button", { type: "button", key: tag.id, className: "selected", onClick: () => onChange(chosen.filter((id) => id !== tag.id)) }, tag.name, tag.hasTimedSegments === false ? " (no timed segments)" : "", " \xD7")), tags.filter((tag) => !chosen.includes(tag.id)).map((tag) => /* @__PURE__ */ React.createElement("button", { type: "button", key: tag.id, onClick: () => {
    onChange([...chosen, tag.id]);
    setQuery("");
  } }, tag.name, " +"))));
}
function OptionForm({ options, setOptions }) {
  const set = (key, value) => setOptions((current) => ({ ...current, [key]: value }));
  const modes = selectedModes(options);
  const slices = modes.includes("grid") || modes.includes("three-pane");
  const portrait = modes.includes("three-pane");
  const full = modes.includes("full-screen");
  const faceSlices = modes.includes("grid") || portrait && !options.useVerticalVideosOnly;
  const toggleMode = (mode, enabled) => setOptions((current) => ({
    ...current,
    layoutModes: enabled ? [.../* @__PURE__ */ new Set([...current.layoutModes || [], mode])] : (current.layoutModes || []).filter((item) => item !== mode)
  }));
  return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "pmv-form-heading" }, /* @__PURE__ */ React.createElement("h5", null, "Layout settings"), /* @__PURE__ */ React.createElement("span", null, "01")), /* @__PURE__ */ React.createElement("fieldset", { className: "pmv-layout-choices" }, /* @__PURE__ */ React.createElement("legend", null, "Modes ", /* @__PURE__ */ React.createElement(InfoButton, { label: "Modes", help: optionHelp.layoutModes })), /* @__PURE__ */ React.createElement("div", { className: "pmv-checkbox-grid" }, [["grid", "Grid (four videos)"], ["three-pane", "Triple portrait"], ["full-screen", "Full screen"]].map(([mode, label]) => /* @__PURE__ */ React.createElement(Control, { key: mode, label, help: optionHelp.layoutModes, className: "pmv-toggle" }, (id) => /* @__PURE__ */ React.createElement("input", { id, type: "checkbox", checked: (options.layoutModes || []).includes(mode), onChange: (e) => toggleMode(mode, e.target.checked) })))), !(options.layoutModes || []).length && /* @__PURE__ */ React.createElement("small", null, "No modes checked: Full screen will be used.")), /* @__PURE__ */ React.createElement("div", { className: "pmv-grid" }, portrait && /* @__PURE__ */ React.createElement(Control, { label: "Use vertical videos only", help: optionHelp.useVerticalVideosOnly, className: "pmv-toggle" }, (id) => /* @__PURE__ */ React.createElement("input", { id, type: "checkbox", checked: !!options.useVerticalVideosOnly, onChange: (e) => set("useVerticalVideosOnly", e.target.checked) })), slices && faceSlices && /* @__PURE__ */ React.createElement(Control, { label: "Slice selection mode", help: optionHelp.selectionMode }, (id) => /* @__PURE__ */ React.createElement("select", { id, value: options.selectionMode || "center", onChange: (e) => set("selectionMode", e.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "random" }, "Random slice"), /* @__PURE__ */ React.createElement("option", { value: "center" }, "Center slice"), /* @__PURE__ */ React.createElement("option", { value: "face" }, "Face slice"))), slices && faceSlices && options.selectionMode === "face" && /* @__PURE__ */ React.createElement(Control, { label: "Keep face centered", help: optionHelp.keepFaceCentered, className: "pmv-toggle" }, (id) => /* @__PURE__ */ React.createElement("input", { id, type: "checkbox", checked: options.keepFaceCentered !== false, onChange: (e) => set("keepFaceCentered", e.target.checked) })), full && /* @__PURE__ */ React.createElement(Control, { label: "Full-screen selection mode", help: optionHelp.fullSelectionMode }, (id) => /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("select", { id, value: options.fullSelectionMode || "face", onChange: (e) => set("fullSelectionMode", e.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "face" }, "Face match"), /* @__PURE__ */ React.createElement("option", { value: "scene" }, "Scene (no performer check)")), options.fullSelectionMode === "scene" && /* @__PURE__ */ React.createElement("small", null, "Scene shots are not matched to a performer."))), (slices && faceSlices && options.selectionMode === "face" || full && options.fullSelectionMode === "face") && /* @__PURE__ */ React.createElement(Control, { label: "Match selected performers", help: optionHelp.matchSelectedPerformers, className: "pmv-toggle" }, (id) => /* @__PURE__ */ React.createElement("input", { id, type: "checkbox", checked: options.matchSelectedPerformers !== false, onChange: (e) => set("matchSelectedPerformers", e.target.checked) })), portrait && /* @__PURE__ */ React.createElement(Control, { label: "Mirror repeated source", help: optionHelp.mirrorRepeatedSource, className: "pmv-toggle" }, (id) => /* @__PURE__ */ React.createElement("input", { id, type: "checkbox", checked: options.mirrorRepeatedSource !== false, onChange: (e) => set("mirrorRepeatedSource", e.target.checked) }))), /* @__PURE__ */ React.createElement("div", { className: "pmv-form-heading" }, /* @__PURE__ */ React.createElement("h5", null, "Creative direction"), /* @__PURE__ */ React.createElement("span", null, "02")), /* @__PURE__ */ React.createElement("div", { className: "pmv-grid" }, /* @__PURE__ */ React.createElement(Control, { label: "Style", help: optionHelp.style }, (id) => /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("select", { id, value: options.style, onChange: (e) => setOptions((current) => ({ ...current, style: e.target.value, ...stylePresets[e.target.value] })) }, Object.keys(styleHelp).map((x) => /* @__PURE__ */ React.createElement("option", { key: x, value: x }, x.replaceAll("-", " ")))), /* @__PURE__ */ React.createElement("small", null, styleHelp[options.style]))), /* @__PURE__ */ React.createElement(Control, { label: "Source audio", help: optionHelp.sourceAudio }, (id) => /* @__PURE__ */ React.createElement("select", { id, value: options.sourceAudio, onChange: (e) => set("sourceAudio", e.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "muted" }, "Muted"), /* @__PURE__ */ React.createElement("option", { value: "mixed" }, "Mixed \xB7 brief accents"), /* @__PURE__ */ React.createElement("option", { value: "all" }, "All source audio"))), /* @__PURE__ */ React.createElement(Control, { label: "Render codec", help: optionHelp.outputCodec }, (id) => /* @__PURE__ */ React.createElement("select", { id, value: options.outputCodec || "h264", onChange: (e) => set("outputCodec", e.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "h264" }, "H.264 MP4"), /* @__PURE__ */ React.createElement("option", { value: "h265" }, "H.265 MP4"), /* @__PURE__ */ React.createElement("option", { value: "av1" }, "AV1 MP4")))), /* @__PURE__ */ React.createElement("details", { className: "pmv-advanced" }, /* @__PURE__ */ React.createElement("summary", null, "Advanced edit controls"), /* @__PURE__ */ React.createElement("div", { className: "pmv-grid" }, [["pacing", "Pacing"], ["transitionIntensity", "Transition intensity"], ["motionIntensity", "Motion"], ["flashIntensity", "Flash"], ["glitchIntensity", "Glitch"]].map(([key, label]) => /* @__PURE__ */ React.createElement(RangeControl, { key, label, help: optionHelp[key], lower: options[`${key}Min`] ?? 0, upper: options[`${key}Max`] ?? 0, onChange: (lower, upper) => setOptions((current) => ({ ...current, [`${key}Min`]: lower, [`${key}Max`]: upper })) })), /* @__PURE__ */ React.createElement(RangeControl, { label: "Clip length (sec)", help: optionHelp.clipLength, lower: options.minClipSeconds, upper: options.maxClipSeconds, minValue: 0.25, maxValue: 30, step: 0.25, onChange: (lower, upper) => setOptions((current) => ({ ...current, minClipSeconds: lower, maxClipSeconds: upper })) }), /* @__PURE__ */ React.createElement(Control, { label: "Sampled clips progress through video", help: optionHelp.sampledClipsProgress, className: "pmv-toggle" }, (id) => /* @__PURE__ */ React.createElement("input", { id, type: "checkbox", checked: options.sampledClipsProgress !== false, onChange: (e) => set("sampledClipsProgress", e.target.checked) })), /* @__PURE__ */ React.createElement(Control, { label: "Cycle longer clip into segments", help: optionHelp.cycleLongerClipIntoSegments, className: "pmv-toggle" }, (id) => /* @__PURE__ */ React.createElement("input", { id, type: "checkbox", checked: options.cycleLongerClipIntoSegments !== false, onChange: (e) => set("cycleLongerClipIntoSegments", e.target.checked) })), [["minimumTimestampSeconds", "Clip minimum timestamp"], ["endBufferSeconds", "Keep clear before source end"], ["rotatedClipLengthSeconds", "Rotated scene length"]].map(([key, label]) => /* @__PURE__ */ React.createElement(Control, { key, label: `${label} (sec)`, help: optionHelp[key] }, (id) => /* @__PURE__ */ React.createElement("input", { id, type: "number", min: "0", max: key === "rotatedClipLengthSeconds" ? 300 : void 0, step: "0.5", value: options[key] ?? 0, onChange: (e) => set(key, Number(e.target.value)) }))), /* @__PURE__ */ React.createElement(Control, { label: "Beats per bar", help: optionHelp.beatsPerBar }, (id) => /* @__PURE__ */ React.createElement("select", { id, value: options.beatsPerBar || "auto", onChange: (e) => set("beatsPerBar", e.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "auto" }, "Auto"), /* @__PURE__ */ React.createElement("option", { value: "3" }, "3"), /* @__PURE__ */ React.createElement("option", { value: "4" }, "4"), /* @__PURE__ */ React.createElement("option", { value: "6" }, "6"))), (slices && faceSlices && options.selectionMode === "face" || full && options.fullSelectionMode === "face") && options.matchSelectedPerformers !== false && /* @__PURE__ */ React.createElement(Control, { label: "Face slice performer matching minimum confidence required", help: optionHelp.faceSimilarityThreshold }, (id) => /* @__PURE__ */ React.createElement("div", { className: "pmv-range" }, /* @__PURE__ */ React.createElement("input", { id, type: "range", min: "0.55", max: "0.8", step: "0.01", value: Math.max(0.55, options.faceSimilarityThreshold ?? 0.55), onChange: (e) => set("faceSimilarityThreshold", Number(e.target.value)) }), /* @__PURE__ */ React.createElement("output", null, Math.round(100 * Math.max(0.55, options.faceSimilarityThreshold ?? 0.55)), "%"))), ["beatAdherence", "sourceDiversity"].map((key) => /* @__PURE__ */ React.createElement(Control, { key, label: key === "beatAdherence" ? "Beat adherence" : "Source diversity", help: optionHelp[key] }, (id) => /* @__PURE__ */ React.createElement("div", { className: "pmv-range" }, /* @__PURE__ */ React.createElement("input", { id, type: "range", min: "0", max: "1", step: "0.05", value: options[key], onChange: (e) => set(key, Number(e.target.value)) }), /* @__PURE__ */ React.createElement("output", null, Number(options[key]).toFixed(2))))), ["songTrimStart", "songTrimEnd"].map((key, i) => /* @__PURE__ */ React.createElement(Control, { key, label: ["Song start (sec)", "Song end (sec)"][i], help: optionHelp[key] }, (id) => /* @__PURE__ */ React.createElement("input", { id, type: "number", min: "0", step: "any", value: options[key] ?? "", onChange: (e) => set(key, e.target.value === "" ? null : Number(e.target.value)) }))), /* @__PURE__ */ React.createElement(Control, { label: "FPS override", help: optionHelp.outputFps }, (id) => /* @__PURE__ */ React.createElement("select", { id, value: options.outputFps ?? "", onChange: (e) => set("outputFps", e.target.value ? Number(e.target.value) : null) }, /* @__PURE__ */ React.createElement("option", { value: "" }, "Auto"), /* @__PURE__ */ React.createElement("option", { value: "24" }, "24 fps"), /* @__PURE__ */ React.createElement("option", { value: "25" }, "25 fps"), /* @__PURE__ */ React.createElement("option", { value: "30" }, "30 fps"), /* @__PURE__ */ React.createElement("option", { value: "50" }, "50 fps"), /* @__PURE__ */ React.createElement("option", { value: "60" }, "60 fps"))), /* @__PURE__ */ React.createElement(Control, { label: "Transitions", help: optionHelp.transitionFamilies }, (id) => /* @__PURE__ */ React.createElement("select", { id, value: options.transitionFamilies?.join(",") || "cut", onChange: (e) => set("transitionFamilies", e.target.value.split(",")) }, /* @__PURE__ */ React.createElement("option", { value: "cut" }, "Cuts"), /* @__PURE__ */ React.createElement("option", { value: "cut,dissolve" }, "Cuts and dissolves"))), /* @__PURE__ */ React.createElement(Control, { label: "Color matching", help: optionHelp.colorTreatment }, (id) => /* @__PURE__ */ React.createElement("select", { id, value: options.colorTreatment, onChange: (e) => set("colorTreatment", e.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "natural" }, "None"), /* @__PURE__ */ React.createElement("option", { value: "matched" }, "Match brightness"), /* @__PURE__ */ React.createElement("option", { value: "warm" }, "Warm"), /* @__PURE__ */ React.createElement("option", { value: "cool" }, "Cool")))), /* @__PURE__ */ React.createElement("div", { className: "pmv-form-heading" }, /* @__PURE__ */ React.createElement("h5", null, "Output and Cove metadata"), /* @__PURE__ */ React.createElement("span", null, "03")), /* @__PURE__ */ React.createElement("div", { className: "pmv-checkbox-grid" }, [["saveProject", "Save project (.drp)"], ["scanToCove", "Scan to Cove"], ["keepPerformers", "Keep performers"], ["keepTags", "Keep used segment tags"], ["addPmvTag", "Add PMV tag"], ["addAutoPmvTag", "Add Auto_PMV tag"]].map(([key, label]) => /* @__PURE__ */ React.createElement(Control, { key, label, help: optionHelp[key], className: "pmv-toggle" }, (id) => /* @__PURE__ */ React.createElement("input", { id, type: "checkbox", checked: !!options[key], onChange: (e) => set(key, e.target.checked) }))))));
}
function useSettings(path = "/settings") {
  const [settings, setSettings] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api(path).then(setSettings).catch((e) => setError(e.message));
  }, [path]);
  return [settings, setSettings, error, setError];
}
function PmvSettingsPanel() {
  const [settings, setSettings, error, setError] = useSettings();
  const [message, setMessage] = useState("");
  const [health, setHealth] = useState(null);
  const [local, setLocal] = useState(null);
  const [validation, setValidation] = useState(null);
  const [mappingText, setMappingText] = useState("[]");
  const [mappingValid, setMappingValid] = useState(true);
  const [browsing, setBrowsing] = useState(null);
  useEffect(() => {
    if (settings) setMappingText(JSON.stringify(settings.pathMappings || [], null, 2));
  }, [!!settings]);
  useEffect(() => {
    if (settings?.companionMode === "auto") api("/local-companion").then(setLocal).catch((e) => setError(e.message));
  }, [settings?.companionMode]);
  useEffect(() => {
    if (!settings) return;
    const refresh = () => api("/validation").then(setValidation).catch((e) => setError(e.message));
    refresh();
    const timer = window.setInterval(refresh, 3e3);
    return () => window.clearInterval(timer);
  }, [!!settings]);
  useEffect(() => {
    if (settings) api("/health").then(setHealth).catch((e) => setHealth({ ok: false, error: e.message }));
  }, [!!settings, settings?.companionMode]);
  if (!settings) return /* @__PURE__ */ React.createElement("div", { className: "pmv-settings" }, error || "Loading PMV settings\u2026");
  const set = (key, value) => setSettings((current) => ({ ...current, [key]: value }));
  const defaults = { ...defaultOptions, ...settings.defaults };
  const automatic = settings.companionMode === "auto";
  const ready = !!settings.skipSetupChecks || !!health?.ok && validation?.state === "complete";
  const chooseFolder = (path) => {
    set(browsing, path);
    setBrowsing(null);
  };
  return /* @__PURE__ */ React.createElement("div", { className: "pmv-settings" }, !ready && /* @__PURE__ */ React.createElement("div", { className: "pmv-setup-banner" }, /* @__PURE__ */ React.createElement("strong", null, "Setup required"), /* @__PURE__ */ React.createElement("p", null, "Connect Resolve and check compatibility, or skip setup and configure your first PMV.")), /* @__PURE__ */ React.createElement("details", { className: "pmv-panel pmv-checks", open: !ready }, /* @__PURE__ */ React.createElement("summary", null, "Resolve setup checks"), !ready && /* @__PURE__ */ React.createElement("p", null, "These checks are optional at setup. Jobs still verify Resolve and media paths before rendering."), /* @__PURE__ */ React.createElement("div", { className: "pmv-actions" }, /* @__PURE__ */ React.createElement(HelpAction, { label: "Check Resolve", help: "Checks the Resolve connection and required media tools." }, /* @__PURE__ */ React.createElement("button", { type: "button", onClick: async () => {
    try {
      setHealth(await api("/health"));
      setError("");
    } catch (e) {
      setError(e.message);
    }
  } }, "Check Resolve")), /* @__PURE__ */ React.createElement(HelpAction, { label: "Run Resolve compatibility check", help: "Renders short fixtures to check the installed Resolve version." }, /* @__PURE__ */ React.createElement("button", { type: "button", disabled: !health?.ok || validation?.state === "queued" || validation?.state === "running", onClick: async () => {
    try {
      setValidation(await api("/validation", "POST"));
      setError("");
    } catch (e) {
      setError(e.message);
    }
  } }, "Run Resolve compatibility check")), !ready && /* @__PURE__ */ React.createElement("button", { type: "button", className: "pmv-button-quiet", onClick: async () => {
    try {
      setSettings(await api("/settings", "PUT", { ...settings, skipSetupChecks: true }));
      setMessage("Setup checks skipped. PMV jobs will still check Resolve and media paths before rendering.");
      setError("");
    } catch (e) {
      setError(e.message);
    }
  } }, "Skip setup checks")), settings.skipSetupChecks && /* @__PURE__ */ React.createElement("p", { className: "pmv-setup-note" }, "Setup checks skipped. PMV jobs still check Resolve and media paths before rendering."), health && /* @__PURE__ */ React.createElement("p", { role: "status" }, "Resolve: ", health.ok ? `${health.product} ${health.version} connected` : health.error), validation && validation.state !== "idle" && /* @__PURE__ */ React.createElement("p", { role: "status" }, "Compatibility check: ", validation.message, validation.error ? ` \u2014 ${validation.error}` : "")), !ready && !automatic && /* @__PURE__ */ React.createElement("details", null, /* @__PURE__ */ React.createElement("summary", null, "External companion connection (Docker)"), /* @__PURE__ */ React.createElement("p", null, "Download and start the bundled Windows companion, then save its URL and token before checking Resolve."), /* @__PURE__ */ React.createElement("button", { type: "button", onClick: async () => {
    try {
      await downloadCompanion();
      setMessage("Companion ZIP downloaded.");
    } catch (e) {
      setError(e.message);
    }
  } }, "Download Windows companion"), /* @__PURE__ */ React.createElement("div", { className: "pmv-grid" }, /* @__PURE__ */ React.createElement(Control, { label: "Companion URL", help: "The address shown by the Windows companion." }, (id) => /* @__PURE__ */ React.createElement("input", { id, value: settings.companionUrl || "", onChange: (e) => set("companionUrl", e.target.value) })), /* @__PURE__ */ React.createElement(Control, { label: "Companion token", help: "The private token shown by the Windows companion." }, (id) => /* @__PURE__ */ React.createElement("input", { id, type: "password", value: settings.companionToken || "", onChange: (e) => set("companionToken", e.target.value) })), /* @__PURE__ */ React.createElement("button", { type: "button", onClick: async () => {
    try {
      setSettings(await api("/settings", "PUT", settings));
      setHealth(await api("/health"));
      setError("");
    } catch (e) {
      setError(e.message);
    }
  } }, "Save connection"))), ready && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("section", { className: "pmv-panel" }, /* @__PURE__ */ React.createElement("div", { className: "pmv-section-heading" }, /* @__PURE__ */ React.createElement("h4", null, "Connection"), /* @__PURE__ */ React.createElement("p", null, "How Cove reaches the Windows Resolve companion.")), /* @__PURE__ */ React.createElement(Control, { label: "Connection", help: "Automatic starts the bundled Windows engine with Cove. External connects to the Windows companion when Cove runs in Docker or on another PC." }, (id) => /* @__PURE__ */ React.createElement("select", { id, value: settings.companionMode || "auto", onChange: (e) => set("companionMode", e.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "auto" }, "Automatic (native Windows Cove)"), /* @__PURE__ */ React.createElement("option", { value: "external" }, "External (Docker or another PC)"))), automatic ? /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("p", null, "Cove starts the bundled engine in your Windows desktop session. No download, launcher, URL, or token is needed."), /* @__PURE__ */ React.createElement("p", { role: "status" }, "Engine: ", local ? local.running ? "running" : local.error || "stopped" : "checking\u2026"), /* @__PURE__ */ React.createElement("div", { className: "pmv-actions" }, /* @__PURE__ */ React.createElement(HelpAction, { label: "Restart engine", help: "Restarts the bundled Windows engine after a Resolve scripting change. An active PMV job will be interrupted." }, /* @__PURE__ */ React.createElement("button", { type: "button", onClick: async () => {
    try {
      setLocal(await api("/local-companion/start", "POST"));
      setHealth(null);
      setError("");
    } catch (e) {
      setError(e.message);
    }
  } }, "Restart engine"))), /* @__PURE__ */ React.createElement("small", null, "Restart the engine after changing Resolve's scripting setting. This interrupts any active PMV render.")) : /* @__PURE__ */ React.createElement("details", { open: true }, /* @__PURE__ */ React.createElement("summary", null, "External companion setup"), /* @__PURE__ */ React.createElement("p", null, "For Cove in Docker, run the bundled companion on the Windows desktop and connect it here."), /* @__PURE__ */ React.createElement("div", { className: "pmv-actions" }, /* @__PURE__ */ React.createElement(HelpAction, { label: "Download Windows companion", help: "Downloads the matching Windows companion ZIP for external or Docker mode." }, /* @__PURE__ */ React.createElement("button", { type: "button", onClick: async () => {
    try {
      await downloadCompanion();
      setMessage("Companion ZIP downloaded.");
    } catch (e) {
      setError(e.message);
    }
  } }, "Download Windows companion"))), /* @__PURE__ */ React.createElement("small", null, "Extract the ZIP, run Start Companion Docker.cmd, then enter the displayed URL and token."), /* @__PURE__ */ React.createElement("div", { className: "pmv-grid" }, [["companionUrl", "Companion URL", "The local network address printed by the Windows companion."], ["companionToken", "Companion token", "The private token printed by the Windows companion. Leave blank to keep a saved token."]].map(([key, label, help]) => /* @__PURE__ */ React.createElement(Control, { key, label, help }, (id) => /* @__PURE__ */ React.createElement("input", { id, type: key === "companionToken" ? "password" : "text", value: settings[key] || "", onChange: (e) => set(key, e.target.value) })))), settings.companionConfigured && /* @__PURE__ */ React.createElement("small", null, "A companion token is saved. Leave the field blank to keep it."), /* @__PURE__ */ React.createElement(Control, { label: "Container \u2192 Windows path mappings (JSON)", help: "For Docker, pair each Cove container path with the Windows path that points to the same files. Save mappings before browsing folders." }, (id) => /* @__PURE__ */ React.createElement("textarea", { id, rows: "4", value: mappingText, onChange: (e) => {
    setMappingText(e.target.value);
    try {
      const value = JSON.parse(e.target.value);
      if (!Array.isArray(value)) throw new Error();
      set("pathMappings", value);
      setMappingValid(true);
      setError("");
    } catch {
      setMappingValid(false);
      setError("Path mappings must be a JSON array.");
    }
  } })))), /* @__PURE__ */ React.createElement("section", { className: "pmv-panel" }, /* @__PURE__ */ React.createElement("div", { className: "pmv-section-heading" }, /* @__PURE__ */ React.createElement("h4", null, "Folders"), /* @__PURE__ */ React.createElement("p", null, "Output stays inside a Cove video library. Music and project files can live elsewhere.")), /* @__PURE__ */ React.createElement("div", { className: "pmv-grid" }, /* @__PURE__ */ React.createElement(FolderSetting, { label: "Output folder", help: "Where finished MP4 files are saved. Choose a Cove video library folder so Cove can scan the result.", value: settings.outputFolder, onBrowse: () => setBrowsing("outputFolder") }), /* @__PURE__ */ React.createElement(FolderSetting, { label: "Configured music folder (optional)", help: "Choose the folder containing your backing songs. Its subfolders appear in Create PMV. You can also upload a song in that popup without configuring this folder.", value: settings.musicFolder, onBrowse: () => setBrowsing("musicFolder"), onClear: () => set("musicFolder", ""), optional: true })), browsing && browsing !== "projectFolder" && /* @__PURE__ */ React.createElement(FolderPicker, { kind: browsing, current: settings[browsing], onChoose: chooseFolder, onClose: () => setBrowsing(null) }), /* @__PURE__ */ React.createElement("details", null, /* @__PURE__ */ React.createElement("summary", null, "Advanced settings"), /* @__PURE__ */ React.createElement("div", { className: "pmv-grid" }, /* @__PURE__ */ React.createElement(FolderSetting, { label: "Project folder (optional)", help: "Where exported Resolve .drp files go when Save project is enabled. Leave blank to save beside the MP4.", value: settings.projectFolder, onBrowse: () => setBrowsing("projectFolder"), onClear: () => set("projectFolder", ""), optional: true })), browsing === "projectFolder" && /* @__PURE__ */ React.createElement(FolderPicker, { kind: browsing, current: settings.projectFolder, onChoose: chooseFolder, onClose: () => setBrowsing(null) }))), /* @__PURE__ */ React.createElement("section", { className: "pmv-panel" }, /* @__PURE__ */ React.createElement("div", { className: "pmv-section-heading" }, /* @__PURE__ */ React.createElement("h4", null, "Job defaults"), /* @__PURE__ */ React.createElement("p", null, "These choices appear in each Create PMV popup and can be changed per job.")), /* @__PURE__ */ React.createElement("div", { className: "pmv-grid" }, /* @__PURE__ */ React.createElement(Control, { label: "Default backing audio source", help: "Choose the audio source shown when Create PMV opens." }, (id) => /* @__PURE__ */ React.createElement("select", { id, value: settings.defaultAudioKind || "cove", onChange: (e) => set("defaultAudioKind", e.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "cove" }, "Cove audio"), /* @__PURE__ */ React.createElement("option", { value: "folder" }, "Configured music folder"), /* @__PURE__ */ React.createElement("option", { value: "upload" }, "Choose song file"), /* @__PURE__ */ React.createElement("option", { value: "youtube" }, "YouTube URL"), /* @__PURE__ */ React.createElement("option", { value: "video" }, "Cove video audio"))), /* @__PURE__ */ React.createElement(Control, { label: "Default face performer gender", help: "Prefilters the performers offered for face matching. This uses Cove metadata and does not guess gender from appearance." }, (id) => /* @__PURE__ */ React.createElement("select", { id, value: settings.defaultFaceGender || "female", onChange: (e) => set("defaultFaceGender", e.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "female" }, "Female"), /* @__PURE__ */ React.createElement("option", { value: "male" }, "Male"), /* @__PURE__ */ React.createElement("option", { value: "trans" }, "Trans performers"), /* @__PURE__ */ React.createElement("option", { value: "all" }, "All performers")))), /* @__PURE__ */ React.createElement(OptionForm, { options: defaults, setOptions: (value) => set("defaults", typeof value === "function" ? value(defaults) : value) }), /* @__PURE__ */ React.createElement(SegmentTagPicker, { ids: defaults.segmentTagIds, onChange: (ids) => set("defaults", { ...defaults, segmentTagIds: ids }) })), /* @__PURE__ */ React.createElement("div", { className: "pmv-settings-footer" }, /* @__PURE__ */ React.createElement("button", { className: "pmv-button-primary", disabled: !automatic && !mappingValid, onClick: async () => {
    try {
      setSettings(await api("/settings", "PUT", settings));
      if (automatic) setLocal(await api("/local-companion"));
      setMessage("Settings saved.");
      setError("");
    } catch (e) {
      setError(e.message);
    }
  } }, "Save settings"))), error && /* @__PURE__ */ React.createElement("p", { role: "alert" }, error), message && /* @__PURE__ */ React.createElement("p", { role: "status" }, message));
}
function TrackRow({ name, selected, playing, onSelect, onPreview, depth = 0 }) {
  return /* @__PURE__ */ React.createElement("div", { className: `pmv-track-row ${selected ? "is-selected" : ""}`, style: { paddingLeft: 8 + depth * 18 } }, /* @__PURE__ */ React.createElement("button", { type: "button", className: "pmv-track-select", onClick: onSelect, title: name, "aria-pressed": selected }, "\u266B ", /* @__PURE__ */ React.createElement("span", null, name)), /* @__PURE__ */ React.createElement("button", { type: "button", className: "pmv-track-play", onClick: onPreview, title: `${playing ? "Pause" : "Play"} ${name}`, "aria-label": `${playing ? "Pause" : "Play"} ${name}` }, playing ? "\u2161" : "\u25B6"));
}
function MusicNode({ item, depth, selectedPath, playingUrl, onSelect, onPreview }) {
  const [open, setOpen] = useState(false);
  const [children, setChildren] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open || children !== null) return;
    let active = true;
    api(`/music?path=${encodeURIComponent(item.path)}`).then((rows) => {
      if (active) setChildren(rows);
    }).catch((e) => {
      if (active) setError(e.message);
    });
    return () => {
      active = false;
    };
  }, [open, item.path, children]);
  if (item.kind === "file") {
    const url = `/api/ext/pmv/music-preview?path=${encodeURIComponent(item.path)}`;
    return /* @__PURE__ */ React.createElement(
      TrackRow,
      {
        name: item.name,
        depth,
        selected: selectedPath === item.path,
        playing: playingUrl === url,
        onSelect: () => onSelect(item.path),
        onPreview: () => onPreview(url)
      }
    );
  }
  return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "pmv-music-folder", style: { paddingLeft: 8 + depth * 18 } }, /* @__PURE__ */ React.createElement("button", { type: "button", onClick: () => setOpen((value) => !value), "aria-expanded": open, title: item.path }, /* @__PURE__ */ React.createElement("span", { className: `pmv-chevron ${open ? "is-open" : ""}` }), " ", /* @__PURE__ */ React.createElement("span", null, "\u25B8"), " ", item.name)), open && (error ? /* @__PURE__ */ React.createElement("p", { role: "alert", className: "pmv-tree-hint" }, error) : children === null ? /* @__PURE__ */ React.createElement("small", { className: "pmv-tree-hint" }, "Loading tracks\u2026") : children.length ? children.map((child) => /* @__PURE__ */ React.createElement(
    MusicNode,
    {
      key: child.path,
      item: child,
      depth: depth + 1,
      selectedPath,
      playingUrl,
      onSelect,
      onPreview
    }
  )) : /* @__PURE__ */ React.createElement("small", { className: "pmv-tree-empty" }, "Empty folder")));
}
function MusicTree({ selectedPath, playingUrl, onSelect, onPreview }) {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api("/music").then((rows) => {
      if (active) setItems(rows);
    }).catch((e) => {
      if (active) setError(e.message);
    });
    return () => {
      active = false;
    };
  }, []);
  return /* @__PURE__ */ React.createElement("div", { className: "pmv-track-browser" }, /* @__PURE__ */ React.createElement("div", { className: "pmv-track-browser-head" }, /* @__PURE__ */ React.createElement("strong", null, "Configured music folder"), /* @__PURE__ */ React.createElement("small", null, "Choose a song; use Play to listen first.")), /* @__PURE__ */ React.createElement("div", { className: "pmv-track-list", role: "region", "aria-label": "Music folder tracks" }, error ? /* @__PURE__ */ React.createElement("p", { role: "alert", className: "pmv-tree-hint" }, error) : items === null ? /* @__PURE__ */ React.createElement("p", { className: "pmv-tree-hint" }, "Loading music folder\u2026") : items.length ? items.map((item) => /* @__PURE__ */ React.createElement(
    MusicNode,
    {
      key: item.path,
      item,
      depth: 0,
      selectedPath,
      playingUrl,
      onSelect,
      onPreview
    }
  )) : /* @__PURE__ */ React.createElement("p", { className: "pmv-tree-hint" }, "No songs in this folder.")));
}
function PmvDialog({ context, close }) {
  const [settings, , settingsError] = useSettings("/defaults");
  const [options, setOptions] = useState(defaultOptions);
  const [audio, setAudio] = useState({ kind: "cove" });
  const [faceIds, setFaceIds] = useState([]);
  const [faceGender, setFaceGender] = useState("female");
  const [faceQuery, setFaceQuery] = useState("");
  const [faceSearch, setFaceSearch] = useState([]);
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
  const uploadGeneration = useRef(0);
  useEffect(() => {
    if (settings) {
      const kind = settings.defaultAudioKind || "cove";
      setOptions({ ...defaultOptions, ...settings.defaults });
      setAudio(kind === "video" && context.entityType === "video" && (context.entityIds || context.selectedIds || []).length === 1 ? { kind, coveVideoId: (context.entityIds || context.selectedIds)[0] } : { kind });
      setFaceGender(settings.defaultFaceGender || "female");
    }
  }, [settings]);
  const genderFits = (person, gender) => gender === "all" || gender === "female" && (person.gender === 1 || person.gender === "female") || gender === "male" && (person.gender === 0 || person.gender === "male") || gender === "trans" && [2, 3, "transgenderMale", "transgenderFemale"].includes(person.gender);
  useEffect(() => {
    if (initializedFaces.current || !preview?.performers || !settings) return;
    initializedFaces.current = true;
    const initial = preview.performers.filter((person) => person.hasReference && genderFits(person, settings.defaultFaceGender || "female")).map((person) => person.id);
    const scoped = context.entityType === "performer" ? (context.entityIds || context.selectedIds || []).filter((id) => preview.performers.some((p) => p.id === id && p.hasReference)) : [];
    setFaceIds([.../* @__PURE__ */ new Set([...scoped, ...initial])]);
  }, [preview?.performers, settings]);
  useEffect(() => {
    if (faceQuery.trim().length < 2) return;
    let active = true;
    const timer = window.setTimeout(() => api("/performers?q=" + encodeURIComponent(faceQuery.trim())).then((rows) => {
      if (active) setFaceSearch((current) => [...new Map([...current, ...rows].map((person) => [person.id, person])).values()]);
    }).catch((e) => {
      if (active) setError(e.message);
    }), 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [faceQuery]);
  useEffect(() => {
    if (audio.kind !== "cove") return;
    let active = true;
    setAudioLoading(true);
    setAudioError("");
    const timer = window.setTimeout(() => api("/audio?q=" + encodeURIComponent(query)).then((rows) => {
      if (active) setAudioItems(rows);
    }).catch((e) => {
      if (active) {
        setAudioItems([]);
        setAudioError(e.message.includes("403") ? "Cove denied audio access. Your account needs Audios read permission." : e.message);
      }
    }).finally(() => {
      if (active) setAudioLoading(false);
    }), 250);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [audio.kind, query]);
  useEffect(() => {
    if (audio.kind === "video") api("/videos?q=" + encodeURIComponent(videoQuery)).then(setVideoItems).catch((e) => setError(e.message));
  }, [audio.kind, videoQuery]);
  const scope = {
    entityType: context.entityType,
    entityIds: context.entityIds || context.selectedIds,
    includeChildStudios: !!context.includeChildStudios,
    videoFilter: context.videoFilter || null,
    videoFilterExpression: context.videoFilterExpression || null,
    findQuery: context.findQuery || null
  };
  const request = { scope, audio, options, facePerformerIds: faceIds };
  const audioReady = audio.kind === "cove" ? Number(audio.coveAudioId) > 0 : audio.kind === "folder" ? !!audio.path : audio.kind === "upload" ? !!audio.uploadId : audio.kind === "video" ? Number(audio.coveVideoId) > 0 : audio.kind === "youtube" && /^https:\/\//i.test(audio.url || "");
  const removeUpload = (uploadId) => {
    if (uploadId) api(`/uploads/${uploadId}`, "DELETE").catch(() => {
    });
  };
  const playPreview = (url) => {
    const player = audioPlayer.current;
    if (!player) return;
    if (playingUrl === url && !player.paused) {
      player.pause();
      setPlayingUrl("");
      return;
    }
    if (previewUrl !== url) {
      player.src = url;
      setPreviewUrl(url);
    }
    setError("");
    player.play().then(() => setPlayingUrl(url)).catch(() => setError("Could not play this track in the browser."));
  };
  const changeAudioKind = (kind) => {
    uploadGeneration.current += 1;
    removeUpload(audio.uploadId);
    setSelectedAudioName("");
    audioPlayer.current?.pause();
    setPreviewUrl("");
    setPlayingUrl("");
    setUploading(false);
    setAudio(kind === "video" && context.entityType === "video" && scope.entityIds.length === 1 ? { kind, coveVideoId: scope.entityIds[0] } : { kind });
  };
  const chooseSong = async (file) => {
    if (!file) return;
    const generation = ++uploadGeneration.current;
    removeUpload(audio.uploadId);
    setAudio({ kind: "upload" });
    setUploading(true);
    setError("");
    try {
      const uploadId = await uploadSongFile(file);
      if (generation !== uploadGeneration.current) {
        removeUpload(uploadId);
        return;
      }
      setAudio({ kind: "upload", uploadId, name: file.name });
    } catch (e) {
      if (generation === uploadGeneration.current) setError(e.message);
    } finally {
      if (generation === uploadGeneration.current) setUploading(false);
    }
  };
  const cancel = () => {
    uploadGeneration.current += 1;
    removeUpload(audio.uploadId);
    audioPlayer.current?.pause();
    close();
  };
  useEffect(() => {
    let active = true;
    const timer = window.setTimeout(() => api("/preview", "POST", request).then((result) => {
      if (active) setPreview(result);
    }).catch((e) => {
      if (active) setError(e.message);
    }), 150);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [JSON.stringify(scope), JSON.stringify(options)]);
  const create = async () => {
    if (!audioReady) {
      setError("Choose a backing track before creating the PMV.");
      return;
    }
    if (needsFaceReferences(options) && !faceIds.length) {
      setError("Choose at least one performer with a reference image, or turn off performer matching.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api("/create", "POST", request);
      audioPlayer.current?.pause();
      close();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return /* @__PURE__ */ React.createElement("div", { className: "pmv-overlay", role: "dialog", "aria-modal": "true", "aria-label": "Create PMV" }, /* @__PURE__ */ React.createElement("div", { className: "pmv-dialog" }, /* @__PURE__ */ React.createElement("header", null, /* @__PURE__ */ React.createElement("h2", null, "Create PMV"), /* @__PURE__ */ React.createElement("button", { onClick: cancel, "aria-label": "Close" }, "\xD7")), /* @__PURE__ */ React.createElement("p", null, preview ? `${preview.eligibleCount} eligible sources \xB7 ${preview.proposedFilename}` : "Checking sources\u2026"), preview?.eligibilityNote && /* @__PURE__ */ React.createElement("p", { role: "alert" }, preview.eligibilityNote), !!preview?.exclusions?.length && /* @__PURE__ */ React.createElement("details", null, /* @__PURE__ */ React.createElement("summary", null, preview.exclusions.length, " excluded sources"), /* @__PURE__ */ React.createElement("ul", null, preview.exclusions.map((x, i) => /* @__PURE__ */ React.createElement("li", { key: i }, x)))), needsFaceReferences(options) && /* @__PURE__ */ React.createElement("fieldset", { className: "pmv-face-picker" }, /* @__PURE__ */ React.createElement("legend", null, "Faces to follow"), /* @__PURE__ */ React.createElement("p", null, "Only confident matches to selected Cove performers are used. Matching also searches videos without performer tags."), /* @__PURE__ */ React.createElement("div", { className: "pmv-grid" }, /* @__PURE__ */ React.createElement(Control, { label: "Select by gender", help: "Uses performer metadata, not a gender classifier." }, (id) => /* @__PURE__ */ React.createElement("select", { id, value: faceGender, onChange: (e) => setFaceGender(e.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "female" }, "Female"), /* @__PURE__ */ React.createElement("option", { value: "male" }, "Male"), /* @__PURE__ */ React.createElement("option", { value: "trans" }, "Trans performers"), /* @__PURE__ */ React.createElement("option", { value: "all" }, "All performers"))), /* @__PURE__ */ React.createElement(Control, { label: "Search all Cove performers", help: "Add a performer even if the selected videos are not tagged with them." }, (id) => /* @__PURE__ */ React.createElement("input", { id, value: faceQuery, onChange: (e) => setFaceQuery(e.target.value), placeholder: "Search by name" }))), /* @__PURE__ */ React.createElement("div", { className: "pmv-face-actions" }, /* @__PURE__ */ React.createElement("button", { type: "button", onClick: () => setFaceIds([.../* @__PURE__ */ new Set([...faceIds || [], ...(preview?.performers || []).filter((p) => p.hasReference && genderFits(p, faceGender)).map((p) => p.id)])]) }, "Select matching"), /* @__PURE__ */ React.createElement("button", { type: "button", onClick: () => setFaceIds([]) }, "Deselect all"), /* @__PURE__ */ React.createElement("small", null, faceIds.length, " selected")), /* @__PURE__ */ React.createElement("div", { className: "pmv-face-list" }, [...preview?.performers || [], ...faceSearch.filter((p) => !(preview?.performers || []).some((x) => x.id === p.id))].filter((person) => genderFits(person, faceGender) || faceIds.includes(person.id)).map((person) => /* @__PURE__ */ React.createElement("button", { type: "button", key: person.id, className: faceIds.includes(person.id) ? "selected" : "", disabled: !person.hasReference, onClick: () => setFaceIds((current) => current.includes(person.id) ? current.filter((id) => id !== person.id) : [...current, person.id]), "aria-pressed": faceIds.includes(person.id) }, person.name, !person.hasReference ? " \xB7 no reference image" : "")))), /* @__PURE__ */ React.createElement(SegmentTagPicker, { ids: options.segmentTagIds, onChange: (ids) => setOptions((current) => ({ ...current, segmentTagIds: ids })) }), /* @__PURE__ */ React.createElement("fieldset", null, /* @__PURE__ */ React.createElement("legend", null, "Backing audio"), /* @__PURE__ */ React.createElement("div", { className: "pmv-grid" }, /* @__PURE__ */ React.createElement(Control, { label: "Source", help: "Choose a backing song from Cove, the configured music folder, a local song file, YouTube, or a Cove video's audio." }, (id) => /* @__PURE__ */ React.createElement("select", { id, value: audio.kind, onChange: (e) => changeAudioKind(e.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "cove" }, "Cove audio"), /* @__PURE__ */ React.createElement("option", { value: "folder" }, "Configured music folder"), /* @__PURE__ */ React.createElement("option", { value: "upload" }, "Choose song file"), /* @__PURE__ */ React.createElement("option", { value: "youtube" }, "YouTube URL"), /* @__PURE__ */ React.createElement("option", { value: "video" }, "Cove video audio"))), audio.kind === "upload" && /* @__PURE__ */ React.createElement(Control, { label: "Song file", help: "Upload an audio file directly from your computer. The companion stores it temporarily and removes it after the PMV job." }, (id) => /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("input", { id, type: "file", accept: ".mp3,.wav,.flac,.m4a,.aac,.ogg,.opus,.aiff,audio/*", onChange: (e) => chooseSong(e.target.files?.[0]) }), /* @__PURE__ */ React.createElement("small", null, uploading ? "Uploading song\u2026" : audio.uploadId ? `${audio.name} ready` : "Choose an audio file up to 200 MB."))), audio.kind === "cove" && /* @__PURE__ */ React.createElement("div", { className: "pmv-track-browser pmv-grid-span" }, /* @__PURE__ */ React.createElement(Control, { label: "Search Cove audio", help: "Search Cove's audio library. Select a result below to use it as the backing song." }, (id) => /* @__PURE__ */ React.createElement("input", { id, value: query, onChange: (e) => setQuery(e.target.value), placeholder: "Search by title" })), /* @__PURE__ */ React.createElement("div", { className: "pmv-track-list", role: "region", "aria-label": "Cove audio search results" }, audioError ? /* @__PURE__ */ React.createElement("p", { role: "alert", className: "pmv-tree-hint" }, audioError) : audioLoading ? /* @__PURE__ */ React.createElement("p", { className: "pmv-tree-hint" }, "Searching\u2026") : audioItems.length ? audioItems.map((x) => {
    const url = `/api/audios/${x.id}/stream`;
    return /* @__PURE__ */ React.createElement(
      TrackRow,
      {
        key: x.id,
        name: x.title || x.minPath || `Audio ${x.id}`,
        selected: audio.coveAudioId === x.id,
        playing: playingUrl === url,
        onSelect: () => {
          setAudio({ kind: "cove", coveAudioId: x.id });
          setSelectedAudioName(x.title || x.minPath || `Audio ${x.id}`);
        },
        onPreview: () => playPreview(url)
      }
    );
  }) : /* @__PURE__ */ React.createElement("p", { className: "pmv-tree-hint" }, "No matching audio tracks.")), audio.coveAudioId && /* @__PURE__ */ React.createElement("small", { className: "pmv-selected-track" }, "Selected: ", selectedAudioName || `Audio ${audio.coveAudioId}`)), audio.kind === "folder" && /* @__PURE__ */ React.createElement("div", { className: "pmv-grid-span" }, /* @__PURE__ */ React.createElement(
    MusicTree,
    {
      selectedPath: audio.path,
      playingUrl,
      onSelect: (path) => setAudio({ kind: "folder", path }),
      onPreview: playPreview
    }
  ), audio.path && /* @__PURE__ */ React.createElement("small", { className: "pmv-selected-track" }, "Selected: ", audio.path)), audio.kind === "youtube" && /* @__PURE__ */ React.createElement(Control, { label: "YouTube URL", help: "Paste an HTTPS YouTube video URL. The companion downloads only its audio for the PMV." }, (id) => /* @__PURE__ */ React.createElement("input", { id, type: "url", value: audio.url || "", onChange: (e) => setAudio({ kind: "youtube", url: e.target.value }) })), audio.kind === "video" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(Control, { label: "Search Cove videos", help: "Filter Cove videos by title to find the source of your backing audio." }, (id) => /* @__PURE__ */ React.createElement("input", { id, value: videoQuery, onChange: (e) => setVideoQuery(e.target.value) })), /* @__PURE__ */ React.createElement(Control, { label: "Video", help: "Extracts this Cove video's audio as the backing song." }, (id) => /* @__PURE__ */ React.createElement("select", { id, value: audio.coveVideoId || "", onChange: (e) => setAudio({ kind: "video", coveVideoId: Number(e.target.value) }) }, /* @__PURE__ */ React.createElement("option", { value: "" }, "Choose video"), videoItems.map((x) => /* @__PURE__ */ React.createElement("option", { key: x.id, value: x.id }, x.title || x.minPath || `Video ${x.id}`)))))), !audioReady && /* @__PURE__ */ React.createElement("small", { className: "pmv-audio-hint" }, "Choose a backing track to enable Create."), /* @__PURE__ */ React.createElement(
    "audio",
    {
      ref: audioPlayer,
      className: "pmv-audio-preview",
      controls: true,
      style: { display: previewUrl ? "block" : "none" },
      onEnded: () => setPlayingUrl(""),
      onPause: () => setPlayingUrl(""),
      onError: () => {
        setPlayingUrl("");
        setError("Could not play this track. Check that Cove can read it and your account can stream audio.");
      }
    }
  )), /* @__PURE__ */ React.createElement(OptionForm, { options, setOptions }), (error || settingsError) && /* @__PURE__ */ React.createElement("p", { role: "alert" }, error || settingsError), /* @__PURE__ */ React.createElement("footer", null, /* @__PURE__ */ React.createElement(HelpAction, { label: "Cancel", help: "Closes this popup without queueing a PMV." }, /* @__PURE__ */ React.createElement("button", { onClick: cancel }, "Cancel")), /* @__PURE__ */ React.createElement(HelpAction, { label: "Create", help: "Starts a PMV job with the current source selection, backing audio, and edit controls." }, /* @__PURE__ */ React.createElement("button", { disabled: busy || uploading || !audioReady || !preview?.canCreate, onClick: create }, busy ? "Queueing\u2026" : "Create")))));
}
function PmvLauncher() {
  const [context, setContext] = useState(null);
  useEffect(() => {
    const open = (e) => setContext(e.detail);
    window.addEventListener("pmvmaker:open", open);
    return () => window.removeEventListener("pmvmaker:open", open);
  }, []);
  return context ? /* @__PURE__ */ React.createElement(PmvDialog, { context, close: () => setContext(null) }) : null;
}
var index_default = { components: { PmvLauncher, PmvSettingsPanel }, actionHandlers: { openPmv } };
export {
  PmvLauncher,
  PmvSettingsPanel,
  index_default as default,
  openPmv
};
