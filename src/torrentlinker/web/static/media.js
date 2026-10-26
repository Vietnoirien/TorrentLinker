/* The player lives outside navigation views, so browsing never replaces its DOM. */
const media = {kind: "video", view: "recent", rows: [], selected: null, session: null,
  playerClient: "", queue: [], index: 0, shuffle: false, repeat: "off", ack: 0,
  busy: false, preview: null, playbackGeneration: 0, next: null, chat: false, scan: "", request: 0};
const mediaTab = Array.from(crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, "0")).join("");
const mediaChannel = typeof BroadcastChannel === "function" ? new BroadcastChannel("torrentlinker-media") : null;
const mediaClaims = new Set();
if (mediaChannel) mediaChannel.onmessage = event => {
  const message = event.data;
  if (message?.type === "probe" && message.tab !== mediaTab && message.id === media.session?.id)
    mediaChannel.postMessage({type: "claimed", tab: message.tab, id: message.id});
  if (message?.type === "claimed" && message.tab === mediaTab) mediaClaims.add(message.id);
};
async function mediaSessionClaimed(id) {
  if (!mediaChannel) return false;
  mediaChannel.postMessage({type: "probe", tab: mediaTab, id});
  await new Promise(resolve => setTimeout(resolve, 100));
  return mediaClaims.delete(id);
}
const mediaItems = new Map();
const mediaClient = () => state.clientId === "all" ? state.setup?.default_client_id || "default" : state.clientId || "default";
const mediaQuery = values => new URLSearchParams({client_id: mediaClient(), ...values}).toString();
const mediaURL = (id, suffix = "stream") => `api/media/items/${encodeURIComponent(id)}/${suffix}?${new URLSearchParams({client_id: media.playerClient || mediaClient()})}`;
const mediaPlayer = () => $("media-audio").hidden ? $("media-video") : $("media-audio");
const mediaTime = n => { const seconds = Math.max(0, Math.floor(Number(n) || 0)); return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`; };
function mediaStatus(text) { $("media-status").textContent = text; }
function mediaOption(select, value, label) { const option = element("option", label); option.value = value; select.append(option); }
function mediaViews() {
  $("media-search").placeholder = say("Search your media", "Rechercher dans vos médias");
  $("media-playlist-name").placeholder = say("Playlist name", "Nom de la playlist");
  const select = $("media-view"); select.replaceChildren();
  const choices = media.kind === "video" ? [["recent", say("Recent", "Récents")], ["continue", say("Continue watching", "Reprendre")], ["films", say("Films", "Films")], ["series", say("Series", "Séries")], ["all", say("All videos", "Toutes les vidéos")]] : [["albums", say("Albums", "Albums")], ["artists", say("Artists", "Artistes")], ["tracks", say("Tracks", "Pistes")]];
  for (const [value, label] of choices) mediaOption(select, value, label);
  select.value = media.view;
  $("media-video-tab").setAttribute("aria-selected", String(media.kind === "video"));
  $("media-music-tab").setAttribute("aria-selected", String(media.kind === "music"));
  $("media-playlists").hidden = media.kind !== "music";
}
async function loadMedia(append = false) {
  if (!$("media-view").options.length) mediaViews();
  const version = ++media.request;
  const query = {kind: media.kind, view: media.view, q: $("media-search").value, offset: append ? media.next || 0 : 0, limit: 100};
  for (const key of ["genre", "year", "language", "availability"]) if ($(`media-${key}`).value) query[key] = $(`media-${key}`).value;
  const result = await api(`media?${mediaQuery(query)}`);
  if (version !== media.request) return;
  for (const row of result.rows) mediaItems.set(row.id, row);
  media.rows = append ? [...media.rows, ...result.rows] : result.rows;
  media.next = result.has_more ? result.next_offset : null;
  $("media-more").hidden = !result.has_more;
  for (const key of ["genre", "year", "language", "availability"]) {
    const select = $(`media-${key}`), old = select.value;
    select.replaceChildren(); mediaOption(select, "", say(`All ${key === "availability" ? "availability" : key === "year" ? "years" : key === "language" ? "languages" : "genres"}`, ({availability: "Toute disponibilité", year: "Toutes les années", language: "Toutes les langues", genre: "Tous les genres"})[key]));
    for (const entry of result.filters?.[key] || result.filters?.[`${key}s`] || (key === "availability" ? ["available", "unavailable", "unfinished"] : [])) mediaOption(select, typeof entry === "object" ? entry.value : entry, typeof entry === "object" ? entry.label : entry);
    select.value = old;
  }
  const noun = media.kind === "video" ? "video" : media.view === "albums" ? "album" : media.view === "artists" ? "artist" : "track";
  mediaStatus(result.scanning ? "Scanning Library Folders..." : `${result.total} ${noun}${result.total === 1 ? "" : "s"}${result.errors?.length ? " · Some folders are unavailable. Previous items were kept." : ""}`);
  mediaRender();
  if (!media.session && sessionStorage.getItem(`tl-media-session:${mediaClient()}`)) await mediaSession();
  if (media.kind === "music") await mediaPlaylists();
}
function mediaRender() {
  const root = $("media-results"); root.replaceChildren();
  if (!media.rows.length) { root.append(element("p", "No media found. Add a Library Folder in Settings, then refresh the inventory.", "muted")); return; }
  const groups = new Map();
  for (const row of media.rows) {
    const key = media.kind === "music" && media.view === "albums" ? row.album_id || row.id : media.kind === "music" && media.view === "artists" ? row.artist || "Unknown artist" : media.kind === "video" ? row.content_id || row.id : row.id;
    if (!groups.has(key)) groups.set(key, []); groups.get(key).push(row);
  }
  for (const rows of groups.values()) {
    const row = rows[0], card = element("article", undefined, "media-card");
    if (row.artwork_url) { const img = element("img"); img.src = row.artwork_url; img.alt = ""; img.loading = "lazy"; card.append(img); }
    else card.append(element("div", media.kind === "music" ? "♫" : "▷", "media-artwork-fallback"));
    const title = media.kind === "music" && media.view === "albums" ? row.album || "Unknown album" : media.kind === "music" && media.view === "artists" ? row.artist || "Unknown artist" : row.title;
    card.append(element("h3", title), element("p", [row.artist, row.year, row.genre].filter(Boolean).join(" · "), "muted"));
    if (media.kind === "music" && media.view === "albums" && row.track_count) card.append(element("p", `${row.track_count} track${row.track_count === 1 ? "" : "s"}`, "muted"));
    if (row.identity_source === "filename") card.append(element("p", "Filename metadata", "muted"));
    if (row.series || row.episode) card.append(element("p", `${row.series || "Episode"} ${row.season ? `S${row.season}` : ""}${row.episode ? ` E${row.episode}` : ""} · Filename metadata`, "muted"));
    if (row.position > 0) card.append(element("p", `${row.watched ? "Watched" : `Continue at ${mediaTime(row.position)}`}`, "muted"));
    if (row.available === false) card.append(element("p", row.reason || "Unavailable", "media-error"));
    const actions = element("div", undefined, "toolbar");
    const play = button(say("Play", "Lire"), () => mediaStart(mediaGroupIds(rows))); play.disabled = row.available === false;
    actions.append(play, button(say("Details", "Détails"), () => mediaDetails(row.id)));
    if (media.kind === "music") actions.append(button(say("Add to queue", "Ajouter à la file"), async () => mediaEnqueue(await mediaGroupIds(rows))));
    card.append(actions); root.append(card);
  }
}
async function mediaTrackGroup(row, view) {
  if (view === "albums" && !row.album_id) return [row];
  const found = []; let offset = 0;
  do {
    const page = await api(`media?${mediaQuery({kind: "music", view: "tracks", offset, limit: 200, ...(view === "albums" ? {album_id: row.album_id} : {artist: row.artist || ""})})}`);
    for (const item of page.rows) mediaItems.set(item.id, item);
    found.push(...page.rows.filter(item => view === "albums" ? item.album_id === row.album_id : item.artist === row.artist));
    offset = page.has_more ? page.next_offset : null;
  } while (offset !== null);
  return found;
}
async function mediaGroupIds(rows) {
  if (media.kind !== "music" || media.view === "tracks") return rows.map(item => item.id);
  return (await mediaTrackGroup(rows[0], media.view)).map(item => item.id);
}
async function mediaDetails(id) {
  const row = await api(`media/items/${encodeURIComponent(id)}?${mediaQuery({})}`); media.selected = row;
  const root = $("media-details"); root.replaceChildren(); root.hidden = false;
  root.append(button(say("Close details", "Fermer les détails"), () => { root.hidden = true; media.selected = null; }), element("h2", row.title));
  root.append(element("p", row.description || "No local synopsis available."));
  if (row.identity_source) root.append(element("p", `Metadata: ${row.identity_source}`, "muted"));
  if (row.release) root.append(element("p", `Release: ${row.release}`, "muted"));
  if (row.kind === "video" && row.availability === "unfinished") {
    root.append(element("p", say("Preview is optional. Only a verified downloaded prefix from a sequential qBittorrent single-file download can play. Some formats require the missing end of the file.", "L’aperçu est facultatif. Seul le début vérifié d’un téléchargement séquentiel qBittorrent à fichier unique peut être lu. Certains formats exigent la fin du fichier."), "muted"));
    root.append(button(say("Preview downloaded portion", "Prévisualiser la partie téléchargée"), () => mediaPreview(id)));
  }
  if (row.kind === "video") root.append(button(row.watched ? say("Mark unwatched", "Marquer comme non vu") : say("Mark watched", "Marquer comme vu"), async () => { await api(`media/items/${encodeURIComponent(id)}/watched`, {client_id: mediaClient(), watched: !row.watched}); await mediaDetails(id); await loadMedia(); }));
  for (const [key, label] of [["releases", say("Releases", "Versions")], ["episodes", say("Episodes", "Épisodes")]]) {
    if (!row[key]?.length) continue;
    const group = element("section"), list = element("div", undefined, "media-detail-choices");
    group.append(element("h3", label), list); root.append(group);
    const append = items => {
      for (const item of items) {
        const choice = button(item.release || item.title, () => mediaStart([item.id]));
        choice.disabled = item.available === false; choice.title = item.reason || ""; list.append(choice);
      }
    };
    append(row[key]);
    let next = row[`${key}_next_offset`];
    const more = button(key === "episodes" ? say("More episodes", "Plus d’épisodes") : say("More releases", "Plus de versions"), async () => {
      more.disabled = true;
      try {
        const page = await api(`media/items/${encodeURIComponent(id)}?${mediaQuery({[`${key}_offset`]: next, limit: 200})}`);
        if (media.selected?.id !== id || !group.isConnected || root.hidden) return;
        append(page[key] || []); next = page[`${key}_next_offset`]; more.hidden = !page[`${key}_has_more`];
      } finally { more.disabled = false; }
    });
    more.hidden = !row[`${key}_has_more`]; group.append(more);
  }
  if (row.kind === "music") {
    const artistView = media.view === "artists";
    const tracks = await mediaTrackGroup(row, artistView ? "artists" : "albums");
    if (media.selected?.id !== id || root.hidden) return;
    const ids = tracks.map(item => item.id);
    root.append(element("h3", artistView ? row.artist || "Unknown artist" : row.album || "Track"), button(artistView ? say("Play artist", "Lire cet artiste") : say("Play album", "Lire cet album"), () => mediaStart(ids)), button(say("Add to queue", "Ajouter à la file"), () => mediaEnqueue(ids)));
    const list = element("ol");
    tracks.forEach((item, index) => { const entry = element("li"); entry.append(button(`${item.title}${artistView ? ` · ${item.album || "Unknown album"}` : ""}`, () => mediaStart(ids, index)), element("span", item.duration > 0 ? ` ${mediaTime(item.duration)}` : " Duration unknown", "muted")); list.append(entry); });
    root.append(list);
  }
}
let mediaSessionPending = null;
async function mediaSession() {
  if (media.session) return media.session;
  if (mediaSessionPending) return mediaSessionPending;
  mediaSessionPending = mediaOpenSession();
  try { return await mediaSessionPending; } finally { mediaSessionPending = null; }
}
async function mediaOpenSession() {
  media.playerClient = mediaClient();
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
  const restored = result.state || {};
  media.queue = restored.queue || []; media.index = restored.index || 0;
  media.shuffle = !!restored.shuffle; media.repeat = restored.repeat || "off"; media.ack = restored.command_ack || 0;
  if (restored.current_id && !restored.context?.preview) await mediaLoad(restored.current_id, restored.position || 0, true, null, null, false);
  else if (restored.context?.preview) mediaStatus(say("Select Preview downloaded portion again to create a new verified partial preview.", "Sélectionnez à nouveau Prévisualiser la partie téléchargée pour créer un nouvel aperçu partiel vérifié."));
  for (const player of [$("media-video"), $("media-audio")]) player.volume = restored.volume ?? 1;
  await mediaCommands(result.commands || []);
  return media.session;
}
function mediaInvalidatePlayback() { return ++media.playbackGeneration; }
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
  for (const player of [$("media-video"), $("media-audio")]) { player.pause(); delete player.dataset.mediaId; player.removeAttribute("src"); player.load(); }
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
  $("media-save-playlist").hidden = row.kind !== "music";
  const player = $(row.kind === "music" ? "media-audio" : "media-video");
  $("media-audio").hidden = row.kind !== "music"; $("media-video").hidden = row.kind === "music";
  player.volume = old.volume; player.dataset.mediaId = id; player.src = preview ? mediaPreviewURL(preview.preview_id) : mediaURL(id); player.load();
  $("media-player-shell").hidden = false; $("media-player-shell").scrollIntoView({block: "nearest"}); $("media-now-playing").textContent = [row.title, row.artist].filter(Boolean).join(" · ");
  $("media-codec-error").hidden = true;
  const fallback = $("media-external"); fallback.href = player.src;
  fallback.textContent = preview ? say("Download fixed partial preview for an external player", "Télécharger l’aperçu partiel fixe pour un lecteur externe") : say("Open / download for an external player", "Ouvrir / télécharger pour un lecteur externe");
  if (preview) {
    $("media-preview-state").hidden = false; $("media-refresh-preview").hidden = false;
    $("media-preview-state").textContent = say(`Partial preview · fixed verified prefix · ${bytes(preview.verified_bytes)} / ${bytes(preview.total_bytes)}. Refresh explicitly after more data downloads.`, `Aperçu partiel · début vérifié fixe · ${bytes(preview.verified_bytes)} / ${bytes(preview.total_bytes)}. Actualisez l’aperçu après téléchargement de données supplémentaires.`);
  }
  for (const child of [...$("media-video").querySelectorAll("track")]) child.remove();
  for (const subtitle of row.subtitles || []) {
    const track = element("track"); track.kind = "subtitles"; track.label = subtitle.label || subtitle.language || "Subtitles"; track.srclang = subtitle.language || "en";
    track.src = subtitle.url || mediaURL(id, `subtitles/${encodeURIComponent(subtitle.id)}`); $("media-video").append(track);
  }
  player.onloadedmetadata = () => { const seek = position === null ? row.position || 0 : position; if (seek > 0 && Number.isFinite(player.duration)) player.currentTime = Math.min(seek, player.duration); };
  if (!paused) await mediaTryPlay(player);
  if (!mediaRequestCurrent(request)) { if (preview) await mediaClosePreviewHandle(preview, request.client); return false; }
  mediaQueueRender(); return true;
}
async function mediaTryPlay(player = mediaPlayer()) {
  try { await player.play(); }
  catch (error) { if (error.name === "NotAllowedError") mediaStatus("Press Play in the player to continue playback."); else if (error.name !== "AbortError") mediaCodecError(); }
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
    else { delete mediaPlayer().dataset.mediaId; mediaPlayer().removeAttribute("src"); mediaPlayer().load(); await mediaReleasePreview(); }
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
  const list = $("media-player-queue"); list.replaceChildren();
  media.queue.forEach((id, index) => {
    const row = mediaItems.get(id), item = element("li");
    const select = button(`${index + 1}. ${row?.title || "Unavailable item"}`, async () => { media.index = index; await mediaLoad(id, 0); });
    if (index === media.index) select.setAttribute("aria-current", "true");
    item.append(select, button(say("Remove", "Retirer"), () => mediaRemoveAt(index))); list.append(item);
  });
}
async function mediaCommands(commands) {
  for (const command of [...commands].sort((a, b) => a.sequence - b.sequence)) {
    if (command.sequence <= media.ack) continue;
    const player = mediaPlayer();
    if (command.action === "play") { if (command.media_ids?.length) { media.queue = command.media_ids; media.index = command.index || 0; await mediaLoad(media.queue[media.index], command.position ?? null); } else await mediaTryPlay(); }
    if (command.action === "pause") player.pause();
    if (command.action === "seek") { const seek = () => { player.currentTime = Math.max(0, command.position || 0); }; if (player.readyState) seek(); else player.addEventListener("loadedmetadata", seek, {once: true}); }
    if (command.action === "volume") for (const output of [$("media-video"), $("media-audio")]) output.volume = Math.min(1, Math.max(0, command.volume));
    if (command.action === "queue") {
      media.queue = command.media_ids || []; media.index = command.index || 0;
      if (media.queue.length && media.queue[media.index] !== player.dataset.mediaId) await mediaLoad(media.queue[media.index], 0, player.paused);
      else if (!media.queue.length) { player.pause(); delete player.dataset.mediaId; player.removeAttribute("src"); player.load(); await mediaReleasePreview(); }
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
    const player = mediaPlayer();
    const report = {current_id: player.dataset.mediaId || null, queue: media.queue, index: media.index, position: player.currentTime || 0, duration: Number.isFinite(player.duration) ? player.duration : 0, paused: player.paused, volume: player.volume, shuffle: media.shuffle, repeat: media.repeat, command_ack: media.ack};
    const response = await api(`media/sessions/${encodeURIComponent(media.session.id)}`, {token: media.session.token, report, context: {preview: media.preview ? {item_id: media.preview.item_id, verified_bytes: media.preview.verified_bytes, total_bytes: media.preview.total_bytes} : null, kind: media.kind, view: media.view, selection: media.selected?.id || null, filters: {q: $("media-search").value, genre: $("media-genre").value, year: $("media-year").value, language: $("media-language").value}}});
    await mediaCommands(response.commands || []);
  } finally { media.busy = false; }
}
async function mediaPlaylists() {
  const rows = await api(`media/playlists?${mediaQuery({})}`), root = $("media-playlist-list"); root.replaceChildren();
  for (const row of rows.rows || rows) {
    const item = element("div", undefined, "toolbar");
    item.append(element("span", row.name), button(say("Play", "Lire"), () => mediaStart(row.media_ids || [])), button(say("Replace with queue", "Remplacer par la file"), async () => { await api("media/playlists", {client_id: mediaClient(), id: row.id, name: row.name, media_ids: media.queue}); await mediaPlaylists(); }), button(say("Delete", "Supprimer"), async () => { await api(`media/playlists/${encodeURIComponent(row.id)}?${mediaQuery({})}`, undefined, "DELETE"); await mediaPlaylists(); })); root.append(item);
  }
}
async function mediaScan() {
  const job = await api("media/scan", {client_id: mediaClient()}); media.scan = job.id;
  $("media-cancel-scan").hidden = false; $("media-refresh").disabled = true;
  mediaStatus("Scanning Library Folders...");
}
async function mediaPollScan() {
  if (!media.scan) return;
  const job = await api(`jobs/${encodeURIComponent(media.scan)}`);
  mediaStatus(job.progress?.message || (job.progress?.items !== undefined ? `Scanning Library Folders... ${job.progress.items} items found` : job.message || `Scan ${job.status}`));
  if (!["queued", "running"].includes(job.status)) { media.scan = ""; $("media-cancel-scan").hidden = true; $("media-refresh").disabled = false; await loadMedia(); if (job.error) mediaStatus(job.error); }
}
async function mediaOpenChat() {
  await mediaSession(); await mediaHeartbeat();
  const result = await api(`media/sessions/${encodeURIComponent(media.session.id)}/chat`, {token: media.session.token});
  media.chat = true; $("media-chat-panel").hidden = false; document.body.classList.add("media-chat-open");
  await mountMediaAssistant($("media-chat-content"), result.conversation_id);
  $("assistant-prompt")?.focus();
}
function mediaCloseChat() { media.chat = false; $("media-chat-panel").hidden = true; document.body.classList.remove("media-chat-open"); restoreMediaAssistant(); }
$("logout").addEventListener("click", () => { mediaInvalidatePlayback(); mediaPlayer().pause(); });
$("target-client").addEventListener("change", mediaInvalidatePlayback);
$("media-stop").onclick = () => guard(mediaStop);
$("media-refresh-preview").onclick = () => guard(() => { if (media.preview) return mediaPreview(media.preview.item_id, true); });
$("media-video-tab").onclick = () => guard(async () => { media.kind = "video"; media.view = "recent"; mediaViews(); await loadMedia(); });
$("media-music-tab").onclick = () => guard(async () => { media.kind = "music"; media.view = "albums"; mediaViews(); await loadMedia(); });
$("media-view").onchange = () => guard(async () => { media.view = $("media-view").value; await loadMedia(); });
for (const key of ["genre", "year", "language", "availability"]) $(`media-${key}`).onchange = () => guard(loadMedia);
let mediaSearchTimer;
$("media-search").oninput = () => { clearTimeout(mediaSearchTimer); mediaSearchTimer = setTimeout(() => guard(loadMedia), 250); };
$("media-refresh").onclick = () => guard(mediaScan);
$("media-more").onclick = () => guard(() => loadMedia(true));
$("media-cancel-scan").onclick = () => guard(async () => { if (media.scan) await api(`jobs/${encodeURIComponent(media.scan)}/cancel`, {}); });
$("media-chat").onclick = () => guard(mediaOpenChat); $("media-chat-close").onclick = mediaCloseChat;
$("media-previous").onclick = () => guard(() => mediaAdvance(-1)); $("media-next").onclick = () => guard(() => mediaAdvance(1));
$("media-shuffle").onclick = () => { media.shuffle = !media.shuffle; mediaQueueRender(); guard(mediaHeartbeat); };
$("media-repeat").onchange = () => { media.repeat = $("media-repeat").value; guard(mediaHeartbeat); };
$("media-player-shell").querySelector("details").ontoggle = event => { if (event.target.open) guard(mediaQueueMetadata); };
$("media-save-playlist").onsubmit = e => { e.preventDefault(); guard(async () => { await api("media/playlists", {client_id: media.playerClient || mediaClient(), name: $("media-playlist-name").value, media_ids: media.queue}); $("media-playlist-name").value = ""; await mediaPlaylists(); }); };
for (const player of [$("media-video"), $("media-audio")]) { player.onerror = mediaCodecError; player.onwaiting = () => { if (media.preview && player.currentTime > 0) mediaStatus(say("The fixed partial preview has no more playable data here. Wait for more download progress, then refresh preview.", "L’aperçu partiel fixe ne contient plus de données lisibles à cet endroit. Attendez la progression du téléchargement, puis actualisez l’aperçu.")); }; player.onended = () => guard(async () => { if (media.preview) { mediaStatus(say("End of fixed partial preview. Wait for more data, then refresh preview.", "Fin de l’aperçu partiel fixe. Attendez davantage de données, puis actualisez l’aperçu.")); } else if (media.repeat === "one") { player.currentTime = 0; await mediaTryPlay(player); } else await mediaAdvance(1); await mediaHeartbeat(); }); }
setInterval(() => { guard(mediaHeartbeat); guard(mediaPollScan); }, 1000);
