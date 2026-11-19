// The shell can finish authentication before deferred panel hosts have loaded.
// The panel's ready event will load its data once its iframe is available.
function loadTorrents() { window.torrentsEnvironment?.(); }
function loadAssistant() { window.assistantEnvironment?.(); }

"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  view: "torrents",
  setup: null,
  settingsSection: "connections",
  clientId: "",
  addingClient: false,
  offset: 0,
  sort: "name",
  descending: false,
  searchPage: 1,
  searchPages: 1,
  libraryOffset: 0,
  selected: new Set(),
  searchSelected: new Set(),
  queueSelected: new Set(),
  queueRows: [],
  jobs: new Map(),
  searchRows: [],
  localItem: "",
};
const french = {
  mediaFullscreen: "Plein écran", mediaExitFullscreen: "Quitter le plein écran",
  mediaCenterMode: "Mode Media Center", mediaCenterReturn: "Revenir à TorrentLinker",
  interfaceSettings: "Interface", mediaLayout: "Disposition des médias", mediaLayoutShort: "Disposition",
  mediaLayoutCinematic: "Accueil cinéma", mediaLayoutFocus: "Focus", mediaLayoutCollection: "Collection",
  mediaLayoutHelp: "Choisissez la présentation de la médiathèque dans ce navigateur. La lecture continue lorsque vous changez de disposition.",
  mediaHome: "Accueil", mediaFilms: "Films", mediaSeries: "Séries", mediaContinue: "Reprendre la lecture",
  mediaLibraryOptions: "Options de bibliothèque", mediaYourLibrary: "Votre médiathèque", mediaYourCollection: "Votre collection",
  mediaExpandPlayer: "Agrandir le lecteur", mediaAddFolder: "Ajouter un dossier de bibliothèque",
  mediaRefreshPreview: "Actualiser l’aperçu",
  mediaStop: "Arrêter",
  mediaVideo: 'Vidéo',
  mediaMusic: 'Musique',
  mediaRefresh: 'Actualiser les médias',
  mediaCancelScan: 'Annuler l’analyse',
  mediaMore: 'Afficher la suite',
  mediaChat: 'Discuter de ce média',
  mediaCloseChat: 'Fermer la discussion',
  turnOffPartialNames: 'Le désactiver dans Transmission et réessayer',
  checkAllCandidates: 'Vérifier tous les Candidats',
  reseedAllMatches: 'Remettre en seed toutes les correspondances complètes',
  mediaPrevious: 'Précédent',
  mediaNext: 'Suivant',
  mediaShuffle: 'Aléatoire',
  mediaExternal: 'Ouvrir / télécharger pour un lecteur externe',

  agentMedia: "Lecture des médias et playlists",
  allStates: "Tous les états", seedingState: "En partage", downloadingState: "Téléchargement",
  pausedState: "En pause", checkingState: "Vérification", errorState: "Erreur",
  uploadHelp: "Choisissez un élément local dans la Bibliothèque pour préparer un Upload.",
  categoryLabel: "Catégorie", subcategoryLabel: "Sous-catégorie", imageUrl: "URL de l’image",
  releaseName: "Nom de la release", updatePreview: "Actualiser l’aperçu",
  reviewUpload: "J’ai relu les fichiers, la description et les avertissements de catégorie.",
  closeNavigation: "Fermer la navigation",
  navigation: "Navigation", catalogueTab: "Catalogue", planCategory: "Catégorie / sous-catégorie",
  allCategories: "Toutes les catégories", optimizeFor: "Optimiser pour", maxSeeders: "Sources maximum",
  minTorrentGiB: "Taille minimum par torrent, Gio", maxTorrentGiB: "Taille maximum par torrent, Gio",
  refreshProfile: "Actualiser le profil",
  planZeroHelp: "Un budget ou une taille maximum de 0 ne fixe aucune limite supplémentaire. L’espace disponible reste pris en compte dans le plan.",
  seedingTab: "En partage", planTab: "Plan", expandAll: "Tout développer", collapseAll: "Tout réduire",
  seedingSort: "Trier les torrents par", torrentName: "Torrent", torrentSize: "Taille",
  seedAge: "Âge du seed (jours)", seedingOrder: "Ordre", descending: "Décroissant", ascending: "Croissant",
  classComparison: "Comparaison des classes",
  zenPerDay: "≈ Zen/jour",
  agentAccess: "Accès agent (MCP)", enableAgents: "Activer l’accès agent",
  agentHelp: "Les nouvelles connexions proposent uniquement des changements. Approuvez-les ci-dessous ou autorisez certaines actions dans les limites quotidiennes. Le retrait et la suppression de fichiers nécessitent toujours votre accord.",
  agentEndpoint: "Adresse MCP", agentClients: "Clients autorisés", agentMode: "Mode",
  agentPropose: "Propositions uniquement", agentExecute: "Exécuter les actions autorisées",
  agentPermissions: "Actions automatiques", agentControls: "Pause, vérification et reprise des torrents complets",
  agentUploads: "Brouillons d’upload et mise en seed", agentDailyGiB: "Budget quotidien (Gio)",
  agentDailyCount: "Torrents par jour", agentReserve: "Espace à conserver, Gio (0 = désactivé)",
  agentCreate: "Créer la connexion", agentConnections: "Connexions", agentProposals: "Propositions et tâches",
  agentGoals: "Objectifs enregistrés", agentHide: "Masquer le jeton",
  agentTokenHelp: "Copiez ce jeton maintenant. Il ne sera affiché qu’une fois. Utilisez-le comme jeton Bearer ou TL_MCP_TOKEN pour le pont stdio. Gardez-le privé.",
  targetClient: "Client cible", addClient: "Ajouter un client", defaultClient: "Définir par défaut",
  removeClient: "Retirer ce client", clientName: "Nom du client", planDestinations: "Destinations du Plan",
  planDestinationHelp: "Choisissez un client ou répartissez entre plusieurs clients. Budget 0 : espace disponible.",
  welcome: "Vos torrents, où qu’ils soient.",
  webPassword: "Mot de passe de l’interface web",
  signIn: "Se connecter",
  passwordHelp: "Utilisez le mot de passe choisi au démarrage du serveur.",
  torrents: "Torrents",
  search: "Recherche",
  queue: "File de téléchargement",
  library: "Bibliothèque",
  activity: "Activité",
  settings: "Paramètres",
  theme: "Thème",
  system: "Système",
  light: "Clair",
  dark: "Sombre",
  signOut: "Déconnexion",
  setupIntro:
    "Connectez votre client, vérifiez ses dossiers, puis ajoutez c411. Chaque connexion reste modifiable.",
  stepClient: "1 · Client torrent",
  stepStorage: "2 · Dossiers",
  stepIndexer: "3 · c411",
  stepReady: "4 · Prêt",
  connectClient: "Connecter votre client torrent",
  addressHelp:
    "Indiquez une adresse accessible depuis ce serveur. Pour une seedbox, utilisez l’adresse de son interface web.",
  client: "Client torrent",
  address: "Adresse du serveur",
  username: "Identifiant",
  password: "Mot de passe",
  advanced: "Paramètres avancés",
  dockerAddress:
    "Dans Docker, localhost désigne ce conteneur. Utilisez le nom du service client sur un réseau partagé, ou l’adresse HTTPS de votre seedbox.",
  test: "Tester la connexion",
  saveContinue: "Enregistrer et continuer",
  checkFolders: "Retrouver vos fichiers",
  storageIntro:
    "La gestion des torrents fonctionne sans accès aux fichiers. L’analyse, le reseed, la préparation des uploads et les téléchargements sûrs nécessitent un stockage accessible depuis ce serveur.",
  serverFolder: "Dossier visible par TorrentLinker",
  clientFolder: "Même dossier dans le client torrent",
  browse: "Parcourir",
  purpose: "Utiliser ce dossier pour",
  downloads: "Téléchargements",
  kind: "Type de contenu",
  depth: "Regroupement des éléments",
  checkMapping: "Vérifier la correspondance",
  addFolder: "Ajouter un dossier",
  continue: "Continuer",
  skipStorage: "Continuer sans accès aux fichiers",
  connectIndexer: "Connecter c411",
  keyHelp:
    "Votre clé API reste sur ce serveur. Vous pouvez gérer votre client sans configurer c411.",
  skip: "Configurer plus tard",
  ready: "Votre espace est prêt",
  revisit:
    "Revenez dans les paramètres pour ajouter des dossiers ou modifier une connexion. Les tâches continuent après la fermeture du navigateur.",
  openTorrents: "Ouvrir les torrents",
  refresh: "Actualiser",
  start: "Démarrer",
  pause: "Mettre en pause",
  recheck: "Revérifier",
  remove: "Retirer le torrent",
  deleteFiles: "Supprimer le torrent et les fichiers",
  dailyZen: "Estimation Zen / jour",
  seeding: "Torrents en seed",
  planner: "Planificateur",
  planHelp:
    "Créez une proposition à partir du catalogue et du stockage vérifié. Les estimations Zen et les notes issues du cache sont provisoires. Relisez le plan avant l’ajout à la file.",
  cachedPlan: "Utiliser le catalogue en cache sans actualiser",
  maxTorrents: "Nombre maximal de torrents",
  maxGiB: "Budget de téléchargement, Gio",
  updateCatalogue: "Actualiser le catalogue",
  buildPlan: "Créer un plan",
  queueSelected: "Ajouter la sélection à la file",
  moreFilters: "Plus de filtres",
  queueHelp:
    "Démarrer envoie les torrents au client. Mettre la tâche en pause arrête les prochains envois ; les téléchargements déjà lancés continuent.",
  startQueue: "Démarrer la file",
  removeSelected: "Retirer la sélection",
  scan: "Analyser les dossiers",
  jobsHelp:
    "Les tâches appartiennent au serveur. Vous pouvez fermer le navigateur et revenir plus tard. Aucune action interrompue n’est relancée automatiquement.",
};
let language =
  localStorage.getItem("tl-language") ||
  (navigator.language.startsWith("fr") ? "fr" : "en");
const english = new Map();
function translate() {
  document.documentElement.lang = language;
  $("language").value = language;
  document.querySelectorAll("[data-en][data-fr]").forEach(el => {
    el.textContent = language === "fr" ? el.dataset.fr : el.dataset.en;
  });
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    if (!english.has(el)) english.set(el, el.textContent);
    el.textContent =
      language === "fr"
        ? french[el.dataset.i18n] || english.get(el)
        : english.get(el);
  });
}
const say = (en, fr) => (language === "fr" ? fr : en);
function element(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
function button(text, callback, cls) {
  const e = element("button", text, cls);
  e.type = "button";
  e.onclick = () => guard(callback);
  return e;
}
function toast(text) {
  $("toast").textContent = text;
  $("toast").hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => ($("toast").hidden = true), 7000);
}
async function guard(fn) {
  try {
    await fn();
  } catch (error) {
    toast(error.message);
  }
}
async function api(path, body, method) {
  const scoped = ["reseed-workspace", "setup", "torrents", "library", "queue", "upload/queue", "upload/drafts"];
  if (body === undefined && scoped.includes(path.split("?")[0]) && state.clientId && !new URLSearchParams(path.split("?")[1]).has("client_id")) {
    const id = state.clientId === "all" && path === "setup" ? state.setup?.default_client_id || "" : state.clientId;
    path += (path.includes("?") ? "&" : "?") + "client_id=" + encodeURIComponent(id);
  }
  if (body !== undefined && (path === "jobs" || path === "confirm" || (path.startsWith("setup/") && !path.startsWith("setup/assistant")))) {
    body = {client_id: state.clientId === "all" ? state.setup?.default_client_id : state.clientId, ...body};
    if (path === "jobs" && body.kind === "refresh") body.client_id = state.clientId;
  }
  const response = await fetch(`api/${path}`, {
    method: method || (body === undefined ? "GET" : "POST"),
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-TorrentLinker": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) {
    if (response.status === 401) {
      clearAgentToken();
      $("workspace").hidden = true;
      $("login-screen").hidden = false;
    }
    // An `action` tells the page what it may offer, such as fixing a client option.
    throw Object.assign(Error(result.detail || "Request failed"), {action: result.action});
  }
  return result;
}
const bytes = (n) => {
  if (n === null || n === undefined) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
  let i = 0;
  while (n >= 1024 && i < 5) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
};
const num = (n) => (n === null || n === undefined ? "—" : Number(n).toFixed(2));
function age(timestamp) {
  if (!timestamp) return "—";
  const seconds = Math.max(0, Date.now() / 1000 - timestamp);
  const [value, unit] =
    seconds < 3600
      ? [Math.floor(seconds / 60), say("minutes", "minutes")]
      : seconds < 86400
        ? [Math.floor(seconds / 3600), say("hours", "heures")]
        : [Math.floor(seconds / 86400), say("days", "jours")];
  return `${value} ${unit}`;
}
function table(target, rows, columns, selection, key = "hash", onChange, onRow) {
  const host = $(target);
  host.replaceChildren();
  if (!rows.length) {
    host.append(
      element(
        "p",
        say("Nothing to display yet.", "Aucun élément à afficher."),
        "empty",
      ),
    );
    return;
  }
  const t = element("table"),
    head = element("tr");
  if (selection) {
    const cell = element("th"),
      input = document.createElement("input");
    input.type = "checkbox";
    input.setAttribute(
      "aria-label",
      say("Select page", "Sélectionner la page"),
    );
    input.checked = rows.every((r) => selection.has(r[key]));
    input.onchange = () => {
      rows.forEach((r) =>
        input.checked ? selection.add(r[key]) : selection.delete(r[key]),
      );
      table(target, rows, columns, selection, key, onChange);
      if (onChange) onChange();
    };
    cell.append(input);
    head.append(cell);
  }
  for (const column of columns) {
    const cell = element("th");
    if (column.title) cell.title = column.title;
    if (column.sort)
      cell.append(
        button(column.label, () => {
          state.sort = column.sort;
          state.descending = !state.descending;
          return loadTorrents();
        }),
      );
    else cell.textContent = column.label;
    head.append(cell);
  }
  const thead = element("thead");
  thead.append(head);
  t.append(thead);
  const body = element("tbody");
  for (const row of rows) {
    const tr = element("tr");
    tr.dataset.key = row[key];
    if (onRow) {
      tr.onclick = (e) => {
        if (!e.target.closest("button, input, a")) onRow(row);
      };
      if (row[key] === state.current) tr.className = "current";
    }
    if (selection) {
      const cell = element("td"),
        input = document.createElement("input");
      input.type = "checkbox";
      input.checked = selection.has(row[key]);
      input.setAttribute("aria-label", row.name || row.title || row[key]);
      input.onchange = () => {
        input.checked ? selection.add(row[key]) : selection.delete(row[key]);
        if (onChange) onChange();
      };
      cell.append(input);
      tr.append(cell);
    }
    for (const column of columns) {
      const cell = element("td", undefined, column.name ? "name" : "");
      const value = column.render(row);
      if (value instanceof Node) cell.append(value);
      else cell.textContent = value ?? "—";
      if (column.name) cell.title = row.name || row.title;
      tr.append(cell);
    }
    body.append(tr);
  }
  t.append(body);
  host.append(t);
}
async function refreshSetup() {
  state.setup = await api("setup");
  for (const node of document.querySelectorAll("[data-adult]")) node.hidden = !state.setup.adult_content;
  if (!state.clientId) state.clientId = state.setup.client_id;
  const selector = $("target-client");
  selector.replaceChildren(new Option(say("All clients · overview", "Tous les clients · aperçu"), "all"),
    ...state.setup.clients.map(p => new Option(p.name, p.id)));
  selector.value = state.clientId;
  $("connection-status").textContent = state.setup.configured
    ? `${state.setup.name} · ${state.setup.client.toUpperCase()} · ${new URL(state.setup.host).host}`
    : "TORRENTLINKER WEB";
  if (typeof settingsEnvironment === "function") settingsEnvironment();
}
function clearAgentToken() {
  document.dispatchEvent(new Event("tl-settings-clear-secrets"));
}
async function settingsSection(section, detail) {
  state.settingsSection = section === "interface" ? "general" : section;
  rememberTab("setup", state.settingsSection, detail);
  settingsEnvironment();
}

// Only workspace locations belong in the fragment. Form state and filters stay local.
const viewTabs = {
  torrents: [], zen: ["profile", "seeding", "plan", "catalogue", "community"], search: [],
  feeds: [], queue: [], media: ["video", "music"], library: ["reseed", "items", "review", "folders", "activity"],
  upload: ["local", "remote", "sources"], assistant: [], jobs: [], documentation: [],
  setup: ["connections", "clients", "general", "library", "downloads", "paths", "matching", "zen", "interface", "companion", "assistant", "agents"],
};
const agentTabs = ["connections", "new", "activity"];
const mediaViewsByKind = {
  video: ["recent", "continue", "films", "series", "anime", "rated", "unwatched", "all", "adult"],
  music: ["albums", "artists", "tracks"],
};
const rememberedTabs = {};
let activeRoute = "";
function resolveRoute(fragment) {
  const fallback = state.setup?.configured ? ["torrents"] : ["setup", "connections"];
  const parts = fragment.replace(/^#\//, "").split("/");
  const [view, tab, detail] = parts;
  // Incomplete setup selects the landing page; it does not block explicit routes
  // such as configuring the Assistant or reviewing saved Upload drafts.
  if (!fragment.startsWith("#/") || !Object.hasOwn(viewTabs, view)) return fallback;
  const tabs = viewTabs[view];
  const validDetail = view === "setup" && tab === "agents" && agentTabs.includes(detail) ||
    view === "media" && mediaViewsByKind[tab]?.includes(detail) &&
      (detail !== "adult" || state.setup?.adult_content);
  if (parts.length > 3 || (tab !== undefined && !tabs.includes(tab)) ||
      (detail !== undefined && !validDetail)) return fallback;
  const defaultDetail = view === "media" ? mediaViewsByKind[tab || tabs[0]][0] : "connections";
  return tabs.length ? [view, tab || tabs[0], ...(detail && detail !== defaultDetail ? [detail] : [])] : [view];
}
function routeFragment(parts) { return "#/" + parts.join("/"); }
function writeRoute(parts, replace = false) {
  activeRoute = routeFragment(parts);
  if (location.hash === activeRoute) return;
  if (replace) history.replaceState(null, "", activeRoute);
  else location.hash = activeRoute;
}
function rememberTab(view, tab, detail) {
  if (state.view !== view || $("workspace").hidden) return;
  const parts = [view, tab, ...(detail ? [detail] : [])];
  rememberedTabs[view] = parts.slice(1);
  writeRoute(parts);
}
async function openFragment() {
  if ($("workspace").hidden) return;
  const parts = resolveRoute(location.hash);
  const fragment = routeFragment(parts);
  if (location.hash !== fragment) history.replaceState(null, "", fragment);
  if (activeRoute !== fragment) await navigate(...parts);
}
window.addEventListener("hashchange", () => guard(openFragment));
async function navigate(view, section, detail) {
  if (view === "agents") { view = "setup"; section = "agents"; }
  const requested = [view, ...(section ? [section, ...(detail ? [detail] : [])] : rememberedTabs[view] || [])];
  const parts = resolveRoute(routeFragment(requested));
  [view, section, detail] = parts;
  rememberedTabs[view] = parts.slice(1);
  const route = routeFragment(parts);
  writeRoute(parts);
  if (view !== "media" && document.body.classList.contains("media-center-mode")) await mediaExitCenter();
  if (activeRoute !== route) return;
  if (typeof mediaCloseChat === "function" && media.chat) mediaCloseChat();
  state.view = view;
  document.body.classList.toggle("media-view", view === "media");
  document.body.classList.toggle("chat-view", view === "assistant");
  document
    .querySelectorAll(".view")
    .forEach((el) => (el.hidden = el.id !== `view-${view}`));
  document
    .querySelectorAll("[data-view]")
    .forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $("page-title").textContent =
    document.querySelector(`[data-view="${view}"]`)?.textContent || view;
  if (view === "setup") {
    if (state.clientId === "all") state.clientId = state.setup.default_client_id;
    await refreshSetup();
    if (activeRoute !== route) return;
    await settingsSection(section, detail);
  }
  if (view === "assistant") await loadAssistant();
  if (view === "media") {
    media.kind = section;
    media.view = detail || mediaViewsByKind[section][0];
    await loadMedia(); guard(mediaAutoScan);
  }
  if (view !== "setup") clearAgentToken();
  if (view === "documentation") await loadGuides();
  if (view === "torrents") await loadTorrents();
  if (view === "queue") await loadQueue();
  if (view === "feeds") await loadFeeds();
  if (view === "upload") {
    uploadEnvironment(section);
  }
  if (view === "library") await libraryTab(section);
  if (view === "jobs") await loadJobs();
  if (view === "zen") {
    zenTab(section);
    await refreshSetup();
    await Promise.all([loadZenProfile(true), loadZenSeeding(), loadCatalogue(), loadZenPlan()]);
  }
  if (view === "search" && state.setup.indexer_configured) await loadSearchPage();
}
async function job(body, done, failed, progress) {
  body = {client_id: state.clientId, ...body};
  if (body.client_id === "all" && body.kind !== "refresh")
    throw Error(say("Choose a target client first.", "Choisissez un client cible."));
  const r = await api("jobs", body);
  state.jobs.set(r.id, { body, done, failed, progress });
  workStatus("Working…", "En cours…");
  await pollJobs();
  return r.id;
}
function workStatus(en, fr) {
  const status = $("work-status");
  status.dataset.en = en;
  status.dataset.fr = fr;
  status.textContent = say(en, fr);
}
async function pollJobs() {
  if ($("workspace").hidden) return;
  const rows = await api("jobs");
  catalogueJobs(rows);
  planJobs(rows);
  let running = 0;
  for (const row of rows) {
    if (["running", "queued"].includes(row.status)) running++;
    const pending = state.jobs.get(row.id);
    if (pending?.progress && pending.body.client_id === state.clientId && row.progress) pending.progress(row.progress);
    if (pending && !["running", "queued"].includes(row.status)) {
      state.jobs.delete(row.id);
      const full = await api(`jobs/${row.id}`);
      if (["completed", "partial"].includes(full.status)) {
        if (pending.done && (pending.body.client_id === state.clientId || ["enqueue", "configure-download-folder", "catalogue"].includes(pending.body.kind))) await pending.done(full.result);
        if (pending.body.kind === "refresh" && pending.body.client_id === state.clientId && state.view === "zen") await loadZenSeeding();
        if (full.status === "partial") toast(say("Scan incomplete. Some paths could not be read; previous items were kept. See job details.", "Analyse incomplète. Certains chemins sont inaccessibles ; les éléments précédents ont été conservés. Consultez les détails de la tâche."));
      } else {
        if (pending.body.kind === "refresh" && pending.body.client_id === state.clientId && state.view === "zen") await loadZenSeeding();
        if (pending.failed && (pending.body.client_id === state.clientId || ["configure-download-folder", "catalogue"].includes(pending.body.kind))) await pending.failed(full.error, full.result);
        toast(full.error || say("Job cancelled", "Tâche annulée"));
      }
    }
  }
  if (running) workStatus(`${running} active job(s)`, `${running} tâche(s) active(s)`);
  else if (rows.find(row => row.kind === "scan" && row.client_id === state.clientId)?.status === "partial")
    workStatus("Scan incomplete · see jobs", "Analyse incomplète · voir les tâches");
  else workStatus("Up to date", "À jour");
  if (state.view === "jobs") renderJobs(rows);
  if (state.view === "queue") await loadQueue();
  if (state.view === "library" && !$("library-reseed").hidden && reseedUI.job) await loadReseed();
}
async function loadJobs() {
  renderJobs(await api("jobs"));
}
function renderJobs(rows) {
  const clientName = id => state.setup?.clients?.find(p => p.id === id)?.name || id;
  $("job-list").replaceChildren(
    ...rows.map((r) => {
      const card = element("div", undefined, "card job"),
        text = element("div");
      text.append(
        element("strong", `${r.kind} · ${clientName(r.client_id)}`),
        element("p", r.status),
        element("small", r.error || (r.progress?.stage === "client-files"
          ? say(`Reading client files: ${r.progress.done}/${r.progress.total} · up to ${Number(r.progress.requests_per_second).toFixed(2)} requests/s`,
              `Lecture des fichiers du client : ${r.progress.done}/${r.progress.total} · jusqu’à ${Number(r.progress.requests_per_second).toFixed(2)} requêtes/s`)
          : JSON.stringify(r.progress || {}))),
      );
      card.append(text);
      if (["queued", "running"].includes(r.status) && r.progress?.cancellable !== false)
        card.append(
          button(say("Stop", "Arrêter"), () => api(`jobs/${r.id}/cancel`, {})),
        );
      else
        card.append(
          button(say("Details", "Détails"), async () => {
            const full = await api(`jobs/${r.id}`);
            $("dialog-content").replaceChildren(
              element("h2", r.kind),
              element(
                "pre",
                JSON.stringify(full.result || full.error, null, 2),
              ),
            );
            $("dialog").showModal();
          }),
        );
      return card;
    }),
  );
}
function options(select, values, label) {
  const old = select.value;
  select.replaceChildren(
    new Option(label, ""),
    ...values.map((v) => new Option(v, v)),
  );
  select.value = old;
}
function duration(seconds) {
  const d = Math.floor(seconds / 86400), h = Math.floor((seconds % 86400) / 3600), m = Math.floor((seconds % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}
const statusLabel = (s) =>
  ({
    downloading: say("Downloading", "Téléchargement"),
    seeding: say("Seeding", "En partage"),
    paused: say("Paused", "En pause"),
    checking: say("Checking", "Vérification"),
    error: say("Error", "Erreur"),
    other: say("Other", "Autre"),
  })[s] || s;
function searchColumns() {
  return [
    {
      label: "Torrent",
      name: true,
      render: (r) => button(r.title, () => details(r)),
    },
    { label: say("Size", "Taille"), render: (r) => bytes(r.size) },
    { label: "Seeds", render: (r) => r.seeders },
    { label: "≈ Zen / j", render: (r) => num(r.zen) },
    { label: "≈ Note", render: (r) => num(r.note) },
    { label: say("Age", "Âge"), render: (r) => age(r.published_at) },
  ];
}
async function enqueue(hashes) {
  if (!hashes.length)
    throw Error(say("Select torrents first.", "Sélectionnez des torrents."));
  await job({ kind: "enqueue", hashes }, async () => {
    toast(
      say("Added to download queue.", "Ajouté à la file de téléchargement."),
    );
    await navigate("queue");
  });
}
async function details(row) {
  await navigate("search");
  searchFrame.contentWindow.postMessage({type:"search-open-detail", row}, location.origin);
}
// Library batch actions, as on the desktop: they use the Candidates earlier searches found.
async function checkAllCandidates() {
  await job({ kind: "check-all" }, async (r) => {
    toast(say(
      `Checked ${r.items} Local Items: ${r.full} full, ${r.partial} partial, ${r.none} without a Match, ${r.archive} in archives.`,
      `${r.items} éléments vérifiés : ${r.full} complètes, ${r.partial} partielles, ${r.none} sans correspondance, ${r.archive} dans des archives.`,
    ));
    await loadLibrary();
  });
}
async function reseedAllMatches() {
  if (!confirm(say(
    "Reseed every confirmed Full Match across the Library? Archives and disk renames are left for each item's own review.",
    "Remettre en seed toutes les correspondances complètes de la bibliothèque ? Les archives et les renommages sur disque restent à traiter élément par élément.",
  ))) return;
  await job({ kind: "reseed-all" }, (r) => toast(say(
    `${r.started} verifications started, ${r.already_present} already in the client, ${r.skipped} left for review.`,
    `${r.started} vérifications lancées, ${r.already_present} déjà dans le client, ${r.skipped} à traiter à la main.`,
  )));
}
async function enter() {
  await refreshSetup();
  $("logout").hidden = state.setup.web_auth === "proxy";
  $("login-screen").hidden = true;
  $("workspace").hidden = false;
  const parts = resolveRoute(location.hash);
  writeRoute(parts, true);
  await navigate(...parts);
  if (state.setup.configured) await job({ kind: "refresh" }, loadTorrents);
  await pollJobs();
}
$("login-form").onsubmit = (e) => {
  e.preventDefault();
  guard(async () => {
    await api("login", { password: $("login-password").value });
    $("login-password").value = "";
    await enter();
  });
};
document
  .querySelectorAll("[data-view]")
  .forEach((b) => (b.onclick = () => guard(() => navigate(b.dataset.view))));
$("logout").onclick = () =>
  guard(async () => {
    await api("logout", {});
    state.jobs.clear();
    clearAgentToken();
    $("workspace").hidden = true;
    $("login-screen").hidden = false;
  });
$("theme").value = localStorage.getItem("tl-theme") || "auto";
function theme() {
  const value = $("theme").value;
  document.documentElement.dataset.theme = value === "auto"
    ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    : value;
  localStorage.setItem("tl-theme", value);
}
$("theme").onchange = theme;
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", theme);
theme();
$("language").onchange = () => {
  language = $("language").value;
  localStorage.setItem("tl-language", language);
  translate();
  document.dispatchEvent(new Event("tl-language-changed"));
  if (state.view === "zen") { guard(loadZenSeeding); planEnvironment(); if (profileState) showZenProfile(profileState); }
  if (state.view === "search") searchRetranslate();
  if (state.view === "upload") uploadEnvironment();
  if (state.view === "torrents") guard(loadTorrents);
  if (state.view === "media") { guard(loadMedia); mediaQueueRender(); }
  $("page-title").textContent =
    document.querySelector(`[data-view="${state.view}"]`)?.textContent ||
    state.view;
};
translate();
setInterval(() => {
  if (!$("workspace").hidden) guard(pollJobs);
}, 2000);
setInterval(() => {
  if (
    !$("workspace").hidden &&
    state.setup?.configured &&
    state.view === "zen" &&
    !state.jobs.size
  )
    guard(() => job({ kind: "refresh" }, loadTorrents));
}, 15000);
document.addEventListener("DOMContentLoaded", () => guard(async () => {
  try {
    await api("setup");
    await enter();
  } catch (error) {
    if (!error.message.includes("Sign in")) toast(error.message);
  }
}));

$("target-client").onchange = () => guard(async () => {
  state.clientId = $("target-client").value;
  uploadEnvironment();
  state.selected.clear(); state.queueSelected.clear();
  state.offset = 0; state.libraryOffset = 0; state.localItem = "";
  await refreshSetup();
  await navigate(state.clientId === "all" && state.view !== "zen" ? "torrents" : state.view);
  if (state.setup.configured && state.view !== "media") await job({kind: "refresh"}, state.view === "zen" ? loadZenSeeding : loadTorrents);
});
$("navigation-toggle").onclick = () => {
  const collapsed = document.body.classList.toggle("navigation-collapsed");
  $("navigation-toggle").setAttribute("aria-expanded", String(!collapsed));
};

if (matchMedia("(max-width: 1050px)").matches) {
  document.body.classList.add("navigation-collapsed");
  $("navigation-toggle").setAttribute("aria-expanded", "false");
}


$("navigation-close").onclick = () => {
  document.body.classList.add("navigation-collapsed");
  $("navigation-toggle").setAttribute("aria-expanded", "false");
  $("navigation-toggle").focus();
};

async function waitForJob(identifier) {
  while (true) {
    const result = await api(`jobs/${identifier}`);
    if (result.status === "completed") return;
    if (!["queued", "running"].includes(result.status))
      throw Error(result.error || say("Job cancelled", "Tâche annulée"));
    await new Promise(resolve => setTimeout(resolve, 500));
  }
}
