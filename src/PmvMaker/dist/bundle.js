// src/index.jsx
import React from "@cove/runtime/react";
var { useEffect, useState } = React;
var base = "/api/ext/pmv";
async function api(path, method = "GET", body) {
  const response = await fetch(base + path, {
    method,
    credentials: "same-origin",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : void 0
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.message || result.error || `Request failed (${response.status})`);
  return result;
}
function openPmv(_action, payload) {
  window.dispatchEvent(new CustomEvent("pmvmaker:open", { detail: payload }));
  return { cancelled: true };
}
var styleHelp = {
  "rhythmic-polish": "Precise cuts, restrained accents, and matched color.",
  "high-energy": "Faster cuts, stronger motion, and controlled accents.",
  cinematic: "Longer shots, softer pacing, and cohesive color."
};
var stylePresets = {
  "rhythmic-polish": { motionIntensity: 0.25, transitionIntensity: 0.25, flashIntensity: 0, glitchIntensity: 0, colorTreatment: "matched" },
  "high-energy": { motionIntensity: 0.7, transitionIntensity: 0.3, flashIntensity: 0.35, glitchIntensity: 0.25, colorTreatment: "matched" },
  cinematic: { motionIntensity: 0.2, transitionIntensity: 0.5, flashIntensity: 0, glitchIntensity: 0, colorTreatment: "warm" }
};
var defaultOptions = {
  layout: "three-pane",
  style: "rhythmic-polish",
  sourceAudio: "mixed",
  pacing: 0.5,
  beatAdherence: 0.8,
  minClipSeconds: 1,
  maxClipSeconds: 5,
  sourceDiversity: 0.8,
  transitionFamilies: ["cut", "dissolve"],
  transitionIntensity: 0.25,
  motionIntensity: 0.25,
  flashIntensity: 0,
  glitchIntensity: 0,
  colorTreatment: "matched",
  songTrimStart: null,
  songTrimEnd: null,
  outputWidth: null,
  outputHeight: null,
  outputFps: null,
  saveProject: false,
  scanToCove: true,
  keepPerformers: true,
  keepTags: true,
  addPmvTag: true
};
function OptionForm({ options, setOptions }) {
  const set = (key, value) => setOptions((current) => ({ ...current, [key]: value }));
  return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "pmv-grid" }, /* @__PURE__ */ React.createElement("label", null, "Layout", /* @__PURE__ */ React.createElement("select", { value: options.layout, onChange: (e) => set("layout", e.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "three-pane" }, "Three panes \xB7 9:16"), /* @__PURE__ */ React.createElement("option", { value: "full-screen" }, "Full screen \xB7 16:9"))), /* @__PURE__ */ React.createElement("label", null, "Style", /* @__PURE__ */ React.createElement("select", { value: options.style, onChange: (e) => setOptions((current) => ({ ...current, style: e.target.value, ...stylePresets[e.target.value] })) }, Object.keys(styleHelp).map((x) => /* @__PURE__ */ React.createElement("option", { key: x, value: x }, x.replaceAll("-", " ")))), /* @__PURE__ */ React.createElement("small", null, styleHelp[options.style])), /* @__PURE__ */ React.createElement("label", null, "Source audio", /* @__PURE__ */ React.createElement("select", { value: options.sourceAudio, onChange: (e) => set("sourceAudio", e.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "muted" }, "Muted"), /* @__PURE__ */ React.createElement("option", { value: "mixed" }, "Mixed \xB7 brief accents"), /* @__PURE__ */ React.createElement("option", { value: "all" }, "All source audio")))), /* @__PURE__ */ React.createElement("details", null, /* @__PURE__ */ React.createElement("summary", null, "Advanced edit controls"), /* @__PURE__ */ React.createElement("div", { className: "pmv-grid" }, [["pacing", "Pacing"], ["beatAdherence", "Beat adherence"], ["sourceDiversity", "Source diversity"], ["transitionIntensity", "Transition intensity"], ["motionIntensity", "Motion"], ["flashIntensity", "Flash"], ["glitchIntensity", "Glitch"]].map(([key, label]) => /* @__PURE__ */ React.createElement("label", { key }, label, /* @__PURE__ */ React.createElement("input", { type: "range", min: "0", max: "1", step: "0.05", value: options[key], onChange: (e) => set(key, Number(e.target.value)) }), /* @__PURE__ */ React.createElement("output", null, Number(options[key]).toFixed(2)))), [["minClipSeconds", "Minimum clip (sec)"], ["maxClipSeconds", "Maximum clip (sec)"], ["songTrimStart", "Song start (sec)"], ["songTrimEnd", "Song end (sec)"], ["outputWidth", "Width override"], ["outputHeight", "Height override"], ["outputFps", "FPS override"]].map(([key, label]) => /* @__PURE__ */ React.createElement("label", { key }, label, /* @__PURE__ */ React.createElement("input", { type: "number", min: "0", step: "any", value: options[key] ?? "", onChange: (e) => set(key, e.target.value === "" ? null : Number(e.target.value)) }))), /* @__PURE__ */ React.createElement("label", null, "Transitions", /* @__PURE__ */ React.createElement("select", { value: options.transitionFamilies?.join(",") || "cut", onChange: (e) => set("transitionFamilies", e.target.value.split(",")) }, /* @__PURE__ */ React.createElement("option", { value: "cut" }, "Cuts"), /* @__PURE__ */ React.createElement("option", { value: "cut,dissolve" }, "Cuts and dissolves"))), /* @__PURE__ */ React.createElement("label", null, "Color treatment", /* @__PURE__ */ React.createElement("select", { value: options.colorTreatment, onChange: (e) => set("colorTreatment", e.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "matched" }, "Matched"), /* @__PURE__ */ React.createElement("option", { value: "warm" }, "Warm"), /* @__PURE__ */ React.createElement("option", { value: "cool" }, "Cool"), /* @__PURE__ */ React.createElement("option", { value: "natural" }, "Natural"))), [["saveProject", "Save project (.drp)"], ["scanToCove", "Scan to Cove"], ["keepPerformers", "Keep performers"], ["keepTags", "Keep used segment tags"], ["addPmvTag", "Add PMV tag"]].map(([key, label]) => /* @__PURE__ */ React.createElement("label", { className: "pmv-check", key }, /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: !!options[key], onChange: (e) => set(key, e.target.checked) }), label)))));
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
  const [mappingText, setMappingText] = useState("[]");
  const [mappingValid, setMappingValid] = useState(true);
  useEffect(() => {
    if (settings) setMappingText(JSON.stringify(settings.pathMappings || [], null, 2));
  }, [!!settings]);
  if (!settings) return /* @__PURE__ */ React.createElement("div", { className: "pmv-settings" }, error || "Loading PMV settings\u2026");
  const set = (key, value) => setSettings((current) => ({ ...current, [key]: value }));
  const defaults = { ...defaultOptions, ...settings.defaults };
  return /* @__PURE__ */ React.createElement("div", { className: "pmv-settings" }, /* @__PURE__ */ React.createElement("h3", null, "Auto PMV Maker"), /* @__PURE__ */ React.createElement("p", null, "Run the companion in the signed-in Windows session where Resolve Studio is open."), /* @__PURE__ */ React.createElement("div", { className: "pmv-grid" }, [["companionUrl", "Companion URL"], ["companionToken", "Companion token"], ["outputFolder", "Output folder"], ["projectFolder", "Project folder (optional)"], ["musicFolder", "Music folder"]].map(([key, label]) => /* @__PURE__ */ React.createElement("label", { key }, label, /* @__PURE__ */ React.createElement("input", { type: key === "companionToken" ? "password" : "text", value: settings[key] || "", onChange: (e) => set(key, e.target.value) })))), settings.companionConfigured && /* @__PURE__ */ React.createElement("small", null, "A companion token is saved. Leave the field blank to keep it."), /* @__PURE__ */ React.createElement("label", null, "Container \u2192 Windows path mappings (JSON)", /* @__PURE__ */ React.createElement("textarea", { rows: "4", value: mappingText, onChange: (e) => {
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
  } })), /* @__PURE__ */ React.createElement("h4", null, "Job defaults"), /* @__PURE__ */ React.createElement(OptionForm, { options: defaults, setOptions: (value) => set("defaults", typeof value === "function" ? value(defaults) : value) }), /* @__PURE__ */ React.createElement("div", { className: "pmv-actions" }, /* @__PURE__ */ React.createElement("button", { onClick: async () => {
    try {
      setHealth(await api("/health"));
    } catch (e) {
      setError(e.message);
    }
  } }, "Check Resolve"), /* @__PURE__ */ React.createElement("button", { disabled: !mappingValid, onClick: async () => {
    try {
      setSettings(await api("/settings", "PUT", settings));
      setMessage("Settings saved.");
      setError("");
    } catch (e) {
      setError(e.message);
    }
  } }, "Save settings")), health && /* @__PURE__ */ React.createElement("p", { role: "status" }, health.ok ? `${health.product} ${health.version} ready` : health.error), error && /* @__PURE__ */ React.createElement("p", { role: "alert" }, error), message && /* @__PURE__ */ React.createElement("p", { role: "status" }, message));
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
  useEffect(() => {
    if (settings) setOptions({ ...defaultOptions, ...settings.defaults });
  }, [settings]);
  useEffect(() => {
    if (audio.kind === "cove") api("/audio?q=" + encodeURIComponent(query)).then(setAudioItems).catch((e) => setError(e.message));
  }, [audio.kind, query]);
  useEffect(() => {
    if (audio.kind === "video") api("/videos?q=" + encodeURIComponent(videoQuery)).then(setVideoItems).catch((e) => setError(e.message));
  }, [audio.kind, videoQuery]);
  useEffect(() => {
    if (audio.kind === "folder") api("/music?path=" + encodeURIComponent(folderPath)).then(setFolderItems).catch((e) => setError(e.message));
  }, [audio.kind, folderPath]);
  const scope = {
    entityType: context.entityType,
    entityIds: context.entityIds || context.selectedIds,
    includeChildStudios: !!context.includeChildStudios,
    videoFilter: context.videoFilter || null,
    videoFilterExpression: context.videoFilterExpression || null,
    findQuery: context.findQuery || null
  };
  const request = { scope, audio, options };
  useEffect(() => {
    api("/preview", "POST", request).then(setPreview).catch((e) => setError(e.message));
  }, [JSON.stringify(scope)]);
  const create = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api("/create", "POST", request);
      window.alert(`PMV queued. Job: ${result.jobId}`);
      close();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return /* @__PURE__ */ React.createElement("div", { className: "pmv-overlay", role: "dialog", "aria-modal": "true", "aria-label": "Create PMV" }, /* @__PURE__ */ React.createElement("div", { className: "pmv-dialog" }, /* @__PURE__ */ React.createElement("header", null, /* @__PURE__ */ React.createElement("h2", null, "Create PMV"), /* @__PURE__ */ React.createElement("button", { onClick: close, "aria-label": "Close" }, "\xD7")), /* @__PURE__ */ React.createElement("p", null, preview ? `${preview.eligibleCount} eligible sources \xB7 ${preview.proposedFilename}` : "Checking sources\u2026"), !!preview?.exclusions?.length && /* @__PURE__ */ React.createElement("details", null, /* @__PURE__ */ React.createElement("summary", null, preview.exclusions.length, " excluded sources"), /* @__PURE__ */ React.createElement("ul", null, preview.exclusions.map((x, i) => /* @__PURE__ */ React.createElement("li", { key: i }, x)))), /* @__PURE__ */ React.createElement("fieldset", null, /* @__PURE__ */ React.createElement("legend", null, "Backing audio"), /* @__PURE__ */ React.createElement("div", { className: "pmv-grid" }, /* @__PURE__ */ React.createElement("label", null, "Source", /* @__PURE__ */ React.createElement("select", { value: audio.kind, onChange: (e) => setAudio(e.target.value === "video" && context.entityType === "video" && scope.entityIds.length === 1 ? { kind: "video", coveVideoId: scope.entityIds[0] } : { kind: e.target.value }) }, /* @__PURE__ */ React.createElement("option", { value: "cove" }, "Cove audio"), /* @__PURE__ */ React.createElement("option", { value: "folder" }, "Music folder"), /* @__PURE__ */ React.createElement("option", { value: "youtube" }, "YouTube URL"), /* @__PURE__ */ React.createElement("option", { value: "video" }, "Cove video audio"))), audio.kind === "cove" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("label", null, "Search", /* @__PURE__ */ React.createElement("input", { value: query, onChange: (e) => setQuery(e.target.value) })), /* @__PURE__ */ React.createElement("label", null, "Track", /* @__PURE__ */ React.createElement("select", { value: audio.coveAudioId || "", onChange: (e) => setAudio({ kind: "cove", coveAudioId: Number(e.target.value) }) }, /* @__PURE__ */ React.createElement("option", { value: "" }, "Choose track"), audioItems.map((x) => /* @__PURE__ */ React.createElement("option", { value: x.id, key: x.id }, x.title || x.minPath))))), audio.kind === "folder" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("label", null, "Folder", /* @__PURE__ */ React.createElement("input", { value: folderPath, onChange: (e) => setFolderPath(e.target.value) })), /* @__PURE__ */ React.createElement("div", null, folderItems.map((x) => /* @__PURE__ */ React.createElement("button", { key: x.path, onClick: () => x.kind === "folder" ? setFolderPath(x.path) : setAudio({ kind: "folder", path: x.path }) }, x.kind === "folder" ? "\u{1F4C1}" : "\u266B", " ", x.name))), /* @__PURE__ */ React.createElement("p", null, audio.path || "Choose a file")), audio.kind === "youtube" && /* @__PURE__ */ React.createElement("label", null, "YouTube URL", /* @__PURE__ */ React.createElement("input", { type: "url", value: audio.url || "", onChange: (e) => setAudio({ kind: "youtube", url: e.target.value }) })), audio.kind === "video" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("label", null, "Search Cove videos", /* @__PURE__ */ React.createElement("input", { value: videoQuery, onChange: (e) => setVideoQuery(e.target.value) })), /* @__PURE__ */ React.createElement("label", null, "Video", /* @__PURE__ */ React.createElement("select", { value: audio.coveVideoId || "", onChange: (e) => setAudio({ kind: "video", coveVideoId: Number(e.target.value) }) }, /* @__PURE__ */ React.createElement("option", { value: "" }, "Choose video"), videoItems.map((x) => /* @__PURE__ */ React.createElement("option", { key: x.id, value: x.id }, x.title || x.minPath || `Video ${x.id}`))))))), /* @__PURE__ */ React.createElement(OptionForm, { options, setOptions }), (error || settingsError) && /* @__PURE__ */ React.createElement("p", { role: "alert" }, error || settingsError), /* @__PURE__ */ React.createElement("footer", null, /* @__PURE__ */ React.createElement("button", { onClick: close }, "Cancel"), /* @__PURE__ */ React.createElement("button", { disabled: busy || !preview?.eligibleCount, onClick: create }, busy ? "Queueing\u2026" : "Create"))));
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
