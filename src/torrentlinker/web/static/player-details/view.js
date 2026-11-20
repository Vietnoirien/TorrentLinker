"use strict";
// Details of the playing film under the picture. The host owns playback; this view only
// shows what it publishes and asks it to switch tracks.
const $ = (id) => document.getElementById(id);
let state = {},
  request,
  artworkFor = "";
const say = (en, fr) => (state.language === "fr" ? fr : en);
const scope = () => ({
  client_id: state.client_id,
  media_id: state.media_id,
  source_token: state.source_token,
});

function runtime(seconds) {
  const minutes = Math.round((Number(seconds) || 0) / 60);
  if (!minutes) return "";
  const hours = Math.floor(minutes / 60),
    rest = String(minutes % 60).padStart(2, "0");
  if (!hours) return say(`${minutes} min`, `${minutes} min`);
  return say(`${hours}h ${rest}m`, `${hours} h ${rest}`);
}

function rating(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return "";
  return number.toLocaleString(state.language === "fr" ? "fr-FR" : "en-US", {
    maximumFractionDigits: 1,
  });
}

// What the release name and the scan say about the file: the facts a viewer checks first.
function flags(item) {
  const name = ` ${String(item.release || "").replace(/[._]/g, " ")} `,
    found = [];
  const add = (text, strong = false) => {
    if (text && !found.some(([known]) => known === text))
      found.push([text, strong]);
  };
  const resolution = name.match(/\b(2160|1080|720|576|480)[pi]\b/i);
  if (resolution) add(`${resolution[1]}p`, Number(resolution[1]) >= 1080);
  else if (/\b(4K|UHD)\b/i.test(name)) add("2160p", true);
  if (/\b(DV|DoVi|Dolby ?Vision)\b/i.test(name)) add("Dolby Vision", true);
  if (/\bHDR10\+/i.test(name)) add("HDR10+", true);
  else if (/\bHDR(10)?\b/i.test(name)) add("HDR", true);
  const codec =
    item.codec ||
    (/\b(x265|h ?265|HEVC)\b/i.test(name)
      ? "HEVC"
      : /\b(x264|h ?264|AVC)\b/i.test(name)
        ? "H264"
        : /\bAV1\b/i.test(name)
          ? "AV1"
          : "");
  add(String(codec).toUpperCase());
  const audio = name.match(
    /\b(TrueHD|Atmos|DTS[- ]?HD(?: MA)?|DTS|E-?AC-?3|DDP|DD\+|AC-?3|AAC|FLAC|Opus)(?![a-z])/i,
  );
  const channels = name.match(/(?<!\d)([1-7])[ .]([01])(?!\d)/);
  const format = (value) => {
    const key = value.toLowerCase().replace(/[- ]/g, "");
    if (key.startsWith("dtshd")) return "DTS-HD MA";
    return (
      {
        truehd: "TrueHD",
        atmos: "Atmos",
        eac3: "E-AC-3",
        ddp: "E-AC-3",
        "dd+": "E-AC-3",
        ac3: "AC-3",
        opus: "Opus",
      }[key] || value.toUpperCase()
    );
  };
  if (audio)
    add(
      [
        format(audio[1]),
        channels ? `${channels[1]}.${channels[2]}` : "",
      ]
        .filter(Boolean)
        .join(" "),
    );
  if (/\bMULTI\b/i.test(name)) add("MULTI", true);
  else if (/\bVOSTFR\b/i.test(name)) add("VOSTFR");
  else if (/\b(VFF|VFQ|VFI|TRUEFRENCH|FRENCH)\b/i.test(name)) add("VF");
  return found;
}

function chips(root, rows, kind) {
  const buttons = rows.map((row) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = row.text;
    button.setAttribute("aria-pressed", String(row.selected));
    const source = scope();
    button.onclick = async () => {
      $("error").hidden = true;
      try {
        await request("command", {
          action: "select_track",
          values: { kind, track_id: row.id },
          ...source,
        });
      } catch (error) {
        $("error").textContent = error.message;
        $("error").hidden = false;
      }
    };
    return button;
  });
  root.replaceChildren(...buttons);
}

function trackText(row, index, fallback) {
  return [
    row.label || `${fallback} ${index + 1}`,
    row.language && row.language !== row.label ? row.language : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

async function artwork(item) {
  const key = `${state.client_id}/${state.media_id}`;
  if (artworkFor === key) return;
  artworkFor = key;
  const poster = $("poster");
  poster.classList.remove("has-art");
  poster.querySelector("img")?.remove();
  if (!item.artwork) return;
  try {
    const result = await request("artwork", { media_id: state.media_id });
    if (artworkFor !== key || !result?.data_url) return;
    const image = document.createElement("img");
    image.alt = "";
    image.src = result.data_url;
    poster.prepend(image);
    poster.classList.add("has-art");
  } catch {
    // The title stays on the placeholder.
  }
}

function render() {
  document.documentElement.lang = state.language || "en";
  document.documentElement.dataset.theme = state.theme || "dark";
  const item = state.item;
  $("details").hidden = !item;
  if (!item) return;
  $("title").textContent = item.title || "";
  $("poster-title").textContent = item.title || "";
  const original = item.original_title && item.original_title !== item.title;
  $("original").hidden = !original;
  $("original").textContent = original ? item.original_title : "";
  const meta = [item.year, runtime(item.duration), item.genre]
    .filter(Boolean)
    .map((text) => {
      const span = document.createElement("span");
      span.textContent = text;
      return span;
    });
  if (rating(item.rating)) {
    const span = document.createElement("span");
    span.className = "rating";
    span.textContent = `★ ${rating(item.rating)}`;
    span.setAttribute(
      "aria-label",
      say(
        `Rated ${rating(item.rating)} out of 10`,
        `Note ${rating(item.rating)} sur 10`,
      ),
    );
    meta.push(span);
  }
  $("meta").replaceChildren(...meta);
  $("tagline").textContent = item.tagline || "";
  $("tagline").hidden = !item.tagline;
  $("plot").textContent = item.description || "";
  $("plot").hidden = !item.description;
  const people = [
    [say("Director", "Réalisation"), item.director],
    [say("Starring", "Avec"), item.actors],
  ].filter(([, value]) => value);
  $("people").replaceChildren(
    ...people.flatMap(([label, value]) => {
      const term = document.createElement("dt"),
        detail = document.createElement("dd");
      term.textContent = label;
      detail.textContent = value;
      return [term, detail];
    }),
  );
  $("people").hidden = !people.length;
  const found = flags(item);
  $("flags-label").textContent = say("File", "Fichier");
  $("flags").replaceChildren(
    ...found.map(([text, strong]) => {
      const li = document.createElement("li");
      li.textContent = text;
      if (strong) li.className = "strong";
      return li;
    }),
  );
  $("flags-section").hidden = !found.length;
  const tracks = state.tracks || {};
  $("audio-label").textContent = say("Audio", "Audio");
  const audio = (tracks.audio || []).map((row, index) => ({
    id: row.id,
    text: trackText(row, index, say("Audio", "Audio")),
    selected: !!row.selected,
  }));
  chips($("audio"), audio, "audio");
  $("audio-section").hidden = !tracks.ready || !audio.length;
  $("subtitle-label").textContent = say("Subtitles", "Sous-titres");
  const subtitles = (tracks.subtitles || []).map((row, index) => ({
    id: row.id,
    text: trackText(row, index, say("Subtitle", "Sous-titre")),
    selected: !!row.selected,
  }));
  subtitles.unshift({
    id: "off",
    text: say("Off", "Aucun"),
    selected: !subtitles.some((row) => row.selected),
  });
  chips($("subtitles"), subtitles, "subtitle");
  // "Off" alone is no choice: the section waits for a real subtitle track.
  $("subtitle-section").hidden = !tracks.ready || subtitles.length < 2;
  artwork(item);
}

window.addEventListener("nowplaying-environment", (event) => {
  if (event.detail.source_token !== state.source_token) $("error").hidden = true;
  state = event.detail || {};
  if (request) render();
});

tlPanelReady.then(async () => {
  request = await TLPanel.connect("nowplaying", { asynchronous: true });
  let height = 0;
  new ResizeObserver(() => {
    const next = Math.ceil(document.body.getBoundingClientRect().height);
    if (next !== height) {
      height = next;
      request("layout", { height }).catch(() => {});
    }
  }).observe(document.body);
  render();
  window.nowplayingReady();
});
