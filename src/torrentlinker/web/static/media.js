function mediaPlayerLabels() {
  $("media-player-menu-toggle").setAttribute("aria-label", say("Player options", "Options du lecteur"));
  $("media-player-menu-toggle").title = say("Player options", "Options du lecteur");
  $("media-player-menu").setAttribute("aria-label", say("Player options", "Options du lecteur"));
  $("media-player-audio-track").setAttribute("aria-label", say("Audio track", "Piste audio"));
  $("media-player-subtitle-track").setAttribute("aria-label", say("Subtitle track", "Piste de sous-titres"));
}
let mediaSessionPending = null;
async function mediaSession() {
  if (media.session) return media.session;
  if (mediaSessionPending) return mediaSessionPending;
  mediaSessionPending = mediaOpenSession();
  try { return await mediaSessionPending; } finally { mediaSessionPending = null; }
}
async function mediaOpenSession() {
  const restoreRequest = {generation: media.playbackGeneration, client: mediaClient(), selectedClient: state.clientId, session: null};
  media.playerClient = restoreRequest.client;
  const key = `tl-media-session:${media.playerClient}`;
  let saved;
  try { saved = JSON.parse(sessionStorage.getItem(key)); } catch (_) { /* Invalid local credentials are replaced. */ }
  let result;
  if (saved?.id && saved?.token && !await mediaSessionClaimed(saved.id)) {
    try { result = await api(`media/sessions/${encodeURIComponent(saved.id)}`, {token: saved.token}); result.token = saved.token; }
    catch (_) { sessionStorage.removeItem(key); }
  }
  if (!result) result = await api("media/sessions", {client_id: media.playerClient, platform: "web"});
  media.session = {id: result.id, token: result.token};
  sessionStorage.setItem(key, JSON.stringify(media.session));
  restoreRequest.session = {...media.session};
  if (!mediaRequestCurrent(restoreRequest)) return media.session;
  const restored = result.state || {};
  media.queue = restored.queue || []; media.index = restored.index || 0;
  media.shuffle = !!restored.shuffle; media.repeat = restored.repeat || "off"; media.ack = restored.command_ack || 0;
  if (restored.current_id && !restored.context?.preview) await mediaLoad(restored.current_id, restored.position || 0, true, null, restoreRequest, false);
  else if (restored.context?.preview) mediaStatus(say("Select Preview downloaded portion again to create a new verified partial preview.", "Sélectionnez à nouveau Prévisualiser la partie téléchargée pour créer un nouvel aperçu partiel vérifié."));
  if (!mediaRequestCurrent(restoreRequest)) return media.session;
  for (const player of [$("media-video"), $("media-audio")]) player.volume = restored.volume ?? 1;
  await mediaCommands(result.commands || []);
  return media.session;
}
function mediaInvalidatePlayback() { return ++media.playbackGeneration; }
function mediaNewSourceToken() {
  // getRandomValues also works when the owner opens the app over plain HTTP on a LAN.
  const data = crypto.getRandomValues(new Uint8Array(16)); data[6] = (data[6] & 15) | 64; data[8] = (data[8] & 63) | 128;
  const hex = Array.from(data, value => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
function mediaTrackState() {
  const player = mediaPlayer(), active = !!player.dataset.sourceToken && !!player.dataset.mediaId;
  const trackText = value => Array.from(value || "").slice(0, 300).join("");
  const external = [...player.querySelectorAll("track")];
  const ready = active && player.readyState >= 1 && external.every(track => track.readyState >= 2);
  return {media_id: player.dataset.mediaId || "", source_token: player.dataset.sourceToken || "", ready,
    audio_supported: active && !!player.audioTracks, subtitle_supported: active && !!player.textTracks,
    audio: active ? Array.from(player.audioTracks || []).slice(0, 100).map((track, index) => ({id: `audio:${index}`, label: trackText(track.label), language: trackText(track.language), selected: !!track.enabled})) : [],
    subtitles: active ? Array.from(player.textTracks || [], (track, index) => ({track, index}))
      .filter(({track}) => { const source = external.find(item => item.track === track); return !source || source.readyState === 2; })
      .slice(0, 100).map(({track, index}) => ({id: `subtitle:${index}`, label: trackText(track.label), language: trackText(track.language), selected: track.mode === "showing"})) : []};
}
function mediaSourceMatches(command) {
  const player = mediaPlayer();
  return !!command.source_token && command.source_token === player.dataset.sourceToken && command.media_id === player.dataset.mediaId;
}
function mediaTrackRequestFailure(request) {
  if (request?.status !== "failed" || !mediaSourceMatches(request) || media.failedTrackSource === request.source_token) return;
  media.failedTrackSource = request.source_token;
  const message = element("p", request.error || say("The requested playback tracks are unavailable.", "Les pistes demandées ne sont pas disponibles."), "media-error");
  message.id = "media-track-request-error"; message.setAttribute("role", "alert");
  $("media-track-request-error")?.remove(); $("media-player-shell").append(message);
}
function mediaSelectTrack(command) {
  let error = "";
  const state = mediaTrackState(), player = mediaPlayer();
  if (!mediaSourceMatches(command)) error = "The playback source changed. Refresh its tracks before selecting.";
  else if (!state.ready) error = "Playback tracks are not ready yet.";
  else if (command.kind !== "audio" && command.kind !== "subtitle") error = "Choose audio or subtitle tracks.";
  else if (!state[command.kind === "audio" ? "audio_supported" : "subtitle_supported"]) error = `${command.kind === "audio" ? "Audio" : "Subtitle"} track switching is unavailable in this browser.`;
  else {
    const tracks = state[command.kind === "audio" ? "audio" : "subtitles"];
    const off = command.kind === "subtitle" && command.track_id === "off";
    if (!off && !tracks.some(track => track.id === command.track_id)) error = "That track is unavailable in the current browser player.";
    else try {
      const available = command.kind === "audio" ? player.audioTracks : player.textTracks;
      Array.from(available).forEach((track, index) => {
        const selected = command.track_id === `${command.kind}:${index}`;
        if (command.kind === "audio") track.enabled = selected;
        else track.mode = selected ? "showing" : "disabled";
      });
      const selected = mediaTrackState()[command.kind === "audio" ? "audio" : "subtitles"].filter(track => track.selected);
      if (off ? selected.length !== 0 : selected.length !== 1 || selected[0].id !== command.track_id) error = "The browser did not apply the requested track.";
    } catch (_) { error = "The browser could not switch that track."; }
  }
  if (command.sequence) media.trackResult = {sequence: command.sequence, applied: !error, error};
  if (error) mediaStatus(error);
}
function mediaClosePlayerMenu(focus = false) {
  $("media-player-menu").hidden = true; $("media-video-stage").dataset.menuOpen = "false";
  $("media-player-menu-toggle").setAttribute("aria-expanded", "false");
  if (focus) $("media-player-menu-toggle").focus();
}
function mediaPositionPlayerMenu(point) {
  const menu = $("media-player-menu"), box = $("media-video-stage").getBoundingClientRect();
  if (menu.hidden) return;
  const width = menu.offsetWidth, height = menu.offsetHeight;
  menu.style.left = `${Math.max(12, Math.min(point?.x ?? box.right - width - 8, innerWidth - width - 12))}px`;
  menu.style.top = `${Math.max(12, Math.min(point?.y ?? box.top + 42, innerHeight - height - 12))}px`;
}
function mediaRenderPlayerTracks() {
  const state = mediaTrackState();
  for (const kind of ["audio", "subtitle"]) {
    const select = $(`media-player-${kind}-track`), rows = state[kind === "audio" ? "audio" : "subtitles"];
    $(`media-player-${kind}-control`).hidden = !state.ready || !state[`${kind}_supported`] || !rows.length;
    const signature = JSON.stringify([state.source_token, rows.map(row => [row.id, row.label, row.language])]);
    if (select.dataset.signature !== signature) {
      select.replaceChildren();
      if (kind === "subtitle") mediaOption(select, "off", say("Off", "Désactivés"));
      for (const row of rows) mediaOption(select, row.id, [row.label, row.language].filter(Boolean).join(" · ") || row.id);
      select.dataset.signature = signature; select.dataset.sourceToken = state.source_token; select.dataset.mediaId = state.media_id;
    }
    select.value = rows.find(row => row.selected)?.id || (kind === "subtitle" ? "off" : "");
  }
}
function mediaOpenPlayerMenu(point) {
  if ($("media-video-stage").hidden) return;
  mediaRenderPlayerTracks(); $("media-player-menu").hidden = false; $("media-video-stage").dataset.menuOpen = "true";
  $("media-player-menu-toggle").setAttribute("aria-expanded", "true"); mediaPositionPlayerMenu(point);
  $("media-player-menu-close").focus();
}
function mediaPlayerComposition(kind) {
  mediaClosePlayerMenu();
  const shell = $("media-player-shell"), menu = $("media-player-menu"), video = kind === "video";
  $("media-video-stage").hidden = !video;
  $("media-playing-description").hidden = !video;
  (video ? menu : shell.querySelector(".media-player-heading")).append($("media-chat"));
  const transport = shell.querySelector(".media-player-transport");
  for (const item of [shell.querySelector(".media-player-actions"), $("media-queue-details"), $("media-track-support")]) (video ? menu : shell).append(item);
  (video ? $("media-queue-details") : shell).append(transport);
}
function mediaRequestCurrent(request) {
  return request.generation === media.playbackGeneration && (request.browsingClient || request.client) === mediaClient()
    && request.selectedClient === state.clientId && (!request.session || (
      request.client === media.playerClient && request.session.id === media.session?.id
      && request.session.token === media.session?.token));
}
async function mediaClosePreviewHandle(preview, client) {
  try { await api(`media/previews/${encodeURIComponent(preview.preview_id)}?${new URLSearchParams({client_id: client})}`, undefined, "DELETE"); }
  catch (_) { /* Closing an expired preview must not replace the current playback decision. */ }
}
const mediaPreviewURL = previewId => `api/media/previews/${encodeURIComponent(previewId)}/stream?${new URLSearchParams({client_id: media.playerClient})}`;
async function mediaReleasePreview() {
  const previous = media.preview; media.preview = null;
  $("media-preview-state").hidden = true; $("media-refresh-preview").hidden = true;
  if (previous) await mediaClosePreviewHandle(previous, previous.client_id);
}
async function mediaPreview(id, refresh = false) {
  const request = {generation: mediaInvalidatePlayback(), client: mediaClient(), selectedClient: state.clientId, session: null};
  if (media.session && media.playerClient !== request.client) { mediaPlayer().pause(); media.session = null; }
  await mediaSession();
  if (!mediaRequestCurrent(request)) return;
  request.session = {...media.session};
  const position = refresh ? mediaPlayer().currentTime || 0 : 0;
  const preview = await api(`media/items/${encodeURIComponent(id)}/preview`, {client_id: request.client});
  if (!mediaRequestCurrent(request)) { await mediaClosePreviewHandle(preview, request.client); return; }
  try {
    const loaded = await mediaLoad(id, position, false, {...preview, item_id: id, client_id: request.client}, request);
    if (loaded) await mediaHeartbeat();
  } catch (error) {
    await mediaClosePreviewHandle(preview, request.client);
    if (mediaRequestCurrent(request)) throw error;
  }
}
async function mediaStop() {
  mediaInvalidatePlayback();
  mediaClosePlayerMenu();
  if (document.fullscreenElement === $("media-player-shell")) await document.exitFullscreen().catch(() => {});
  for (const player of [$("media-video"), $("media-audio")]) { player.pause(); delete player.dataset.mediaId; delete player.dataset.sourceToken; player.removeAttribute("src"); player.load(); }
  media.trackResult = null;
  $("media-track-request-error")?.remove();
  const closing = mediaReleasePreview(); media.queue = []; media.index = 0;
  $("media-player-shell").hidden = true; mediaQueueRender();
  await closing; await mediaHeartbeat();
}
async function mediaLoad(id, position = null, paused = false, preview = null, request = null, invalidate = true) {
  if (!request) {
    request = {generation: invalidate ? mediaInvalidatePlayback() : media.playbackGeneration,
      client: media.playerClient || mediaClient(), selectedClient: state.clientId,
      browsingClient: invalidate ? mediaClient() : null, session: media.session ? {...media.session} : null};
  }
  if (!mediaRequestCurrent(request)) { if (preview) await mediaClosePreviewHandle(preview, request.client); return false; }
  const row = await api(`media/items/${encodeURIComponent(id)}?${new URLSearchParams({client_id: request?.client || media.playerClient})}`);
  if (!mediaRequestCurrent(request)) { if (preview) await mediaClosePreviewHandle(preview, request.client); return false; }
  mediaItems.set(id, row);
  const old = mediaPlayer(); old.pause();
  await mediaReleasePreview();
  if (!mediaRequestCurrent(request)) { if (preview) await mediaClosePreviewHandle(preview, request.client); return false; }
  media.preview = preview;
  if (preview) { media.queue = [id]; media.index = 0; }
  else if (request.queue) { media.queue = request.queue; media.index = request.index; }
  $("media-player-shell").dataset.kind = row.kind; mediaMusicBar();
  mediaPlayerComposition(row.kind);
  const player = $(row.kind === "music" ? "media-audio" : "media-video");
  $("media-audio").hidden = row.kind !== "music"; $("media-video").hidden = row.kind === "music";
  player.volume = old.volume; player.dataset.mediaId = id; player.dataset.sourceToken = request.sourceToken || mediaNewSourceToken(); media.trackResult = null;
  $("media-track-request-error")?.remove();
  player.src = preview ? mediaPreviewURL(preview.preview_id) : mediaURL(id); player.load();
  $("media-player-shell").hidden = false; $("media-player-shell").scrollIntoView({block: "nearest"}); $("media-now-playing").textContent = [row.title, row.artist].filter(Boolean).join(" · ");
  $("media-playing-description").textContent = [[row.year, row.duration > 0 ? mediaTime(row.duration) : "", row.genre, row.language].filter(Boolean).join(" · "), row.description].filter(Boolean).join(" · ");
  $("media-playing-description").hidden = row.kind !== "video" || !$("media-playing-description").textContent;
  $("media-player-shell").querySelector(".media-playing-art")?.remove();
  if (row.kind === "music") $("media-player-shell").prepend(mediaArt(row, "media-playing-art"));
  $("media-codec-error").hidden = true;
  const fallback = $("media-external"); fallback.href = player.src;
  $("media-track-support").hidden = row.kind !== "video" || !!preview;
  $("media-track-external").href = mediaURL(id);
  fallback.textContent = preview ? say("Download fixed partial preview for an external player", "Télécharger l’aperçu partiel fixe pour un lecteur externe") : say("Open / download for an external player", "Ouvrir / télécharger pour un lecteur externe");
  if (preview) {
    $("media-preview-state").hidden = false; $("media-refresh-preview").hidden = false;
    $("media-preview-state").textContent = say(`Partial preview · fixed verified prefix · ${bytes(preview.verified_bytes)} / ${bytes(preview.total_bytes)}. Refresh explicitly after more data downloads.`, `Aperçu partiel · début vérifié fixe · ${bytes(preview.verified_bytes)} / ${bytes(preview.total_bytes)}. Actualisez l’aperçu après téléchargement de données supplémentaires.`);
  }
  for (const child of [...$("media-video").querySelectorAll("track")]) child.remove();
  for (const subtitle of row.subtitles || []) {
    const track = element("track"); track.kind = "subtitles"; track.label = subtitle.label || subtitle.language || "Subtitles"; track.srclang = subtitle.language || "en";
    track.src = subtitle.url || mediaURL(id, `subtitles/${encodeURIComponent(subtitle.id)}`); $("media-video").append(track);
    // A prepared paused player must load external cues before reporting its selectable tracks.
    track.track.mode = "hidden";
  }
  player.onloadedmetadata = () => { const seek = position === null ? row.position || 0 : position; if (seek > 0 && Number.isFinite(player.duration)) player.currentTime = Math.min(seek, player.duration); };
  if (!paused) await mediaTryPlay(player);
  if (!mediaRequestCurrent(request)) { if (preview) await mediaClosePreviewHandle(preview, request.client); return false; }
  mediaQueueRender(); return true;
}
async function mediaTryPlay(player = mediaPlayer()) {
  try { await player.play(); return true; }
  catch (error) { if (error.name === "NotAllowedError") mediaStatus("Press Play in the player to continue playback."); else if (error.name !== "AbortError") mediaCodecError(); return false; }
}
function mediaCodecError() { $("media-codec-error").hidden = false; $("media-codec-message").textContent = media.preview ? say("This partial preview cannot play yet. The format may need the missing end of the file, or its codec may be unsupported. Wait for more data and use Refresh preview.", "Cet aperçu partiel ne peut pas encore être lu. Le format peut exiger la fin du fichier ou son codec peut être incompatible. Attendez davantage de données, puis actualisez l’aperçu.") : "This browser could not play the file. Its codec may be unsupported. Open or download the file for an external player."; }
async function mediaStart(ids, index = 0) {
  const request = {generation: mediaInvalidatePlayback(), client: mediaClient(), selectedClient: state.clientId, session: null};
  ids = await ids;
  if (!mediaRequestCurrent(request) || !ids.length) return;
  if (media.session && media.playerClient !== request.client) { mediaPlayer().pause(); media.session = null; }
  await mediaSession();
  if (!mediaRequestCurrent(request)) return;
  request.session = {...media.session}; request.queue = [...ids]; request.index = index;
  const loaded = await mediaLoad(ids[index], null, false, null, request);
  if (loaded && mediaRequestCurrent(request)) await mediaHeartbeat();
}
async function mediaEnqueue(ids) { if (media.session && media.playerClient !== mediaClient()) throw Error("Choose the playing client before adding to its queue."); await mediaSession(); media.queue.push(...ids); mediaQueueRender(); await mediaHeartbeat(); }
async function mediaAdvance(delta) {
  if (!media.queue.length) return;
  let index = media.index + delta;
  if (media.shuffle && delta > 0 && media.queue.length > 1) index = (media.index + 1 + Math.floor(Math.random() * (media.queue.length - 1))) % media.queue.length;
  if (media.repeat === "all") index = (index + media.queue.length) % media.queue.length;
  if (index < 0 || index >= media.queue.length) return;
  media.index = index; await mediaLoad(media.queue[index], 0); mediaQueueRender();
}
async function mediaRemoveAt(index) {
  const previous = media.index;
  media.queue.splice(index, 1);
  if (index < previous) media.index--;
  else if (index === previous) {
    mediaPlayer().pause(); media.index = Math.min(index, Math.max(0, media.queue.length - 1));
    if (media.queue.length) await mediaLoad(media.queue[media.index], 0);
    else { delete mediaPlayer().dataset.mediaId; delete mediaPlayer().dataset.sourceToken; media.trackResult = null; mediaPlayer().removeAttribute("src"); mediaPlayer().load(); await mediaReleasePreview(); }
  }
  mediaQueueRender(); await mediaHeartbeat();
}
async function mediaQueueMetadata() {
  if (!media.session) return;
  const ids = [...new Set(media.queue.filter(id => !mediaItems.has(id)))];
  const results = await Promise.allSettled(ids.map(id => api(`media/items/${encodeURIComponent(id)}?${new URLSearchParams({client_id: media.playerClient})}`)));
  for (const result of results) if (result.status === "fulfilled") mediaItems.set(result.value.id, result.value);
  mediaQueueRender();
}
function mediaQueueRender() {
  $("media-shuffle").setAttribute("aria-pressed", String(media.shuffle)); $("media-repeat").value = media.repeat;
  $("media-show-queue").textContent = say(`Playback queue · ${media.queue.length}`, `File de lecture · ${media.queue.length}`);
  // Restored queues can contain uncached tracks; the server validates every saved item.
  $("media-save-playlist").querySelector("button").disabled = !media.queue.length || media.queue.some(id => { const row = mediaItems.get(id); return row && row.kind !== "music"; });
  const list = $("media-player-queue"), signature = JSON.stringify([language, media.index, media.queue.map(id => [id, mediaItems.get(id)?.title])]);
  if (list.dataset.signature === signature) return;
  list.dataset.signature = signature; list.replaceChildren();
  media.queue.forEach((id, index) => {
    const row = mediaItems.get(id), item = element("li");
    const select = button(`${index + 1}. ${row?.title || "Unavailable item"}`, async () => { media.index = index; await mediaLoad(id, 0); });
    if (index === media.index) select.setAttribute("aria-current", "true");
    item.append(select, button(say("Remove", "Retirer"), () => mediaRemoveAt(index), "quiet")); list.append(item);
  });
}
async function mediaCommands(commands) {
  for (const command of [...commands].sort((a, b) => a.sequence - b.sequence)) {
    if (command.sequence <= media.ack) continue;
    const player = mediaPlayer();
    if (command.action === "play") {
      if (command.media_ids?.length) {
        const request = {generation: mediaInvalidatePlayback(), client: media.playerClient || mediaClient(), selectedClient: state.clientId,
          session: media.session ? {...media.session} : null, queue: [...command.media_ids], index: command.index || 0, sourceToken: command.load_token};
        await mediaLoad(request.queue[request.index], command.position ?? null, !!command.start_paused, null, request);
      } else if ((command.media_id || command.source_token) && !mediaSourceMatches(command)) {
        const error = "The playback source changed. The prepared player was not resumed.";
        media.trackResult = {sequence: command.sequence, applied: false, error}; mediaStatus(error);
      } else {
        const played = await mediaTryPlay();
        if (command.source_token) {
          const applied = played && mediaSourceMatches(command);
          media.trackResult = {sequence: command.sequence, applied, error: applied ? "" : "The browser did not resume the prepared media source."};
        }
      }
    }
    if (command.action === "select_track") mediaSelectTrack(command);
    if (command.action === "pause") player.pause();
    if (command.action === "seek") { const seek = () => { player.currentTime = Math.max(0, command.position || 0); }; if (player.readyState) seek(); else player.addEventListener("loadedmetadata", seek, {once: true}); }
    if (command.action === "volume") for (const output of [$("media-video"), $("media-audio")]) output.volume = Math.min(1, Math.max(0, command.volume));
    if (command.action === "queue") {
      media.queue = command.media_ids || []; media.index = command.index || 0;
      if (media.queue.length && media.queue[media.index] !== player.dataset.mediaId) await mediaLoad(media.queue[media.index], 0, player.paused);
      else if (!media.queue.length) { player.pause(); delete player.dataset.mediaId; delete player.dataset.sourceToken; media.trackResult = null; player.removeAttribute("src"); player.load(); await mediaReleasePreview(); }
    }
    if (command.action === "next") await mediaAdvance(1);
    if (command.action === "previous") await mediaAdvance(-1);
    if (command.action === "shuffle") media.shuffle = !!command.shuffle;
    if (command.action === "repeat") media.repeat = command.repeat || "off";
    media.ack = command.sequence;
  }
  mediaQueueRender();
}
async function mediaHeartbeat() {
  if (!media.session || media.busy || $("workspace").hidden) return;
  media.busy = true;
  try {
    const browsing=media.kind==="video"&&media.browseContext;
    const player = mediaPlayer();
    const report = {current_id: player.dataset.mediaId || null, queue: media.queue, index: media.index, position: player.currentTime || 0, duration: Number.isFinite(player.duration) ? player.duration : 0, paused: player.paused, volume: player.volume, shuffle: media.shuffle, repeat: media.repeat, command_ack: media.ack, track_state: mediaTrackState(), track_result: media.trackResult || null};
    const response = await api(`media/sessions/${encodeURIComponent(media.session.id)}`, {token: media.session.token, report, context: {preview: media.preview ? {item_id: media.preview.item_id, verified_bytes: media.preview.verified_bytes, total_bytes: media.preview.total_bytes} : null, kind: media.kind, view: browsing?.view || media.view, selection: media.selected?.id || null, filters: browsing || {q: $("media-search").value, genre: $("media-genre").value, year: $("media-year").value, language: $("media-language").value}}});
    mediaTrackRequestFailure(response.state?.track_request);
    await mediaCommands(response.commands || []);
    if (!$("media-player-menu").hidden && !$("media-player-tracks").contains(document.activeElement)) { mediaRenderPlayerTracks(); mediaPositionPlayerMenu(); }
  } finally { media.busy = false; }
}
async function mediaPlaylists() {
  const rows = await api(`media/playlists?${mediaQuery({})}`), root = $("media-playlist-list"); root.replaceChildren();
  const playlists = rows.rows || rows;
  if (!playlists.length) root.append(element("p", say("Your saved playlists will appear here. Start with a track or album, then save its queue.", "Vos playlists apparaîtront ici. Lancez une piste ou un album, puis enregistrez la file."), "media-playlist-empty"));
  for (const row of playlists) {
    const item = element("article", undefined, "media-playlist-card"), actions = element("div", undefined, "media-card-actions");
    const count = row.media_ids?.length || 0;
    item.append(element("h3", row.name), element("p", say(`${count} track${count === 1 ? "" : "s"}`, `${count} piste${count === 1 ? "" : "s"}`), "media-card-meta"));
    actions.append(button(say("Play", "Lire"), () => mediaStart(row.media_ids || [])), button(say("Add to queue", "Ajouter à la file"), () => mediaEnqueue(row.media_ids || [])));
    const options = element("details"), more = element("summary", say("Edit playlist", "Modifier la playlist"));
    options.append(more, button(say("Replace with queue", "Remplacer par la file"), async () => { await api("media/playlists", {client_id: mediaClient(), id: row.id, name: row.name, media_ids: media.queue}); await mediaPlaylists(); }), button(say("Delete", "Supprimer"), async () => { await api(`media/playlists/${encodeURIComponent(row.id)}?${mediaQuery({})}`, undefined, "DELETE"); await mediaPlaylists(); }));
    item.append(actions, options); root.append(item);
  }
  mediaQueueRender();
}
async function mediaScan(quiet = false) {
  if (!quiet) $("media-library-options").open = false;
  const job = await api("media/scan", {client_id: mediaClient()}); media.scan = job.id; media.scanQuiet = quiet;
  $("media-cancel-scan").hidden = false; $("media-refresh").disabled = true;
  mediaScanIcon();
  if (!quiet) mediaStatus("Scanning Library Folders...");
}
// New films and episodes appear on their own: a quiet rescan reloads only what changed.
const MEDIA_AUTO_REFRESH = 60000;
async function mediaAutoScan() {
  if (state.view !== "media" || $("workspace").hidden || media.scan || !state.setup?.capabilities?.scan) return;
  await mediaScan(true);
}
// The toolbar ⟳ refreshes the library; while a refresh runs, the same button cancels it.
function mediaScanIcon() {
  const running = !!media.scan, icon = $("media-toolbar-refresh");
  const label = running ? say("Cancel library refresh", "Annuler l’actualisation") : say("Refresh library", "Actualiser la médiathèque");
  icon.setAttribute("aria-pressed", String(running)); icon.title = label; icon.setAttribute("aria-label", label);
}
async function mediaPollScan() {
  if (!media.scan) return;
  const job = await api(`jobs/${encodeURIComponent(media.scan)}`);
  const quiet = media.scanQuiet;
  if (!quiet) mediaStatus(job.progress?.message || (job.progress?.items !== undefined ? `Scanning Library Folders... ${job.progress.items} items found` : job.message || `Scan ${job.status}`));
  if (!["queued", "running"].includes(job.status)) {
    media.scan = ""; media.scanQuiet = false; mediaScanIcon(); $("media-cancel-scan").hidden = true; $("media-refresh").disabled = false;
    if (!quiet || job.result?.changed) await loadMedia();
    if (job.error && !quiet) mediaStatus(job.error);
  }
}
const MEDIA_CHAT_MIN = 320, MEDIA_SIDE_MIN = 480;
function mediaChatWidth(width) {
  // The chat keeps its remembered width, leaving the media side its minimum.
  const navigation = document.querySelector("main")?.getBoundingClientRect().left || 0;
  const clamped = Math.round(Math.max(MEDIA_CHAT_MIN, Math.min(width, window.innerWidth - navigation - MEDIA_SIDE_MIN)));
  document.body.style.setProperty("--media-chat-width", `${clamped}px`);
  return clamped;
}
function mediaRestoreChatWidth() {
  let saved = 0;
  try { saved = Number(localStorage.getItem("tl-media-chat-width")) || 0; } catch {}
  mediaChatWidth(saved || window.innerWidth * 0.38);
}
function mediaRememberChatWidth(width) { try { localStorage.setItem("tl-media-chat-width", String(width)); } catch {} }
function mediaChatButtons() {
  queueMicrotask(()=>window.dispatchEvent(new Event("media-host-changed")));
  for (const [id, label] of [["media-chat-history", say("Discussions", "Discussions")], ["media-chat-more", say("More", "Plus")], ["media-chat-close", say("Close chat", "Fermer la discussion")]]) {
    $(id).title = label; $(id).setAttribute("aria-label", label);
  }
  $("media-chat-resize").setAttribute("aria-label", say("Resize chat", "Redimensionner la discussion"));
  for (const id of ["media-chat", "media-feature-chat", "media-toolbar-chat"]) $(id)?.setAttribute("aria-pressed", String(media.chat));
  $("media-toolbar-chat").title = say("Chat", "Discussion"); $("media-toolbar-chat").setAttribute("aria-label", say("Chat", "Discussion"));
}
async function mediaOpenChat(conversationId = "", fresh = false) {
  await mediaSession(); await mediaHeartbeat();
  const result = await api(`media/sessions/${encodeURIComponent(media.session.id)}/chat`, {token: media.session.token, conversation_id: conversationId, new: fresh});
  if (!media.chat) mediaRestoreChatWidth();
  media.chat = true; $("media-chat-panel").hidden = false; document.body.classList.add("media-chat-open");
  mediaChatButtons(); mediaCloseChatMenu();
  await mountMediaAssistant($("media-chat-content"), result.conversation_id);
  $("assistant-prompt")?.focus();
}
async function mediaToggleChat() { if (media.chat) mediaCloseChat(); else await mediaOpenChat(); }
function mediaCloseChat() { media.chat = false; mediaCloseChatMenu(); $("media-chat-panel").hidden = true; document.body.classList.remove("media-chat-open"); mediaChatButtons(); restoreMediaAssistant(); }
function mediaCloseChatMenu() { $("media-chat-menu").hidden = true; $("media-chat-menu").replaceChildren(); }
function mediaChatMenu(anchor, items) {
  const menu = $("media-chat-menu");
  if (!menu.hidden && menu.dataset.anchor === anchor.id) return mediaCloseChatMenu();
  menu.replaceChildren(...items.map(([label, action, checked]) => {
    const item = button(label, () => { mediaCloseChatMenu(); guard(action); });
    item.setAttribute("role", checked === undefined ? "menuitem" : "menuitemradio");
    if (checked !== undefined) item.setAttribute("aria-checked", String(checked));
    return item;
  }));
  menu.dataset.anchor = anchor.id; menu.hidden = false;
  menu.querySelector("button")?.focus();
}
async function mediaChatHistory() {
  const conversations = (await api("assistant/conversations")).filter(c => c.folder === "Media").slice(0, 20);
  mediaChatMenu($("media-chat-history"), [
    [say("New discussion", "Nouvelle discussion"), () => mediaOpenChat("", true)],
    ...conversations.map(c => [c.name, () => mediaOpenChat(c.id), c.id === assistantConversation]),
  ]);
}
function mediaChatMore() {
  mediaChatMenu($("media-chat-more"), [
    [say("Discussion settings", "Paramètres de la discussion"), () => $("assistant-chat-settings")?.click()],
    [say("Delete discussion", "Supprimer la discussion"), async () => {
      if (!assistantConversation || !confirm(say("Delete this discussion and its history? Pending proposals will be rejected. Torrents and files will not be removed.", "Supprimer cette discussion et son historique ? Les propositions en attente seront refusées. Les torrents et fichiers ne seront pas supprimés."))) return;
      await api(`assistant/conversations/${assistantConversation}`, undefined, "DELETE");
      await mediaOpenChat("", true);
    }],
  ]);
}
function mediaStartChatResize(event) {
  event.preventDefault();
  // Keep drag events in the host when the pointer crosses the browsing iframe.
  event.currentTarget.setPointerCapture(event.pointerId);
  document.body.classList.add("media-chat-resizing");
  let width = 0;
  const move = e => { width = mediaChatWidth(window.innerWidth - e.clientX); };
  const done = () => {
    window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", done); window.removeEventListener("pointercancel", done);
    document.body.classList.remove("media-chat-resizing");
    if (width) mediaRememberChatWidth(width);
  };
  window.addEventListener("pointermove", move); window.addEventListener("pointerup", done); window.addEventListener("pointercancel", done);
}
function mediaChatResizeKey(event) {
  if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
  event.preventDefault();
  const current = $("media-chat-panel").getBoundingClientRect().width;
  mediaRememberChatWidth(mediaChatWidth(current + (event.key === "ArrowLeft" ? 24 : -24)));
}
function mediaCenterAppearance(enabled) {
  queueMicrotask(()=>window.dispatchEvent(new Event("media-host-changed")));
  document.body.classList.toggle("media-center-mode", enabled);
  const label = enabled ? say("Return to TorrentLinker", "Revenir à TorrentLinker") : say("Media Center mode", "Mode Media Center");
  $("media-center-mode").title = label; $("media-center-mode").setAttribute("aria-label", label);
  $("media-center-mode").setAttribute("aria-pressed", String(enabled));
}
async function mediaExitCenter() {
  if (document.fullscreenElement === document.documentElement) await document.exitFullscreen();
  mediaCenterAppearance(false);
}
$("media-center-mode").onclick = () => guard(async () => {
  if (document.body.classList.contains("media-center-mode")) await mediaExitCenter();
  else {
    if (document.fullscreenEnabled) await document.documentElement.requestFullscreen();
    mediaCenterAppearance(true);
  }
});
$("media-layout-switch").onchange = event => mediaSetLayout(event.target.value);
$("settings-media-layout").onchange = event => mediaSetLayout(event.target.value);
for (const item of document.querySelectorAll("[data-media-view]")) item.onclick = () => guard(async () => {
  // A browse tab returns to its rows, so it clears the filters a row's "See all" applied.
  media.gridMode = false; media.animeFilters = {};
  for (const key of ["genre", "year", "language", "availability"]) $(`media-${key}`).value = "";
  media.view = item.dataset.mediaView; $("media-view").value = media.view; await loadMedia();
});
$("media-details").addEventListener("click", event => { if (event.target === $("media-details")) { const box = event.target.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) event.target.close(); } });
$("media-player-expand").onclick = () => { const expanded = $("media-player-shell").classList.toggle("media-player-expanded"); $("media-player-expand").textContent = expanded ? say("Compact player", "Réduire le lecteur") : say("Expand player", "Agrandir le lecteur"); };
$("media-fullscreen").hidden = !document.fullscreenEnabled;
$("media-fullscreen").onclick = () => guard(async () => {
  if (document.fullscreenElement === $("media-player-shell")) await document.exitFullscreen();
  else await $("media-player-shell").requestFullscreen();
});
document.addEventListener("fullscreenchange", () => {
  if (!document.fullscreenElement) mediaCenterAppearance(false);
  const fullscreen = document.fullscreenElement === $("media-player-shell");
  $("media-fullscreen").textContent = fullscreen ? say("Exit fullscreen", "Quitter le plein écran") : say("Fullscreen", "Plein écran");
  $("media-fullscreen").dataset.i18n = fullscreen ? "mediaExitFullscreen" : "mediaFullscreen";
  $("media-fullscreen").setAttribute("aria-pressed", String(fullscreen));
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && document.fullscreenElement === $("media-player-shell")) {
    guard(() => document.exitFullscreen());
  } else if (event.key === "Escape" && document.body.classList.contains("media-center-mode")) {
    guard(mediaExitCenter);
  }
});
mediaSetLayout(media.layout);
$("logout").addEventListener("click", () => { mediaInvalidatePlayback(); mediaPlayer().pause(); });
$("target-client").addEventListener("change", mediaInvalidatePlayback);
$("media-stop").onclick = () => guard(mediaStop);
$("media-refresh-preview").onclick = () => guard(() => { if (media.preview) return mediaPreview(media.preview.item_id, true); });
$("media-video-tab").onclick = () => guard(async () => { media.kind = "video"; media.view = "recent"; mediaViews(); await loadMedia(); });
$("media-music-tab").onclick = () => guard(async () => { media.kind = "music"; media.view = "albums"; mediaViews(); await loadMedia(); });
$("media-view").onchange = () => guard(async () => { media.view = $("media-view").value; await loadMedia(); });
for (const item of document.querySelectorAll("[data-media-music-view]")) item.onclick = () => guard(async () => { media.view = item.dataset.mediaMusicView; $("media-view").value = media.view; await loadMedia(); });
for (const key of ["genre", "year", "language", "availability"]) $(`media-${key}`).onchange = () => guard(loadMedia);
let mediaSearchTimer;
$("media-search").oninput = () => { clearTimeout(mediaSearchTimer); mediaSearchTimer = setTimeout(() => guard(loadMedia), 250); };
$("media-refresh").onclick = () => guard(mediaScan);
for (const event of ["play", "pause", "ended", "emptied"]) $("media-audio").addEventListener(event, mediaMusicBar);
$("media-toolbar-refresh").onclick = () => guard(async () => { if (media.scan) await api(`jobs/${encodeURIComponent(media.scan)}/cancel`, {}); else await mediaScan(); });
mediaScanIcon();
$("media-more").onclick = () => guard(() => loadMedia(true));
$("media-cancel-scan").onclick = () => guard(async () => { if (media.scan) await api(`jobs/${encodeURIComponent(media.scan)}/cancel`, {}); });
$("media-chat").onclick = () => guard(mediaToggleChat); $("media-toolbar-chat").onclick = () => guard(mediaToggleChat); $("media-chat-close").onclick = mediaCloseChat;
mediaCenterAppearance(document.body.classList.contains("media-center-mode")); mediaChatButtons();
$("media-chat-history").onclick = () => guard(mediaChatHistory); $("media-chat-more").onclick = mediaChatMore;
$("media-chat-resize").addEventListener("pointerdown", mediaStartChatResize); $("media-chat-resize").addEventListener("keydown", mediaChatResizeKey);
$("media-chat-panel").addEventListener("keydown", e => { if (e.key === "Escape" && !$("media-chat-menu").hidden) { e.stopPropagation(); mediaCloseChatMenu(); } });
window.addEventListener("resize", () => { if (media.chat) mediaChatWidth($("media-chat-panel").getBoundingClientRect().width); });
$("media-previous").onclick = () => guard(() => mediaAdvance(-1)); $("media-next").onclick = () => guard(() => mediaAdvance(1));
$("media-shuffle").onclick = () => { media.shuffle = !media.shuffle; mediaQueueRender(); guard(mediaHeartbeat); };
$("media-repeat").onchange = () => { media.repeat = $("media-repeat").value; guard(mediaHeartbeat); };
$("media-queue-details").ontoggle = event => { if (event.target.open) { guard(mediaQueueMetadata); mediaPositionPlayerMenu(); } };
$("media-show-queue").onclick = () => { if (!media.queue.length) return; if (mediaPlayer() === $("media-video")) mediaOpenPlayerMenu(); $("media-queue-details").open = true; $("media-player-shell").scrollIntoView({block: "nearest"}); };
$("media-player-menu-toggle").onclick = () => $("media-player-menu").hidden ? mediaOpenPlayerMenu() : mediaClosePlayerMenu(true);
$("media-player-menu-close").onclick = () => mediaClosePlayerMenu(true);
$("media-video-stage").oncontextmenu = event => { event.preventDefault(); mediaOpenPlayerMenu({x: event.clientX, y: event.clientY}); };
$("media-video-stage").addEventListener("keydown", event => {
  if (event.key === "Escape" && !$("media-player-menu").hidden) { event.preventDefault(); event.stopPropagation(); mediaClosePlayerMenu(true); }
  if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) { event.preventDefault(); mediaOpenPlayerMenu(); }
});
document.addEventListener("pointerdown", event => { if (!$("media-player-menu").hidden && !$("media-player-menu").contains(event.target) && event.target !== $("media-player-menu-toggle")) mediaClosePlayerMenu(); });
$("media-player-menu").addEventListener("click", event => { if (["media-stop", "media-fullscreen", "media-player-expand", "media-chat", "media-previous", "media-next", "media-refresh-preview"].includes(event.target.id)) mediaClosePlayerMenu(); });
for (const kind of ["audio", "subtitle"]) $(`media-player-${kind}-track`).onchange = event => {
  const select = event.target;
  mediaSelectTrack({kind, track_id: select.value, source_token: select.dataset.sourceToken, media_id: select.dataset.mediaId});
  guard(mediaHeartbeat);
};
let mediaOverlayTimer;
$("media-video-stage").addEventListener("pointermove", () => {
  $("media-video-stage").classList.add("media-controls-revealed"); clearTimeout(mediaOverlayTimer);
  mediaOverlayTimer = setTimeout(() => $("media-video-stage").classList.remove("media-controls-revealed"), 1600);
});
$("media-video-stage").addEventListener("pointerdown", () => {
  $("media-video-stage").classList.add("media-controls-revealed"); clearTimeout(mediaOverlayTimer);
  mediaOverlayTimer = setTimeout(() => $("media-video-stage").classList.remove("media-controls-revealed"), 1600);
});
for (const event of ["play", "pause", "ended", "emptied"]) $("media-video").addEventListener(event, () => { $("media-video-stage").dataset.playing = String(!$("media-video").paused && !$("media-video").ended); });
window.addEventListener("resize", () => mediaPositionPlayerMenu());
document.addEventListener("fullscreenchange", () => mediaPositionPlayerMenu());
$("media-save-playlist").onsubmit = e => { e.preventDefault(); guard(async () => { await api("media/playlists", {client_id: media.playerClient || mediaClient(), name: $("media-playlist-name").value, media_ids: media.queue}); $("media-playlist-name").value = ""; await mediaPlaylists(); }); };
for (const player of [$("media-video"), $("media-audio")]) { player.onerror = mediaCodecError; player.onwaiting = () => { if (media.preview && player.currentTime > 0) mediaStatus(say("The fixed partial preview has no more playable data here. Wait for more download progress, then refresh preview.", "L’aperçu partiel fixe ne contient plus de données lisibles à cet endroit. Attendez la progression du téléchargement, puis actualisez l’aperçu.")); }; player.onended = () => guard(async () => { if (media.preview) { mediaStatus(say("End of fixed partial preview. Wait for more data, then refresh preview.", "Fin de l’aperçu partiel fixe. Attendez davantage de données, puis actualisez l’aperçu.")); } else if (media.repeat === "one") { player.currentTime = 0; await mediaTryPlay(player); } else await mediaAdvance(1); await mediaHeartbeat(); }); }
setInterval(() => { guard(mediaHeartbeat); guard(mediaPollScan); }, 1000);
setInterval(() => guard(mediaAutoScan), MEDIA_AUTO_REFRESH);
