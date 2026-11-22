"use strict";
/* A playing video belongs to the page (docs/specs/media-watch-page, layout A): its picture at the top, drawn by the
   host behind the transparent slot below; the controls over it, the film's details under it, then the rows.
   The host owns playback; this view shows what it publishes in environment.playback and sends commands. */
const WATCH_ICONS = {
  play: '<path d="M8 5l11 7-11 7z" fill="currentColor"/>', pause: '<path d="M8 5v14M16 5v14"/>',
  rew: '<path d="M11 7l-6 5 6 5M19 7l-6 5 6 5"/>', fwd: '<path d="M13 7l6 5-6 5M5 7l6 5-6 5"/>',
  full: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>', exit: '<path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  subs: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 13h4M13 13h4M7 16h7"/>',
  next: '<path d="M6 5l9 7-9 7zM18 5v14"/>', check: '<path d="M5 12l5 5 9-10"/>',
};
const watchIcon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${WATCH_ICONS[name]}</svg>`;
const WATCH_HIDE_MS = 3000;
let watchBarHeld = false, watchTimer = 0, watchWasPlaying = false, watchSource = "", watchSignature = "", watchLayoutSent = "", watchBarTop = 0, watchLastTop = 0, watchWatched = new Map();
const watchScroller = () => document.querySelector(".media-scroll");
const watchPlayback = () => media.kind === "video" && environment.playback?.media_id && environment.playback.kind === "video" ? environment.playback : null;
const watchClock = seconds => {
  const total = Math.max(0, Math.floor(Number(seconds) || 0)), hours = Math.floor(total / 3600), minutes = Math.floor(total / 60) % 60;
  return `${hours ? `${hours}:${String(minutes).padStart(2, "0")}` : minutes}:${String(total % 60).padStart(2, "0")}`;
};
function watchRuntime(seconds) {
  const minutes = Math.round((Number(seconds) || 0) / 60);
  if (!minutes) return "";
  const hours = Math.floor(minutes / 60), rest = String(minutes % 60).padStart(2, "0");
  return hours ? say(`${hours}h ${rest}m`, `${hours} h ${rest}`) : `${minutes} min`;
}
// Commands go to the host with the source they were drawn for, so a stale control never acts on a new film.
function watchSend(action, values = {}) {
  const play = watchPlayback();
  if (!play) return Promise.resolve();
  return host("player", {action, values, client_id: play.client_id, media_id: play.media_id, source_token: play.source_token, queue_revision: play.queue_revision});
}
function watchReveal() {
  const screen = $("media-screen");
  screen.dataset.controls = "on";
  clearTimeout(watchTimer);
  watchTimer = setTimeout(() => { if (watchPlayback()?.playing) screen.dataset.controls = "off"; }, WATCH_HIDE_MS);
}
function watchTap() {
  const screen = $("media-screen");
  // Shown and playing, a tap clears the picture; otherwise it always brings the controls back.
  if (screen.dataset.controls === "on" && watchPlayback()?.playing) { clearTimeout(watchTimer); screen.dataset.controls = "off"; }
  else watchReveal();
}
function watchTracksDialog() {
  const play = watchPlayback(), root = $("media-watch-tracks");
  if (!play) return;
  const tracks = play.tracks || {};
  root.replaceChildren(button(say("Close", "Fermer"), () => root.close()), element("h2", say("Audio and subtitles", "Audio et sous-titres")));
  const error = element("p", undefined, "media-error"); error.hidden = true;
  const group = (title, rows, kind) => {
    const section = element("section"), list = element("div", undefined, "media-detail-choices");
    for (const row of rows) {
      const choice = button(row.text, async () => {
        error.hidden = true;
        try { await watchSend("select_track", {kind, track_id: row.id}); }
        catch (failure) { error.textContent = failure.message; error.hidden = false; }
      });
      choice.setAttribute("aria-pressed", String(row.selected));
      list.append(choice);
    }
    section.append(element("h3", title), list);
    return section;
  };
  const text = (row, index, fallback) => [...new Set(String(row.label || "").split(" · ").filter(Boolean).filter(part => !/^(audio|subtitle|sous-titre|embedded subtitle|sous-titre intégré) \d+$/i.test(part)).filter(part => part.toLowerCase() !== String(row.language || "").toLowerCase()))].join(" · ") || row.language || `${fallback} ${index + 1}`;
  const audio = (tracks.audio || []).map((row, index) => ({id: row.id, text: text(row, index, say("Audio", "Audio")), selected: !!row.selected}));
  const subtitles = (tracks.subtitles || []).map((row, index) => ({id: row.id, text: text(row, index, say("Subtitle", "Sous-titre")), selected: !!row.selected}));
  subtitles.unshift({id: "off", text: say("Off", "Aucun"), selected: !subtitles.some(row => row.selected)});
  if (audio.length) root.append(group(say("Audio", "Audio"), audio, "audio"));
  if (subtitles.length > 1) root.append(group(say("Subtitles", "Sous-titres"), subtitles, "subtitle"));
  if (!audio.length && subtitles.length < 2) root.append(element("p", tracks.ready ? say("This file offers no other audio or subtitle choice.", "Ce fichier ne propose pas d’autre choix d’audio ou de sous-titres.") : say("The tracks are still loading.", "Les pistes se chargent encore."), "muted"));
  root.append(error);
  // The browser decides which embedded tracks it exposes: say so, and offer the file to another player.
  if (environment.mode === "web") root.append(element("p", say("Embedded track selection depends on this browser. Use an external player if a track is unavailable.", "La sélection des pistes intégrées dépend du navigateur. Utilisez un lecteur externe si une piste manque."), "media-track-support"));
  if (play.external_available) {
    if (environment.mode === "web") { const link = element("a", say("Open / download for an external player", "Ouvrir / télécharger pour un lecteur externe")); link.id = "media-watch-external"; link.href = play.external_url; link.target = "_blank"; link.rel = "noopener"; link.download = ""; root.append(link); }
    else { const open = button(say("Open in external player", "Ouvrir dans un lecteur externe"), () => watchSend("external")); open.id = "media-watch-external"; root.append(open); }
  }
  if (!root.open) root.showModal();
}
// A dialog drawn once would keep its old selection; it follows the host's tracks while it is open.
function watchTracksRefresh() { if ($("media-watch-tracks").open) watchTracksDialog(); }
function watchDetails(play) {
  const root = $("media-watch"), item = play.item || {};
  const watched = watchWatched.has(play.media_id) ? watchWatched.get(play.media_id) : !!item.watched;
  const flags = typeof mediaFlags === "function" ? mediaFlags(item).map(([text]) => text) : [];
  const facts = [item.year, watchRuntime(item.duration), item.genre, Number(item.rating) > 0 ? `★ ${Number(item.rating).toLocaleString(language === "fr" ? "fr-FR" : "en-US", {maximumFractionDigits: 1})}` : "", ...flags].filter(Boolean);
  const meta = element("p", facts.join(" · "), "media-watch-meta");
  if (typeof mediaRatingBadge === "function") mediaRatingBadge(item, meta);
  const tracksButton = button("", () => watchTracksDialog(), "media-secondary");
  tracksButton.innerHTML = `${watchIcon("subs")}<span>${say("Audio and subtitles", "Audio et sous-titres")}</span>`;
  const nextButton = button("", () => watchSend("next"), "media-secondary");
  nextButton.innerHTML = `${watchIcon("next")}<span>${say("Next", "Suivant")}</span>`;
  nextButton.disabled = !play.has_next;
  const seenButton = button("", async () => {
    const next = !watched;
    await api(`media/items/${encodeURIComponent(play.media_id)}/watched`, {client_id: mediaClient(), watched: next});
    watchWatched.set(play.media_id, next); watchSignature = ""; watchRender(); await loadMedia();
  }, "media-secondary");
  seenButton.innerHTML = `${watchIcon("check")}<span>${watched ? say("Mark unwatched", "Marquer comme non vu") : say("Mark watched", "Marquer comme vu")}</span>`;
  const actions = element("div", undefined, "media-feature-actions");
  actions.append(tracksButton, nextButton, seenButton);
  const parts = [element("h2", item.title || play.title || ""), meta, actions];
  if (item.description) parts.push(element("p", item.description, "media-watch-synopsis"));
  if (play.preview) {
    const note = element("p", say(`Partial preview · fixed verified prefix · ${mediaBytes(play.preview.verified_bytes)} / ${mediaBytes(play.preview.total_bytes)}. Refresh explicitly after more data downloads.`, `Aperçu partiel · début vérifié fixe · ${mediaBytes(play.preview.verified_bytes)} / ${mediaBytes(play.preview.total_bytes)}. Actualisez l’aperçu après téléchargement de données supplémentaires.`), "media-watch-note");
    note.append(" ", button(say("Refresh preview", "Actualiser l’aperçu"), () => watchSend("refresh-preview"), "quiet"));
    parts.push(note);
  }
  root.replaceChildren(...parts);
}
const mediaBytes = value => {
  const number = Number(value) || 0;
  return number >= 1e9 ? `${(number / 1e9).toFixed(1)} ${say("GB", "Go")}` : `${Math.round(number / 1e6)} ${say("MB", "Mo")}`;
};
function watchRender() {
  const view = $("view-media"), play = watchPlayback(), was = view.dataset.watch === "true";
  // The page header is hidden on Médias; on the Web the navigation opens from here.
  $("media-navigation").hidden = environment.mode !== "web" || !!environment.center_mode;
  $("media-navigation").setAttribute("aria-label", say("Navigation", "Navigation")); $("media-navigation").title = say("Navigation", "Navigation");
  view.dataset.watch = String(!!play);
  view.dataset.full = String(!!play && !!play.full);
  $("media-watch-slot").hidden = $("media-watch").hidden = !play;
  if (!play) {
    if (was) { clearTimeout(watchTimer); $("media-watch-tracks").open && $("media-watch-tracks").close(); delete view.dataset.bar; watchLayoutSent = ""; watchSignature = ""; $("media-watch").replaceChildren(); watchWasPlaying = false; }
    return;
  }
  if (!was) {
    // As in the preview, the bar shows over the film until the page scrolls down, on every screen.
    delete view.dataset.bar; watchBarHeld = false;
    watchLastTop = 0; watchScroller().scrollTop = 0; watchWasPlaying = false; }
  // At the top of the page the bar is always there, unless the phone's start is holding it back.
  if (!watchBarHeld && view.dataset.bar === "hidden" && watchScroller().scrollTop < 40) delete view.dataset.bar;
  // Another film or source closes the track choices drawn for the old one.
  const source = `${play.client_id}/${play.media_id}/${play.source_token}`;
  if (source !== watchSource) { watchSource = source; if ($("media-watch-tracks").open) $("media-watch-tracks").close(); }
  const label = (id, en, fr) => { $(id).setAttribute("aria-label", say(en, fr)); $(id).title = say(en, fr); };
  label("watch-rew", "Back 10 seconds", "Reculer de 10 secondes"); $("watch-rew").innerHTML = watchIcon("rew");
  label("watch-fwd", "Forward 10 seconds", "Avancer de 10 secondes"); $("watch-fwd").innerHTML = watchIcon("fwd");
  label("watch-toggle", play.playing ? "Pause" : "Play", play.playing ? "Pause" : "Lecture"); $("watch-toggle").innerHTML = watchIcon(play.playing ? "pause" : "play");
  label("watch-full", play.full ? "Exit full screen" : "Full screen", play.full ? "Quitter le plein écran" : "Plein écran"); $("watch-full").innerHTML = watchIcon(play.full ? "exit" : "full");
  label("watch-stop", "Close the player", "Fermer le lecteur"); $("watch-stop").innerHTML = watchIcon("close");
  label("watch-seek", "Seek", "Position");
  const seek = $("watch-seek");
  if (!seek.dataset.seeking) { seek.max = Math.max(0, play.duration || 0); seek.value = play.position || 0; }
  seek.style.setProperty("--progress", `${play.duration ? Math.min(100, 100 * (Number(seek.value) / play.duration)) : 0}%`);
  seek.disabled = !play.duration;
  $("watch-time").textContent = `${watchClock(play.position)} / ${watchClock(play.duration)}`;
  $("watch-rew").disabled = $("watch-fwd").disabled = $("watch-toggle").disabled = !play.media_id;
  const note = $("media-screen-note");
  note.hidden = !play.error;
  if (play.error) {
    note.replaceChildren(element("span", play.error));
    if (play.external_available && play.external_url) { const link = element("a", say("Open / download for an external player", "Ouvrir / télécharger pour un lecteur externe")); link.href = play.external_url; link.target = "_blank"; link.rel = "noopener"; link.download = ""; note.append(" ", link); }
  }
  const signature = JSON.stringify([play.client_id, play.media_id, play.source_token, language, play.item, play.tracks, play.has_next, play.preview, play.queue_revision, play.external_url, watchWatched.get(play.media_id)]);
  if (signature !== watchSignature) { watchSignature = signature; watchDetails(play); watchTracksRefresh(); }
  // Paused, the controls stay; a film that starts playing clears the picture after the usual delay.
  if (!play.playing) { clearTimeout(watchTimer); $("media-screen").dataset.controls = "on"; }
  else if (!watchWasPlaying) watchReveal();
  watchWasPlaying = !!play.playing;
  watchReport();
}
// The host draws the picture behind the slot: it needs to know where, and that wherever the page moves.
function watchReport() {
  if (!watchPlayback()) return;
  const rect = node => { const box = node.getBoundingClientRect(); return {x: box.left, y: box.top, width: box.width, height: box.height}; };
  const value = {band: rect($("media-watch-slot")), screen: rect($("media-screen"))};
  const key = JSON.stringify(value);
  if (key === watchLayoutSent) return;
  watchLayoutSent = key;
  host("watch-layout", value).catch(() => { watchLayoutSent = ""; });
}
// The top bar leaves while the page scrolls down and returns with any scroll up, and at the top.
function watchScrolled(event) {
  const view = $("view-media");
  if (view.dataset.kind !== "video") return;
  const watching = view.dataset.watch === "true", scroller = watchScroller();
  if (event.target !== (watching ? scroller : document)) return;
  const top = watching ? scroller.scrollTop : scrollY;
  watchBarHeld = false;
  if (top > watchLastTop + 6 && top > 40 && view.dataset.bar !== "hidden") view.dataset.bar = "hidden";
  else if ((top < watchLastTop - 6 || top < 40) && view.dataset.bar === "hidden") delete view.dataset.bar;
  watchLastTop = top;
}
function watchSetUp() {
  const screen = $("media-screen");
  screen.addEventListener("click", event => { if (event.target.closest("button, input")) return; watchTap(); });
  const act = (id, action, values) => { $(id).onclick = () => { watchReveal(); guard(() => typeof values === "function" ? watchSend(action, values()) : watchSend(action, values)); }; };
  act("watch-toggle", "toggle");
  act("watch-rew", "seek", () => ({position: Math.max(0, (watchPlayback()?.position || 0) - 10)}));
  act("watch-fwd", "seek", () => ({position: (watchPlayback()?.position || 0) + 10}));
  act("watch-full", "fullscreen");
  act("watch-stop", "stop");
  const seek = $("watch-seek");
  seek.oninput = () => { seek.dataset.seeking = "1"; watchReveal(); seek.style.setProperty("--progress", `${seek.max > 0 ? 100 * Number(seek.value) / seek.max : 0}%`); };
  seek.onchange = () => { const position = Number(seek.value); delete seek.dataset.seeking; guard(() => watchSend("seek", {position})); };
  $("media-navigation").onclick = () => guard(() => host("navigation"));
  document.addEventListener("scroll", watchScrolled, true);
  const observer = new ResizeObserver(watchReport);
  observer.observe($("media-watch-slot")); observer.observe(screen);
  addEventListener("resize", watchReport);
  document.addEventListener("keydown", event => {
    if (!watchPlayback() || event.target.closest?.("input, select, textarea, dialog, [contenteditable]")) return;
    if (event.key === "Escape" && environment.playback.full) { event.preventDefault(); guard(() => watchSend("fullscreen")); }
    else if (event.key === "f" || event.key === "F") { event.preventDefault(); guard(() => watchSend("fullscreen")); }
    else if (event.key === " " && !event.target.closest?.("button")) { event.preventDefault(); watchReveal(); guard(() => watchSend("toggle")); }
    else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      if (event.target.closest?.(".media-row-card, .media-focus-choice")) return;
      event.preventDefault(); watchReveal();
      guard(() => watchSend("seek", {position: Math.max(0, (environment.playback.position || 0) + (event.key === "ArrowRight" ? 10 : -10))}));
    }
  });
}
window.addEventListener("DOMContentLoaded", watchSetUp);
window.addEventListener("media-environment", watchRender);
