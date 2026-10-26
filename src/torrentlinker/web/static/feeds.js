/* RSS uses the same authenticated API, tables and metadata dialog as Search. */
const feedState = {
  id: "",
  filter: "all",
  selected: new Set(),
  feeds: [],
  rows: []
};
const feedText = (en, fr) => say(en, fr);
const feedCall = (path, body, method = "POST") => api(path, body, method);
async function loadFeeds() {
  feedState.feeds = await api("feeds");
  const toolbar = $("feeds-toolbar");
  toolbar.replaceChildren(button(feedText("New subscription", "Nouvel abonnement"), () => editFeed()), button(feedText("Saved selections", "Sélections enregistrées"), feedSavedSelections), button(feedText("Compare clients", "Comparer les clients"), compareFeedClients));
  const sidebar = $("feeds-sidebar");
  sidebar.replaceChildren(button(feedText("All feeds", "Tous les flux"), () => {
    feedState.id = "";
    return loadFeeds();
  }));
  for (const feed of feedState.feeds) sidebar.append(button(`${feed.name} (${feed.unread_count})${feed.paused ? " · ⏸" : ""}`, () => {
    feedState.id = feed.id;
    return loadFeeds();
  }));
  const active = feedState.feeds.find(f => f.id === feedState.id);
  if (active) toolbar.append(button(feedText("Refresh", "Actualiser"), async () => {
    await feedCall(`feeds/${active.id}/refresh`, {});
    await loadFeeds();
  }), button(feedText("Edit", "Modifier"), () => editFeed(active)), button(active.paused ? feedText("Resume", "Reprendre") : feedText("Pause", "Suspendre"), async () => {
    await feedCall(`feeds/${active.id}/pause?paused=${!active.paused}`, {});
    await loadFeeds();
  }), button(feedText("Process rules", "Évaluer les règles"), async () => {
    const r = await feedCall(`feeds/${active.id}/process`, {});
    feedReport(r);
  }), button(feedText("Decisions", "Décisions"), async () => feedReport(await api(`feeds/${active.id}/decisions`))), button(feedText("Delete", "Supprimer"), async () => {
    await api(`feeds/${active.id}`, undefined, "DELETE");
    feedState.id = "";
    await loadFeeds();
  }));
  $("feeds-status").textContent = active ? `${active.coverage || feedText("Awaiting first refresh", "En attente de la première actualisation")} · ${feedText("Last success", "Dernier succès")}: ${active.last_success ? new Date(active.last_success * 1000).toLocaleString() : "—"}${active.error ? " · " + active.error : ""}` : feedText("Bounded RSS discovery. Shared Torznab categories can combine native subcategories. History and gap-free updates are not guaranteed.", "Découverte RSS limitée. Des catégories Torznab regroupent plusieurs sous-catégories natives. Historique et mises à jour sans lacunes non garantis.");
  const filters = $("feeds-filters");
  filters.replaceChildren(...[["all", "All", "Tous"], ["unread", "Unread", "Non lus"], ["saved", "Saved", "Enregistrés"], ["in-client", "In client", "Dans un client"], ["queued", "Queued", "En file"]].map(([id, en, fr]) => button(feedText(en, fr), () => {
    feedState.filter = id;
    return loadFeeds();
  })));
  let rows = await api(`feed-inbox?feed_id=${encodeURIComponent(feedState.id)}&unread=${feedState.filter === "unread"}&saved=${feedState.filter === "saved"}`);
  if (feedState.filter === "in-client") rows = rows.filter(r => r.in_clients.length);
  if (feedState.filter === "queued") rows = rows.filter(r => r.queued);
  feedState.rows = rows;
  feedState.selected.clear();
  const actions = $("feeds-actions");
  actions.replaceChildren(...[["read", "Mark read", "Marquer lus"], ["save", "Save", "Enregistrer"], ["dismiss", "Dismiss", "Masquer"]].map(([action, en, fr]) => button(feedText(en, fr), async () => {
    await feedCall("feed-inbox/mark", {
      hashes: [...feedState.selected],
      feed_id: feedState.id,
      action
    });
    await loadFeeds();
  })), button(feedText("Save selection", "Enregistrer la sélection"), async () => {
    const r = await feedCall("feed-selections", {
      hashes: [...feedState.selected]
    });
    feedReport(r);
  }), button(feedText("Queue selected", "Mettre la sélection en file"), () => feedEnqueue([...feedState.selected])));
  const columns = [{
    label: feedText("Title", "Titre"),
    render: r => button(`${r.unread ? "● " : ""}${r.title}`, () => details({
      ...r,
      hash: r.infohash,
      website: r.details_url
    }, () => feedEnqueue([r.infohash])))
  }, {
    label: feedText("Size", "Taille"),
    render: r => bytes(r.size)
  }, {
    label: "Seeds",
    render: r => r.seeders
  }, {
    label: feedText("Discovered", "Découvert"),
    render: r => new Date(r.discovered_at * 1000).toLocaleString()
  }, {
    label: feedText("Published", "Publié"),
    render: r => r.published_at ? new Date(r.published_at * 1000).toLocaleString() : "—"
  }, {
    label: feedText("State", "État"),
    render: r => r.queue_status || r.in_clients.join(", ") || (r.client_inventory_unknown.length ? feedText("Client comparison needed", "Comparaison des clients nécessaire") : "")
  }];
  table("feeds-results", rows.map(r => ({
    ...r,
    hash: r.infohash
  })), columns, feedState.selected);
}
function feedDefinition(raw) {
  const keys = ["id", "name", "query", "categories", "paused", "interval_minutes", "mode", "client_id", "folder", "preferences", "include_current", "wait_minutes", "replace_pending", "download_hours", "daily_bytes", "daily_torrents", "reserve_bytes"];
  return Object.fromEntries(keys.filter(k => k in raw).map(k => [k, raw[k]]));
}
function feedReport(value) {
  $("dialog-content").replaceChildren(element("pre", JSON.stringify(value, null, 2)));
  if (value.id && value.hashes) $("dialog-content").append(button(feedText("Queue selected", "Mettre la sélection en file"), () => feedEnqueue([], value.id)));
  $("dialog").showModal();
}
async function feedEnqueue(hashes, selectionId = "") {
  if (!hashes.length && !selectionId) throw Error(feedText("Select releases first.", "Sélectionnez des torrents."));
  const saved = selectionId ? await api(`feed-selections/${selectionId}`) : await feedCall("feed-selections", {
    hashes
  });
  const options = await api("feed-options");
  const content = $("dialog-content");
  content.replaceChildren(element("h2", feedText("Queue selected releases", "Mettre les torrents en file")));
  const client = element("select"),
    folder = element("select");
  for (const p of options.clients) client.append(new Option(p.name, p.id));
  client.value = state.clientId === "all" ? options.clients[0]?.id : state.clientId;
  const update = () => folder.replaceChildren(...(options.clients.find(p => p.id === client.value)?.folders || []).map(p => new Option(p, p)));
  client.onchange = update;
  update();
  content.append(client, folder, element("p", feedText("This saves an app queue entry. Disk and daily limits apply when downloads start.", "La file est enregistrée dans l'application. L'espace disque et les limites journalières sont vérifiés au démarrage.")), button(feedText("Add to app queue", "Ajouter à la file de l'application"), async () => {
    await feedCall(`feed-selections/${saved.id}/enqueue`, {
      client_id: client.value,
      folder: folder.value
    });
    $("dialog").close();
    await loadFeeds();
  }));
  $("dialog").showModal();
}
async function editFeed(existing = null, query = "") {
  const options = await api("feed-options");
  const content = $("dialog-content");
  content.replaceChildren(element("h2", feedText("RSS subscription", "Abonnement RSS")));
  const form = element("div", undefined, "feed-form");
  const inputs = {};
  function input(key, en, fr, value, type = "text") {
    const label = element("label", feedText(en, fr)),
      field = element("input");
    field.type = type;
    if (type === "checkbox") field.checked = Boolean(value);else field.value = value ?? "";
    label.append(field);
    form.append(label);
    inputs[key] = field;
    return field;
  }
  input("name", "Name", "Nom", existing?.name || "RSS");
  input("query", "Title query", "Recherche par titre", existing?.query ?? query);
  input("categories", "Torznab category IDs, comma separated", "Catégories Torznab, séparées par des virgules", existing?.categories?.join(",") || "");
  form.append(element("p", feedText("Examples: Film 2030, TV 5000, Music 3010, Books 7020, all 3D 8010. Native Search filters are not copied to RSS. Advanced criteria are evaluated locally against verified metadata.", "Exemples : Film 2030, Série 5000, Musique 3010, Livres 7020, toute la 3D 8010. Les filtres natifs de Recherche ne sont pas copiés. Les critères avancés utilisent les métadonnées vérifiées locales.")));
  const client = element("select"),
    folder = element("select"),
    mode = element("select");
  for (const p of options.clients) client.append(new Option(p.name, p.id));
  client.value = existing?.client_id || state.clientId;
  const update = () => {
    folder.replaceChildren(new Option("—", ""), ...(options.clients.find(p => p.id === client.value)?.folders || []).map(p => new Option(p, p)));
    folder.value = existing?.folder || "";
  };
  client.onchange = update;
  update();
  for (const [id, en, fr] of [["review_only", "Review only", "Lecture seule"], ["app_queue", "App queue only", "File de l'application"], ["automatic_download", "Automatic downloads", "Téléchargements automatiques"]]) mode.append(new Option(feedText(en, fr), id));
  mode.value = existing?.mode || "review_only";
  form.append(client, folder, mode);
  input("interval_minutes", "Poll interval, minutes", "Intervalle, minutes", existing?.interval_minutes || 30, "number");
  input("include_current", "Include currently available releases", "Inclure les torrents actuels", existing?.include_current, "checkbox");
  input("wait_minutes", "Wait for alternatives, minutes", "Attente des alternatives, minutes", existing?.wait_minutes || 0, "number");
  input("replace_pending", "Replace better matches while still pending", "Remplacer par un meilleur choix uniquement en attente", existing?.replace_pending, "checkbox");
  const prefs = existing?.preferences || {};
  input("min_size", "Minimum bytes", "Octets minimum", prefs.min_size || 0, "number");
  input("max_size", "Maximum bytes, blank for unlimited", "Octets maximum, vide pour illimité", prefs.max_size ?? "", "number");
  input("min_seeders", "Minimum seeders", "Seeders minimum", prefs.min_seeders || 0, "number");
  input("prefer_small", "Prefer smaller releases", "Préférer les petits torrents", prefs.prefer_small, "checkbox");
  for (const key of ["quality", "codec", "audio", "subtitles", "format", "bitrate", "platform", "license"]) for (const [group, en, fr] of [["required", "Required / accepted", "Requis / acceptés"], ["preferred", "Preferred in order", "Préférés par ordre"], ["excluded", "Excluded", "Exclus"]]) input(`${group}-${key}`, `${key} · ${en}`, `${key} · ${fr}`, prefs[group]?.[key]?.join(",") || "");
  input("priorities", "Ranking priorities, comma separated", "Priorités de classement, séparées par des virgules", (prefs.priorities || ["quality", "codec", "audio", "subtitles", "size"]).join(","));
  form.append(element("p", feedText("Add seeders to the ranking priorities to prefer more seeders; move it before quality or codec to give availability priority.", "Ajoutez seeders aux priorités de classement pour privilégier les torrents les mieux partagés ; placez-le avant quality ou codec pour donner priorité à la disponibilité.")));
  input("download_hours", "Allowed UTC hours, comma separated", "Heures UTC autorisées, séparées par des virgules", (existing?.download_hours || Array.from({
    length: 24
  }, (_, i) => i)).join(","));
  input("daily_bytes", "Daily download bytes", "Octets téléchargés par jour", existing?.daily_bytes ?? 10 * 1024 ** 3, "number");
  input("daily_torrents", "Daily download count", "Nombre de téléchargements par jour", existing?.daily_torrents ?? 20, "number");
  input("reserve_bytes", "Disk reserve bytes", "Réserve disque en octets", existing?.reserve_bytes ?? 10 * 1024 ** 3, "number");
  input("approve", "I explicitly authorize automatic downloads under these limits", "J'autorise explicitement les téléchargements automatiques selon ces limites", false, "checkbox");
  const split = value => value.split(",").map(v => v.trim()).filter(Boolean);
  function definition() {
    const p = {
      min_size: Number(inputs.min_size.value),
      max_size: inputs.max_size.value === "" ? null : Number(inputs.max_size.value),
      min_seeders: Number(inputs.min_seeders.value),
      prefer_small: inputs.prefer_small.checked,
      priorities: split(inputs.priorities.value),
      required: {},
      preferred: {},
      excluded: {}
    };
    for (const key of ["quality", "codec", "audio", "subtitles", "format", "bitrate", "platform", "license"]) for (const group of ["required", "preferred", "excluded"]) {
      const values = split(inputs[`${group}-${key}`].value);
      if (values.length) p[group][key] = values;
    }
    return {
      id: existing?.id || "",
      name: inputs.name.value,
      query: inputs.query.value,
      categories: split(inputs.categories.value).map(Number),
      mode: mode.value,
      client_id: client.value,
      folder: folder.value,
      preferences: p,
      paused: existing?.paused || false,
      interval_minutes: Number(inputs.interval_minutes.value),
      include_current: inputs.include_current.checked,
      wait_minutes: Number(inputs.wait_minutes.value),
      replace_pending: inputs.replace_pending.checked,
      download_hours: split(inputs.download_hours.value).map(Number),
      daily_bytes: Number(inputs.daily_bytes.value),
      daily_torrents: Number(inputs.daily_torrents.value),
      reserve_bytes: Number(inputs.reserve_bytes.value)
    };
  }
  const preview = element("pre");
  let previewed = "";
  content.append(form, button(feedText("Preview", "Prévisualiser"), async () => {
    const def = definition();
    const r = await feedCall("feeds/preview", def);
    previewed = JSON.stringify(def);
    preview.textContent = JSON.stringify({
      coverage: r.coverage,
      count: r.rows.length,
      evaluations: r.evaluations
    }, null, 2);
  }), preview, button(feedText("Save subscription", "Enregistrer l'abonnement"), async () => {
    const def = definition();
    if (!existing && previewed !== JSON.stringify(def)) throw Error(feedText("Preview this definition before saving.", "Prévisualisez cette définition avant de l'enregistrer."));
    await feedCall("feeds", {
      subscription: def,
      approve_automatic: inputs.approve.checked
    });
    $("dialog").close();
    await navigate("feeds");
  }));
  $("dialog").showModal();
}
$("subscribe-search").onclick = () => guard(() => editFeed(null, $("search-query").value));
async function feedSavedSelections() {
  const selections = await api("feed-selections");
  const content = $("dialog-content");
  content.replaceChildren(element("h2", feedText("Saved selections", "Sélections enregistrées")));
  for (const saved of selections) content.append(button(`${saved.name} · ${saved.hashes.length} · ${new Date(saved.created * 1000).toLocaleString()}`, async () => feedReport(await api(`feed-selections/${saved.id}`))));
  $("dialog").showModal();
}
async function compareFeedClients() {
  const options = await api("feed-options");
  const content = $("dialog-content");
  content.replaceChildren(element("h2", feedText("Compare clients", "Comparer les clients")));
  const choices = options.clients.map(client => {
    const label = element("label", client.name),
      input = element("input");
    input.type = "checkbox";
    input.checked = true;
    label.append(input);
    content.append(label);
    return {
      client,
      input
    };
  });
  content.append(button(feedText("Compare", "Comparer"), async () => {
    const client_ids = choices.filter(value => value.input.checked).map(value => value.client.id);
    if (!client_ids.length) throw Error(feedText("Choose at least one Torrent Client.", "Choisissez au moins un client torrent."));
    const result = await feedCall("feed-inbox/compare", {
      client_ids
    });
    $("dialog").close();
    await loadFeeds();
    feedReport(result);
  }));
  $("dialog").showModal();
}
