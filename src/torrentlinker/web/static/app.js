"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  view: "torrents",
  setup: null,
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
  planSelected: new Set(),
  jobs: new Map(),
  searchRows: [],
  planRows: [],
  localItem: "",
};
const french = {
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
  agentDailyCount: "Torrents par jour", agentReserve: "Espace à conserver (Gio)",
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
  depth: "Profondeur d’analyse",
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
  const scoped = ["setup", "torrents", "library", "queue", "upload/queue"];
  if (body === undefined && scoped.includes(path.split("?")[0]) && state.clientId) {
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
      $("workspace").hidden = true;
      $("login-screen").hidden = false;
    }
    throw Error(result.detail || "Request failed");
  }
  return result;
}
const bytes = (n) => {
  if (n === null || n === undefined) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let i = 0;
  while (n >= 1024 && i < 4) {
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
function table(target, rows, columns, selection, key = "hash") {
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
      table(target, rows, columns, selection, key);
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
    if (selection) {
      const cell = element("td"),
        input = document.createElement("input");
      input.type = "checkbox";
      input.checked = selection.has(row[key]);
      input.setAttribute("aria-label", row.name || row.title || row[key]);
      input.onchange = () =>
        input.checked ? selection.add(row[key]) : selection.delete(row[key]);
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
function step(name) {
  document
    .querySelectorAll(".setup-step")
    .forEach((el) => (el.hidden = el.id !== `step-${name}`));
  document
    .querySelectorAll(".steps button")
    .forEach((b) => b.classList.toggle("active", b.dataset.step === name));
  if (name === "ready") renderCapabilities();
}
async function refreshSetup() {
  state.setup = await api("setup");
  if (!state.clientId) state.clientId = state.setup.client_id;
  const selector = $("target-client");
  selector.replaceChildren(new Option(say("All clients · overview", "Tous les clients · aperçu"), "all"),
    ...state.setup.clients.map(p => new Option(p.name, p.id)));
  selector.value = state.clientId;
  const oldCategory = $("plan-category").value;
  $("plan-category").replaceChildren(new Option(say("All categories", "Toutes les catégories"), ""));
  const categories = Object.entries(state.setup.indexer_categories || {});
  const appendCategory = (id, category, depth = 0, visited = new Set()) => {
    if (visited.has(id)) return;
    visited.add(id);
    $("plan-category").append(new Option("　".repeat(depth) + category.name, id));
    for (const [child, value] of categories.filter(([, v]) => String(v.parent) === id)) appendCategory(child, value, depth + 1, visited);
  };
  for (const [id, category] of categories.filter(([, c]) => !c.parent || !categories.some(([key]) => key === String(c.parent)))) appendCategory(id, category);
  $("plan-category").value = [...$("plan-category").options].some(o => o.value === oldCategory) ? oldCategory : "";
  $("client-name").value = state.setup.name;
  $("plan-clients").replaceChildren(...state.setup.clients.filter(p => p.enabled).map(p => {
    const row = element("label");
    const check = document.createElement("input"); check.type = "checkbox";
    check.dataset.clientId = p.id; check.checked = p.id === state.setup.client_id;
    const budget = document.createElement("input"); budget.type = "number"; budget.min = "0"; budget.value = "0";
    budget.dataset.budgetId = p.id; budget.setAttribute("aria-label", p.name + " · GiB");
    row.append(check, document.createTextNode(p.name + " · GiB"), budget); return row;
  }));
  $("client-kind").value = state.setup.client;
  $("client-host").value = state.setup.host;
  $("client-username").value = state.setup.username;
  $("indexer-url").value = state.setup.indexer_url;
  $("connection-status").textContent = state.setup.configured
    ? `${state.setup.name} · ${state.setup.client.toUpperCase()} · ${new URL(state.setup.host).host}`
    : "TORRENTLINKER WEB";
  $("saved-folders").replaceChildren(
    ...state.setup.folders.map((f) =>
      savedFolder(f.local, "library", `${f.local} · ${f.kind} · ${f.depth}`),
    ),
  );
  if (state.setup.download_folder)
    $("saved-folders").append(
      savedFolder(
        state.setup.download_folder,
        "download",
        `${say("Downloads", "Téléchargements")} · ${state.setup.download_folder}`,
      ),
    );
  $("proxy-address").value = state.setup.proxy.address;
  $("proxy-username").value = state.setup.proxy.username;
  $("proxy-client").checked = state.setup.proxy.torrent_client;
  clientKind();
  renderCapabilities();
}
function savedFolder(local, purpose, label) {
  const row = element("div", undefined, "toolbar");
  row.append(
    element("span", label),
    button(say("Remove folder", "Retirer ce dossier"), async () => {
      await api("setup/remove-folder", { local, purpose });
      await refreshSetup();
    }),
  );
  return row;
}
function renderCapabilities() {
  if (!state.setup) return;
  const features = [
    [
      say("Torrent management", "Gestion des torrents"),
      state.setup.capabilities.manage,
    ],
    [
      say("Search and Zen profile", "Recherche et profil Zen"),
      state.setup.indexer_configured,
    ],
    [
      say("Library scanning and reseeding", "Analyse et reseed"),
      state.setup.capabilities.scan,
    ],
    [
      say("Downloads and planning", "Téléchargements et planification"),
      state.setup.capabilities.download,
    ],
  ];
  $("capabilities").replaceChildren(
    ...features.map(([label, ready]) => {
      const row = element("div", undefined, "capability");
      row.append(
        element("span", ready ? "✓" : "○"),
        element("span", label),
        element(
          "small",
          ready
            ? say("Ready", "Prêt")
            : say("Needs configuration", "À configurer"),
        ),
      );
      return row;
    }),
  );
}
function clientKind() {
  $("username-label").hidden = $("client-kind").value === "deluge";
  $("client-key").parentElement.hidden =
    $("client-kind").value !== "qbittorrent";
}
function connection() {
  return {
    ...(state.addingClient ? {password: $("client-password").value, api_key: $("client-key").value} : {}),
    name: $("client-name").value.trim(),
    client: $("client-kind").value,
    host: $("client-host").value,
    username: $("client-username").value,
    ...($("client-password").value
      ? { password: $("client-password").value }
      : {}),
    ...($("client-key").value ? { api_key: $("client-key").value } : {}),
  };
}
function folder() {
  return {
    local: $("folder-local").value,
    client_path: $("folder-client").value,
    purpose: $("folder-purpose").value,
    kind: $("folder-kind").value,
    depth: Number($("folder-depth").value),
  };
}
function indexer() {
  return {
    url: $("indexer-url").value,
    ...($("indexer-key").value ? { api_key: $("indexer-key").value } : {}),
  };
}
function showFolders(rows) {
  $("import-folders").replaceChildren(
    ...rows
      .filter((f) => f.path)
      .map((f) =>
        button(
          `${f.name || say("Default folder", "Dossier par défaut")} · ${f.path}`,
          () => {
            $("folder-client").value = f.path;
            if (state.setup.storage_roots.includes(f.path))
              $("folder-local").value = f.path;
          },
        ),
      ),
  );
}
async function testClient(save = false) {
  $("client-result").textContent = say("Connecting…", "Connexion…");
  try {
    const result = await api(
      save && state.addingClient ? "clients" : `setup/${save ? "client" : "test-client"}`,
      connection(),
    );
    $("client-result").textContent = `✓ ${result.version}\n${result.warning}`;
    showFolders(result.folders);
    if (save) {
      if (result.client_id) state.clientId = result.client_id;
      state.addingClient = false;
      $("client-password").value = "";
      $("client-key").value = "";
      await refreshSetup();
      step("storage");
    }
  } catch (e) {
    $("client-result").textContent = e.message;
    throw e;
  }
}
async function testFolder(save = false) {
  const r = await api(`setup/${save ? "folder" : "test-folder"}`, folder());
  $("folder-result").textContent = r.sample
    ? `${r.sample.local}\n→ ${r.sample.client}\n✓ ${say("Matching file and size", "Même fichier, même taille")}`
    : r.warning;
  if (save) await refreshSetup();
}
async function testIndexer(save = false) {
  $("indexer-result").textContent = say(
    "Checking key…",
    "Vérification de la clé…",
  );
  const r = await api(`setup/${save ? "indexer" : "test-indexer"}`, indexer());
  $("indexer-result").textContent =
    `✓ ${r.categories} ${say("categories", "catégories")}`;
  if (save) {
    $("indexer-key").value = "";
    await refreshSetup();
    step("ready");
  }
}
async function browse(path = "") {
  const r = await api(`folders?${new URLSearchParams({ path })}`),
    content = $("dialog-content");
  content.replaceChildren(
    element("h2", say("Folders on this server", "Dossiers de ce serveur")),
    element(
      "p",
      r.path || say("Configured storage roots", "Stockages configurés"),
    ),
  );
  if (r.path)
    content.append(
      button(
        say("Use this folder", "Utiliser ce dossier"),
        () => {
          $("folder-local").value = r.path;
          $("dialog").close();
        },
        "primary",
      ),
    );
  if (r.path) content.append(button("↑", () => browse(r.parent)));
  for (const path of r.folders)
    content.append(button(path, () => browse(path), "directory-button"));
  if (!r.folders.length && !r.path)
    content.append(
      element(
        "p",
        say(
          "No storage roots configured. Mount your media and set TL_STORAGE_ROOTS on the server. Remote torrent management is still available.",
          "Aucun stockage configuré. Montez vos médias et définissez TL_STORAGE_ROOTS sur le serveur. La gestion distante des torrents reste disponible.",
        ),
      ),
    );
  if (!$("dialog").open) $("dialog").showModal();
}
async function navigate(view) {
  state.view = view;
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
    await refreshSetup();
    step("client");
  }
  if (view === "agents") await loadAgents();
  if (view === "assistant") await loadAssistant();
  if (view !== "agents") { $("agent-token").value = ""; $("agent-token-box").hidden = true; }
  if (view === "documentation") await loadGuides();
  if (view === "torrents") await loadTorrents();
  if (view === "queue") await loadQueue();
  if (view === "upload") await loadUploadQueue();
  if (view === "library") await loadLibrary();
  if (view === "jobs") await loadJobs();
  if (view === "zen") {
    await refreshSetup();
    await Promise.all([loadZenSeeding(), api("zen/catalogue").then(showCatalogue)]);
  }
  if (
    view === "search" &&
    state.setup.indexer_configured &&
    !$("search-category").dataset.loaded
  )
    await searchOptions();
}
async function job(body, done) {
  body = {client_id: state.clientId, ...body};
  if (body.client_id === "all" && body.kind !== "refresh")
    throw Error(say("Choose a target client first.", "Choisissez un client cible."));
  const r = await api("jobs", body);
  state.jobs.set(r.id, { body, done });
  $("work-status").textContent = say("Working…", "En cours…");
  await pollJobs();
  return r.id;
}
async function pollJobs() {
  if ($("workspace").hidden) return;
  const rows = await api("jobs");
  let running = 0;
  for (const row of rows) {
    if (["running", "queued"].includes(row.status)) running++;
    const pending = state.jobs.get(row.id);
    if (pending && !["running", "queued"].includes(row.status)) {
      state.jobs.delete(row.id);
      const full = await api(`jobs/${row.id}`);
      if (["completed", "partial"].includes(full.status)) {
        if (pending.done && (pending.body.client_id === state.clientId || pending.body.kind === "enqueue")) await pending.done(full.result);
        if (full.status === "partial") toast(say("Scan incomplete. Some paths could not be read; previous items were kept. See job details.", "Analyse incomplète. Certains chemins sont inaccessibles ; les éléments précédents ont été conservés. Consultez les détails de la tâche."));
      } else {
        if (pending.body.kind === "refresh" && pending.body.client_id === state.clientId && state.view === "zen") await loadZenSeeding();
        toast(full.error || say("Job cancelled", "Tâche annulée"));
      }
    }
  }
  $("work-status").textContent = running
    ? `${running} ${say("active job(s)", "tâche(s) active(s)")}`
    : rows.find(row => row.kind === "scan" && row.client_id === state.clientId)?.status === "partial"
      ? say("Scan incomplete · see jobs", "Analyse incomplète · voir les tâches")
      : say("Up to date", "À jour");
  if (state.view === "jobs") renderJobs(rows);
  if (state.view === "queue") await loadQueue();
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
        element("small", r.error || JSON.stringify(r.progress || {})),
      );
      card.append(text);
      if (["queued", "running"].includes(r.status))
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
async function loadTorrents() {
  const params = new URLSearchParams({
    q: $("torrent-query").value,
    offset: state.offset,
    sort: state.sort,
    descending: state.descending,
    tracker: $("torrent-tracker").value,
    state: $("torrent-state").value,
    category: $("torrent-category").value,
  });
  const r = await api(`torrents?${params}`);
  options(
    $("torrent-tracker"),
    r.trackers,
    say("All trackers", "Tous les trackers"),
  );
  options(
    $("torrent-category"),
    r.categories,
    say("All categories", "Toutes les catégories"),
  );
  const labels = [
    ["client_name", say("Client", "Client"), (v) => v.client_name],
    ["name", say("Torrent", "Torrent"), (v) => v.name],
    ["status", say("Status", "État"), (v) => v.status],
    ["progress", "%", (v) => (v.progress * 100).toFixed(1)],
    ["size", say("Size", "Taille"), (v) => bytes(v.size)],
    ["seeds", say("Seeds", "Seeders"), (v) => `${v.seeds >= 0 ? v.seeds : "?"} (${v.total_seeds >= 0 ? v.total_seeds : "?"})`],
    ["peers", say("Peers", "Pairs"), (v) => `${v.peers >= 0 ? v.peers : "?"} (${v.total_peers >= 0 ? v.total_peers : "?"})`],
    ["download", "↓ / s", (v) => bytes(v.download)],
    ["upload", "↑ / s", (v) => bytes(v.upload)],
    ["ratio", "Ratio", (v) => num(v.ratio)],
    ["zen", "≈ Zen / j", (v) => num(v.zen) + (v.provisional ? " *" : "")],
    ["note", "≈ Note", (v) => num(v.note) + (v.provisional ? " *" : "")],
  ];
  table(
    "torrent-table",
    r.rows,
    labels.map(([key, label, render]) => ({
      label,
      render,
      title: ["seeds", "peers"].includes(key) ? say(
        "Connected (swarm total). ? = unknown. Sorted by total when known.",
        "Connectés (total de l'essaim). ? = inconnu. Tri par total lorsqu'il est connu.",
      ) : "",
      sort: key,
      name: key === "name",
    })),
    state.selected,
  );
  $("torrent-count").textContent =
    `${r.total} torrents · ${Math.floor(state.offset / 100) + 1}` + (r.client_errors?.length ? " · " + r.client_errors.map(e => `${e.name}: ${e.message}`).join(" · ") : "");
  $("torrent-prev").disabled = !state.offset;
  $("torrent-next").disabled = state.offset + 100 >= r.total;
  $("zen-daily").textContent = num(r.zen.daily);
  $("zen-count").textContent = r.zen.count ?? "—";
}
async function manage(action) {
  if (state.clientId === "all") throw Error(say("Choose a client to manage its torrents.", "Choisissez un client pour gérer ses torrents."));
  const hashes = [...state.selected];
  if (!hashes.length)
    throw Error(say("Select torrents first.", "Sélectionnez des torrents."));
  const body = { kind: "manage", action, hashes, client_id: state.clientId };
  if (["delete", "remove"].includes(action)) {
    const preview = await api("confirm", body),
      content = $("dialog-content");
    content.replaceChildren(
      element(
        "h2",
        action === "delete"
          ? say("Delete files?", "Supprimer les fichiers ?")
          : say("Remove torrents?", "Retirer les torrents ?"),
      ),
      element("p", preview.warning),
    );
    const list = element("ul");
    preview.torrents.forEach((t) =>
      list.append(element("li", `${t.name} · ${t.folder}`)),
    );
    content.append(
      list,
      button(say("Cancel", "Annuler"), () => $("dialog").close()),
      button(
        say("Confirm", "Confirmer"),
        async () => {
          await job({ ...body, confirmation: preview.token }, () =>
            job({ kind: "refresh" }, loadTorrents),
          );
          $("dialog").close();
        },
        "danger",
      ),
    );
    $("dialog").showModal();
    content.querySelector("button").focus();
    return;
  }
  await job(body, () => job({ kind: "refresh" }, loadTorrents));
}
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
async function searchOptions() {
  await job(
    {
      kind: "search-options",
      category: Number($("search-category").value) || null,
    },
    (r) => {
      const old = $("search-category").value;
      const categories = r.categories;
      $("search-category").replaceChildren(
        new Option(say("All categories", "Toutes les catégories"), ""),
      );
      for (const [id, c] of Object.entries(categories).filter(
        ([, v]) => !v.parent,
      )) {
        $("search-category").append(new Option(c.name, id));
        for (const [child, v] of Object.entries(categories).filter(
          ([, v]) => String(v.parent) === id,
        ))
          $("search-category").append(new Option(`　↳ ${v.name}`, child));
      }
      $("search-category").value = old;
      $("search-category").dataset.loaded = "1";
      $("search-facets").replaceChildren(
        ...r.facets.map((f) => {
          const label = element("label", f.label),
            select = element("select");
          select.dataset.facet = f.slug;
          select.append(
            new Option("—", ""),
            ...f.choices.map(([name, id]) => new Option(name, id)),
          );
          label.append(select);
          return label;
        }),
      );
    },
  );
}
async function search(page = 1) {
  const filters = {};
  const choices = [...$("search-facets").querySelectorAll("select")]
    .map((s) => s.value)
    .filter(Boolean);
  if (choices.length) filters.options = choices.join(",");
  if ($("search-year").value) filters.year = $("search-year").value;
  if ($("search-uploader").value) filters.uploader = $("search-uploader").value;
  if ($("search-palliative").checked) filters.palliative = "true";
  if ($("search-exclusive").checked) filters.exclusive = "true";
  await job(
    {
      kind: "search",
      query: $("search-query").value,
      page,
      category: Number($("search-category").value) || null,
      filters,
    },
    (r) => {
      state.searchPage = r.page;
      state.searchPages = r.pages;
      state.searchRows = r.rows;
      state.searchSelected.clear();
      table("search-table", r.rows, searchColumns(), state.searchSelected);
      $("search-count").textContent = `${r.page} / ${Math.max(1, r.pages)}`;
      $("search-prev").disabled = r.page <= 1;
      $("search-next").disabled = r.page >= r.pages;
    },
  );
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
function showCatalogue(r) {
  const parts = [
    `${r.count} torrents`,
    say(
      "Coverage is not guaranteed complete.",
      "La couverture complète n’est pas garantie.",
    ),
  ];
  if (r.updated_at)
    parts.push(`${say("Updated", "Actualisé")} · ${age(r.updated_at)}`);
  if (r.limited_categories.length)
    parts.push(
      say(
        "Indexer paging limit reached.",
        "Limite de pagination de l’indexeur atteinte.",
      ),
    );
  if (r.paused)
    parts.push(
      say("Historical fetch paused.", "Récupération de l’historique en pause."),
    );
  if (r.snapshot_imported_at)
    parts.push(
      say(
        "Includes Zen Lab baseline metadata; direct c411 data takes priority.",
        "Inclut les métadonnées de base Zen Lab ; les données c411 sont prioritaires.",
      ),
    );
  $("catalogue-status").textContent = parts.join(" · ");
}
async function loadQueue() {
  const clientId = state.clientId;
  const rows = await api("queue");
  if (clientId !== state.clientId) return;
  const snapshot = JSON.stringify([clientId, language, rows]);
  if (state.queueSnapshot === snapshot) return;
  state.queueSnapshot = snapshot;
  table(
    "queue-table",
    rows,
    [
      { label: "Torrent", name: true, render: (r) => r.title },
      { label: "Client", render: (r) => r.client_name },
      { label: say("Size", "Taille"), render: (r) => bytes(r.size) },
      { label: "≈ Zen / j", render: (r) => num(r.zen) },
      { label: "≈ Note", render: (r) => num(r.note) },
      { label: say("Folder", "Dossier"), render: (r) => r.folder },
      { label: say("Status", "État"), render: (r) => r.status === "uncertain" ? say("Check Torrent Client before retrying", "Vérifier le client torrent avant de réessayer") : r.status },
      { label: say("Details", "Détails"), render: (r) => r.status === "uncertain" ? say("Check the Torrent Client before removing and queueing this entry again.", "Vérifier le client torrent avant de retirer et remettre cette entrée en file.") : r.reason },
    ],
    state.queueSelected,
    "key",
  );
}
async function details(row) {
  const content = $("dialog-content");
  content.replaceChildren(
    element("h2", row.title),
    element(
      "p",
      `${bytes(row.size)} · ${row.seeders} seeds · ≈ ${num(row.zen)} Zen / j`,
    ),
  );
  if (row.website && /^https?:\/\//.test(row.website)) {
    const link = element("a", say("Open on website", "Ouvrir sur le site"));
    link.href = row.website;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    content.append(link);
  }
  content.append(
    button(say("Add to queue", "Ajouter à la file"), () => enqueue([row.hash])),
  );
  $("dialog").showModal();
  if (new URL(state.setup.indexer_url).hostname !== "c411.org") return;
  await job({ kind: "details", hashes: [row.hash] }, (r) => {
    if (!$("dialog").open) return;
    const description = element("div", undefined, "description");
    description.innerHTML = r.description;
    description.querySelectorAll("a").forEach((a) => {
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    });
    content.append(description);
    if (r.nfo) {
      const d = element("details");
      d.append(element("summary", "NFO"), element("pre", r.nfo));
      content.append(d);
    }
    if (r.images.length) {
      const links = element("details");
      links.append(
        element(
          "summary",
          say("Images on the host website", "Images sur le site hébergeur"),
        ),
      );
      r.images.forEach((url) => {
        if (!/^https?:\/\//.test(url)) return;
        const a = element("a", url);
        a.href = url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        const p = element("p");
        p.append(a);
        links.append(p);
      });
      content.append(links);
    }
  });
}
async function loadLibrary() {
  const r = await api(
    `library?${new URLSearchParams({ q: $("library-query").value, offset: state.libraryOffset })}`,
  );
  table(
    "library-table",
    r.rows,
    [
      {
        label: say("Local Item", "Élément local"),
        name: true,
        render: (r) => r.name,
      },
      { label: say("State", "État"), render: (r) => r.state },
      { label: say("Size", "Taille"), render: (r) => bytes(r.size) },
      { label: say("Folder", "Dossier"), render: (r) => r.folder },
      {
        label: "",
        render: (r) =>
          button(say("Find candidates", "Chercher des candidats"), () =>
            check(r),
          ),
      },
      {
        label: "Upload",
        render: (r) =>
          button(say("Prepare", "Préparer"), () => prepareUpload(r)),
      },
    ],
    null,
  );
  $("library-count").textContent =
    `${r.total} · ${Math.floor(state.libraryOffset / 100) + 1}`;
  $("library-prev").disabled = !state.libraryOffset;
  $("library-next").disabled = state.libraryOffset + 100 >= r.total;
}
async function check(row) {
  state.localItem = row.path;
  $("candidates").hidden = false;
  $("candidate-title").textContent = row.name;
  await job({ kind: "check", path: row.path }, (r) =>
    table(
      "candidate-table",
      r,
      [
        { label: "Torrent", name: true, render: (c) => c.title },
        { label: say("Match", "Correspondance"), render: (c) => c.match },
        {
          label: "",
          render: (c) => {
            const b = button("Reseed", () =>
              job({ kind: "reseed", path: row.path, hashes: [c.hash] }, () =>
                toast(say("Verification started.", "Vérification lancée.")),
              ),
            );
            b.disabled = c.match === "none" || c.archive;
            return b;
          },
        },
      ],
      null,
    ),
  );
}
async function enter() {
  await refreshSetup();
  $("login-screen").hidden = true;
  $("workspace").hidden = false;
  await navigate(state.setup.configured ? "torrents" : "setup");
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
$("client-form").onsubmit = (e) => {
  e.preventDefault();
  guard(() => testClient(true));
};
$("test-client").onclick = () => guard(() => testClient());
$("client-kind").onchange = clientKind;
$("folder-form").onsubmit = (e) => {
  e.preventDefault();
  guard(() => testFolder(true));
};
$("test-folder").onclick = () => guard(() => testFolder());
$("browse").onclick = () => guard(() => browse());
$("indexer-form").onsubmit = (e) => {
  e.preventDefault();
  guard(() => testIndexer(true));
};
$("test-indexer").onclick = () => guard(() => testIndexer());
$("finish-setup").onclick = () =>
  guard(async () => {
    await navigate("torrents");
    if (state.setup.configured) await job({ kind: "refresh" }, loadTorrents);
  });
document
  .querySelectorAll("[data-view]")
  .forEach((b) => (b.onclick = () => guard(() => navigate(b.dataset.view))));
document
  .querySelectorAll("[data-step]")
  .forEach((b) => (b.onclick = () => step(b.dataset.step)));
document
  .querySelectorAll("[data-action]")
  .forEach((b) => (b.onclick = () => guard(() => manage(b.dataset.action))));
$("logout").onclick = () =>
  guard(async () => {
    await api("logout", {});
    state.jobs.clear();
    $("workspace").hidden = true;
    $("login-screen").hidden = false;
  });
$("theme").value = localStorage.getItem("tl-theme") || "auto";
function theme() {
  const value = $("theme").value;
  document.documentElement.dataset.theme = value;
  localStorage.setItem("tl-theme", value);
}
$("theme").onchange = theme;
theme();
$("language").onchange = () => {
  if (state.view === "documentation") setTimeout(() => guard(loadGuides), 0);
  language = $("language").value;
  localStorage.setItem("tl-language", language);
  translate();
  if (state.view === "zen") guard(loadZenSeeding);
  $("page-title").textContent =
    document.querySelector(`[data-view="${state.view}"]`)?.textContent ||
    state.view;
};
translate();
$("refresh").onclick = () =>
  guard(() => job({ kind: "refresh" }, loadTorrents));
let filterTimer;
function filter() {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(() => {
    state.offset = 0;
    guard(loadTorrents);
  }, 250);
}
$("torrent-query").oninput = filter;
["torrent-state", "torrent-tracker", "torrent-category"].forEach(
  (id) => ($(id).onchange = filter),
);
$("torrent-prev").onclick = () => {
  state.offset = Math.max(0, state.offset - 100);
  guard(loadTorrents);
};
$("torrent-next").onclick = () => {
  state.offset += 100;
  guard(loadTorrents);
};
$("search-form").onsubmit = (e) => {
  e.preventDefault();
  guard(() => search());
};
$("search-category").onchange = () => guard(searchOptions);
$("search-prev").onclick = () =>
  guard(() => search(Math.max(1, state.searchPage - 1)));
$("search-next").onclick = () => guard(() => search(state.searchPage + 1));
$("queue-search").onclick = () =>
  guard(() => enqueue([...state.searchSelected]));
$("queue-plan").onclick = () => guard(async () => {
  const grouped = new Map();
  for (const row of state.planRows.filter(r => state.planSelected.has(r.hash))) {
    const id = row.client_id || state.clientId;
    if (!grouped.has(id)) grouped.set(id, []);
    grouped.get(id).push(row.hash);
  }
  $("queue-plan").disabled = true;
  try {
    for (const [id, hashes] of grouped) {
      for (let offset = 0; offset < hashes.length; offset += 1000) {
        const identifier = await job({kind: "enqueue", hashes: hashes.slice(offset, offset + 1000), client_id: id}, loadQueue);
        await waitForJob(identifier);
      }
    }
    await navigate("queue");
  } finally { $("queue-plan").disabled = false; }
});
$("start-queue").onclick = () =>
  guard(() => job({ kind: "send-queue" }, loadQueue));
$("remove-queue").onclick = () =>
  guard(async () => {
    await api("queue/remove", [...state.queueSelected]);
    state.queueSelected.clear();
    await loadQueue();
  });
$("scan").onclick = () => guard(() => job({ kind: "scan" }, loadLibrary));
$("library-query").oninput = () => {
  state.libraryOffset = 0;
  guard(loadLibrary);
};
$("library-prev").onclick = () => {
  state.libraryOffset = Math.max(0, state.libraryOffset - 100);
  guard(loadLibrary);
};
$("library-next").onclick = () => {
  state.libraryOffset += 100;
  guard(loadLibrary);
};
$("catalogue").onclick = () =>
  guard(() => job({ kind: "catalogue" }, showCatalogue));
$("plan-limit-count").onchange = () => { $("plan-count").disabled = !$("plan-limit-count").checked; };
$("plan-limit-seeders").onchange = () => { $("plan-seeders").disabled = !$("plan-limit-seeders").checked; };
$("plan-form").onsubmit = event => {
  event.preventDefault();
  guard(() =>
    job(
      {
        kind: "plan",
        client_ids: [...$("plan-clients").querySelectorAll("input[data-client-id]:checked")].map(e => e.dataset.clientId),
        client_budgets: Object.fromEntries([...$("plan-clients").querySelectorAll("input[data-budget-id]")].map(e => [e.dataset.budgetId, Math.round(Number(e.value) * 1024 ** 3)])),
        maximum_torrents: $("plan-limit-count").checked ? Number($("plan-count").value) : 20,
        limit_torrents: $("plan-limit-count").checked,
        plan_goal: $("plan-goal").value,
        category: Number($("plan-category").value) || null,
        max_seeders: $("plan-limit-seeders").checked ? Number($("plan-seeders").value) : null,
        min_size: Math.round(Number($("plan-min-size").value) * 1024 ** 3),
        max_size: Math.round(Number($("plan-max-size").value) * 1024 ** 3),
        maximum_bytes: Math.round(Number($("plan-budget").value) * 1024 ** 3),
        cached_only: $("plan-cached").checked,
      },
      (r) => {
        showCatalogue(r.catalogue);
        if (r.cancelled) return;
        $("plan-diagnostics").replaceChildren(...(r.issues || []).map(issue => element("p", issue.message)));
        $("plan-summary").textContent = `${r.rows.length} torrents · ${bytes(r.size)} · +${num(r.zen)} Zen/${say("day", "jour")}`;
        table("plan-storage", r.storage || [], [
          {label: say("Download folder", "Dossier de téléchargement"), render: r => r.folder},
          {label: say("Free now", "Libre actuellement"), render: r => bytes(r.free)},
          {label: say("Reserved", "Réservé"), render: r => bytes(r.reserved)},
          {label: say("Plan downloads", "Téléchargements du plan"), render: r => bytes(r.download)},
          {label: say("Free after plan", "Libre après le plan"), render: r => bytes(r.after_plan)},
        ]);
        state.planRows = r.rows;
        state.planSelected = new Set(r.rows.map((v) => v.hash));
        state.planOffset = 0;
        renderPlan();
      },
    ),
  );
};
setInterval(() => {
  if (!$("workspace").hidden) guard(pollJobs);
}, 2000);
setInterval(() => {
  if (
    !$("workspace").hidden &&
    state.setup?.configured &&
    ["torrents", "zen"].includes(state.view) &&
    !state.jobs.size
  )
    guard(() => job({ kind: "refresh" }, loadTorrents));
}, 15000);
guard(async () => {
  try {
    await api("setup");
    await enter();
  } catch (error) {
    if (!error.message.includes("Sign in")) toast(error.message);
  }
});

function uploadForm() {
  const options = {};
  $("upload-options")
    .querySelectorAll("select")
    .forEach((s) => {
      options[s.dataset.type] = [...s.selectedOptions]
        .map((o) => Number(o.value))
        .filter(Boolean);
    });
  return {
    category: Number($("upload-category").value) || null,
    subcategory: Number($("upload-subcategory").value) || null,
    source: $("upload-source").value,
    image: $("upload-image").value,
    title: $("upload-title").value,
    description: $("upload-description").value,
    nfo: $("upload-nfo").value,
    options,
    reviewed: $("upload-reviewed").checked,
  };
}
async function prepareUpload(row, saved = null) {
  state.uploadDraft = saved;
  state.uploadPath = row.path;
  $("upload-save-local").disabled = false;
  await navigate("upload");
  $("upload-editor").hidden = false;
  $("upload-help").textContent = row.name;
  const categories = await api("upload/categories");
  $("upload-category").replaceChildren(
    new Option("Auto", ""),
    ...categories.map((c) => new Option(c.name, c.id)),
  );
  [
    "upload-title",
    "upload-description",
    "upload-nfo",
    "upload-source",
    "upload-image",
  ].forEach((id) => ($(id).value = ""));
  $("upload-subcategory").replaceChildren();
  $("upload-options").replaceChildren();
  $("upload-reviewed").checked = false;
  $("upload-result").replaceChildren();
  $("upload-send-direct").hidden = Boolean(saved);
  $("upload-send-local").hidden = !saved;
  if (saved) {
    for (const [field, id] of Object.entries({title: "upload-title", description: "upload-description",
      nfo: "upload-nfo", source: "upload-source", image: "upload-image", category: "upload-category"})) {
      $(id).value = saved.form[field] ?? "";
    }
    $("upload-subcategory").append(new Option(String(saved.form.subcategory), saved.form.subcategory));
    state.uploadSavedOptions = saved.form.options;
  }
  await previewUpload();
}
async function previewUpload() {
  const form = uploadForm();
  if (state.uploadSavedOptions) { form.options = state.uploadSavedOptions; state.uploadSavedOptions = null; }
  await job(
    { kind: "upload-preview", path: state.uploadPath, upload: form,
      draft_id: state.uploadDraft?.id || "", revision: state.uploadDraft?.revision || 0 },
    (r) => {
      $("upload-category").value = r.category;
      $("upload-title").value = r.title;
      $("upload-description").value = r.description;
      $("upload-nfo").value = r.nfo;
      $("upload-subcategory").replaceChildren(
        ...r.subcategories.map((s) => new Option(s.label || s.name, s.id)),
      );
      $("upload-subcategory").value = r.subcategory;
      $("upload-options").replaceChildren(
        ...r.options.map((o) => {
          const label = element("label", o.name + (o.required ? " *" : "")),
            select = element("select");
          select.dataset.type = o.id;
          select.multiple = o.multiple;
          select.append(
            new Option("—", ""),
            ...o.values.map(
              (v) =>
                new Option(
                  v.label,
                  v.id,
                  false,
                  (r.chosen[o.id] || []).includes(v.id),
                ),
            ),
          );
          label.append(select);
          return label;
        }),
      );
      $("upload-rules").replaceChildren(
        ...r.refusals.map((v) => element("p", v, "danger")),
        ...r.warnings.map((v) => element("p", v)),
      );
      table(
        "upload-files",
        r.files,
        [
          { label: "Torrent file", render: (f) => f.torrent_path },
          { label: "Local file", render: (f) => f.local_path },
          { label: "Size", render: (f) => bytes(f.size) },
        ],
        null,
      );
    },
  );
}
async function loadUploadQueue() {
  const rows = await api("upload/queue");
  table("upload-local-queue", rows, [
    {label: say("Title", "Titre"), render: r => r.form.title},
    {label: say("Status", "État"), render: r => ({queued: say("Awaiting review", "À relire"),
      sending: say("Sending / check c411", "Envoi / vérifier c411"),
      uncertain: say("Check c411 before retrying", "Vérifier c411 avant un nouvel essai"),
      sent: say("Sent to c411", "Envoyé à c411")})[r.status] || r.status},
    {label: say("Actions", "Actions"), render: r => {
      const actions = element("div", "", "actions");
      actions.append(button(say("Preview saved draft", "Aperçu du brouillon enregistré"), () => {
        const client = state.clientId;
        return aCardDetail(() => api(`upload/queue/${encodeURIComponent(r.id)}/preview?revision=${r.revision}&client_id=${encodeURIComponent(client || "")}`));
      }));
      if (r.status === "queued") actions.append(button(say("Review / edit", "Relire / modifier"),
        () => prepareUpload({path: r.path, name: r.form.title}, r)));
      if (r.status !== "sending") actions.append(button(say("Remove locally", "Retirer localement"), async () => {
        if (confirm(say("Remove only this local record? Files and c411 Drafts will be kept.",
          "Retirer uniquement ce brouillon local ? Les fichiers et brouillons c411 seront conservés.")))
          await job({kind: "upload-remove", draft_id: r.id, revision: r.revision}, loadUploadQueue);
      }));
      if (["sending", "uncertain"].includes(r.status)) actions.append(button(say("Allow retry…", "Autoriser un nouvel essai…"), async () => {
        if (confirm(say("Check c411 and wait for any running send. Confirm that no Draft was created before allowing another attempt.",
          "Vérifiez c411 et attendez la fin de tout envoi. Confirmez qu’aucun brouillon n’a été créé avant un nouvel essai.")))
          await job({kind: "upload-reset", draft_id: r.id, revision: r.revision}, loadUploadQueue);
      }));
      return actions;
    }},
  ], null);
}
$("upload-queue-refresh").onclick = () => guard(loadUploadQueue);
$("upload-save-local").onclick = () => guard(async () => {
  await job({kind: "upload-queue", path: state.uploadPath, upload: uploadForm(),
    draft_id: state.uploadDraft?.id || "", revision: state.uploadDraft?.revision || 0}, async r => {
      state.uploadDraft = r;
      $("upload-send-direct").hidden = true;
      $("upload-send-local").hidden = false;
      $("upload-reviewed").checked = false;
      $("upload-description").value = r.form.description;
      toast(say("Saved locally. Nothing sent to c411.", "Enregistré localement. Rien n’a été envoyé à c411."));
      await loadUploadQueue();
    });
});
$("upload-send-local").onclick = () => guard(async () => {
  const saved = state.uploadDraft;
  if (!saved || !$("upload-reviewed").checked) throw Error(say("Review the saved draft and check the confirmation box.",
    "Relisez le brouillon enregistré et cochez la confirmation."));
  const current = uploadForm();
  for (const field of ["title", "description", "nfo", "source", "image", "category", "subcategory"])
    if (current[field] !== saved.form[field]) throw Error(say("Save your changes locally before sending.", "Enregistrez vos modifications avant l’envoi."));
  const canonicalOptions = values => JSON.stringify(Object.entries(values).filter(([,v]) => v.length)
    .sort(([a], [b]) => Number(a)-Number(b)).map(([k,v]) => [String(k), [...v].sort((a,b) => a-b)]));
  if (canonicalOptions(current.options) !== canonicalOptions(saved.form.options))
    throw Error(say("Save your changes locally before sending.", "Enregistrez vos modifications avant l’envoi."));
  if (!confirm(say("Send this saved revision to c411 as a Draft? It will not be published.",
    "Envoyer cette version enregistrée à c411 comme brouillon ? Elle ne sera pas publiée."))) return;
  await job({kind: "upload-send", draft_id: saved.id, revision: saved.revision}, async r => {
    $("upload-result").replaceChildren(element("p", r.message), button(say("Seed prepared Upload", "Seeder l’upload préparé"),
      () => job({kind: "upload-seed", hashes: [r.hash]}, () => toast(say("Verification started.", "Vérification lancée.")))));
    $("upload-send-local").hidden = true;
    $("upload-save-local").disabled = true;
    await loadUploadQueue();
  });
});
$("upload-preview").onclick = () => guard(previewUpload);
$("upload-category").onchange = () => {
  $("upload-subcategory").replaceChildren();
  $("upload-title").value = "";
  guard(previewUpload);
};
$("upload-subcategory").onchange = () => guard(previewUpload);
$("upload-form").onsubmit = (e) => {
  e.preventDefault();
  if (state.uploadDraft) { $("upload-send-local").click(); return; }
  guard(async () => {
    if (!$("upload-reviewed").checked)
      throw Error(
        say(
          "Review the Upload and check the confirmation box.",
          "Relisez l’upload et cochez la confirmation.",
        ),
      );
    await job(
      { kind: "upload-draft", path: state.uploadPath, upload: uploadForm() },
      (r) => {
        $("upload-result").replaceChildren(
          element("p", r.message),
          button(say("Seed prepared Upload", "Seeder l’upload préparé"), () =>
            job({ kind: "upload-seed", hashes: [r.hash] }, () =>
              toast(say("Verification started.", "Vérification lancée.")),
            ),
          ),
        );
      },
    );
  });
};
$("save-announce").onclick = () =>
  guard(async () => {
    await api("setup/announce", { value: $("announce-url").value });
    $("announce-url").value = "";
    toast(say("Announce URL saved.", "URL d’annonce enregistrée."));
  });
$("refresh-profile").onclick = () =>
  guard(() =>
    job({ kind: "profile" }, (r) => {
      toast(`${r.balance} Zen · ${r.class || ""}`);
      return job({ kind: "refresh" }, state.view === "zen" ? loadZenSeeding : loadTorrents);
    }),
  );

$("save-proxy").onclick = () =>
  guard(async () => {
    await api("setup/proxy", {
      address: $("proxy-address").value,
      username: $("proxy-username").value,
      torrent_client: $("proxy-client").checked,
      ...($("proxy-password").value
        ? { password: $("proxy-password").value }
        : {}),
    });
    $("proxy-password").value = "";
    toast(
      say(
        "Proxy settings saved. Test the connection again.",
        "Proxy enregistré. Testez à nouveau la connexion.",
      ),
    );
  });
$("suggest-mappings").onclick = () =>
  guard(async () => {
    const result = await api("setup/suggest-mappings", {});
    $("mapping-suggestions").replaceChildren(
      ...result.suggestions.map((s) =>
        button(`${s.mapping.local} → ${s.mapping.qbit}`, () => {
          $("folder-local").value = s.mapping.local;
          $("folder-client").value = s.mapping.qbit;
        }),
      ),
    );
    if (!result.suggestions.length)
      $("mapping-suggestions").append(
        element(
          "p",
          result.same_paths
            ? say(
                "Some torrents already use the same path. Select that folder below.",
                "Certains torrents utilisent déjà le même chemin. Sélectionnez ce dossier ci-dessous.",
              )
            : say(
                "No matching file found. Check your mount, then enter both folder paths below.",
                "Aucun fichier correspondant. Vérifiez le montage puis indiquez les deux chemins ci-dessous.",
              ),
        ),
      );
  });

const guideHistory = [];
let currentGuide = "";
async function loadGuides() {
  const guides = await api(`documentation?language=${language}`);
  $("guide-select").replaceChildren(...guides.map(g => new Option(g.title, g.path)));
  guideHistory.length = 0;
  currentGuide = "";
  $("guide-back").title = say("Previous guide", "Guide précédent");
  $("guide-back").setAttribute("aria-label", $("guide-back").title);
  await openGuide(guides[0].path);
}
async function openGuide(path, fragment = "", remember = true) {
  const result = await api(`documentation/page/${path.split("/").map(encodeURIComponent).join("/")}`);
  if (remember && currentGuide && path !== currentGuide) guideHistory.push(currentGuide);
  currentGuide = path;
  $("guide-content").innerHTML = result.html;
  $("guide-select").value = path;
  $("guide-back").disabled = !guideHistory.length;
  $("guide-online").href = `https://github.com/Vietnoirien/TorrentLinker/blob/main/docs/${path}`;
  if (fragment) document.getElementById(decodeURIComponent(fragment))?.scrollIntoView();
  else if (state.view === "documentation") window.scrollTo(0, 0);
}
$("guide-select").onchange = () => guard(() => openGuide($("guide-select").value));
$("guide-back").onclick = () => {
  const previous = guideHistory.pop();
  if (previous) guard(() => openGuide(previous, "", false));
};
$("guide-content").onclick = event => {
  const link = event.target.closest("a[data-guide]");
  if (!link) return;
  event.preventDefault();
  guard(() => openGuide(link.dataset.guide, link.hash.slice(1)));
};

$("target-client").onchange = () => guard(async () => {
  state.clientId = $("target-client").value;
  state.uploadDraft = null;
  state.uploadSavedOptions = null;
  state.addingClient = false;
  $("client-password").value = ""; $("client-key").value = "";
  state.selected.clear(); state.queueSelected.clear(); state.planSelected.clear();
  state.offset = 0; state.libraryOffset = 0; state.localItem = "";
  $("candidates").hidden = true; $("upload-editor").hidden = true;
  await refreshSetup();
  await navigate(state.clientId === "all" && state.view !== "zen" ? "torrents" : state.view);
  if (state.setup.configured) await job({kind: "refresh"}, state.view === "zen" ? loadZenSeeding : loadTorrents);
});
$("add-client").onclick = () => {
  state.addingClient = true;
  $("client-name").value = ""; $("client-host").value = "";
  $("client-username").value = ""; $("client-password").value = ""; $("client-key").value = "";
  $("client-name").focus();
};
$("default-client").onclick = () => guard(async () => {
  await api("clients/default", {client_id: state.setup.client_id}); await refreshSetup();
});
$("remove-client").onclick = () => guard(async () => {
  if (!confirm(say("Remove this client profile? Torrents and files will be kept.", "Retirer ce profil ? Les torrents et fichiers seront conservés."))) return;
  await api("clients/remove", {client_id: state.setup.client_id}); state.clientId = ""; await refreshSetup();
});


async function loadAgents() {
  const data = await api("agents");
  $("agents-enabled").checked = data.enabled;
  $("agents-endpoint").textContent = new URL("mcp/", location.href).href;
  const choices = $("agent-clients");
  const previous = new Set([...choices.querySelectorAll("input:checked")].map(e => e.value));
  const firstLoad = !choices.children.length;
  choices.replaceChildren(...state.setup.clients.filter(p => p.enabled).map(p => {
    const label = element("label"), input = document.createElement("input");
    input.type = "checkbox"; input.value = p.id;
    input.checked = firstLoad ? p.id === state.setup.client_id : previous.has(p.id);
    label.append(input, document.createTextNode(p.name)); return label;
  }));
  $("agent-permissions").disabled = $("agent-mode").value === "propose";
  $("agent-connections").replaceChildren(...data.connections.map(g => {
    const row = element("div", undefined, "card");
    row.append(element("p", `${g.name} · ${g.mode} · ${g.clients.join(", ")}`));
    if (g.revoked) row.append(element("span", say("Revoked", "Révoqué")));
    else row.append(button(say("Revoke", "Révoquer"), async () => {
      await api(`agents/${g.id}/revoke`, {}); await loadAgents();
    }));
    return row;
  }));
  $("agent-proposals").replaceChildren(...data.proposals.map(p => {
    const row = element("details", undefined, "card");
    const name = data.connections.find(g => g.id === p.grant_id)?.name || p.grant_id;
    row.append(element("summary", `${name} · ${p.body.kind} · ${p.body.client_id} · ${p.status}`));
    const details = element("pre", JSON.stringify(p.body, null, 2)); row.append(details);
    if (p.status === "pending") {
      row.append(button(say("Approve", "Approuver"), async () => {
        if (["upload-send", "upload-reset", "upload-remove"].includes(p.body.kind)) {
          await aReview(p.id, loadAgents); return;
        }
        const destructive = p.body.kind === "manage" && ["remove", "delete"].includes(p.body.action);
        if (destructive) {
          const preview = await api(`agents/proposals/${p.id}/review`);
          if (!confirm(preview.client + "\n" + preview.warning + "\n\n" +
            preview.torrents.map(t => t.name + "\n" + t.folder).join("\n"))) return;
        }
        await api(`agents/proposals/${p.id}/approve`, {}); await loadAgents();
      }), button(say("Reject", "Refuser"), async () => {
        await api(`agents/proposals/${p.id}/reject`, {}); await loadAgents();
      }));
    }
    if (p.job_id) row.append(button(say("View job", "Voir la tâche"), async () => {
      const job = await api(`jobs/${p.job_id}`);
      details.textContent = JSON.stringify(job, null, 2);
    }), button(say("Cancel job", "Annuler la tâche"), async () => {
      await api(`jobs/${p.job_id}/cancel`, {}); await loadAgents();
    }));
    if (p.body.kind === "send-queue") row.append(button(
      say("Release uncertain storage reservation", "Libérer la réserve disque incertaine"), async () => {
        if (!confirm(say(
          "Check the Torrent Client first. Confirm that this send has finished or did not start. Daily spending stays counted.",
          "Vérifiez d'abord le client torrent. Confirmez que cet envoi est terminé ou n'a pas démarré. Le budget quotidien reste débité."
        ))) return;
        await api(`agents/proposals/${p.id}/release-storage`, {}); await loadAgents();
      }
    ));
    return row;
  }));
  $("agent-goals").replaceChildren(...data.goals.map(g => element("pre", JSON.stringify(g.body, null, 2))));
  $("agent-activity").replaceChildren(...data.activity.map(e =>
    element("p", `${new Date(e.created * 1000).toLocaleString()} · ${e.action} · ${e.detail}`)));
}
$("agents-refresh").onclick = () => guard(loadAgents);
$("agents-enabled").onchange = () => guard(async () => {
  await api("agents", {enabled: $("agents-enabled").checked}, "PUT"); await loadAgents();
});
$("agent-mode").onchange = () => { $("agent-permissions").disabled = $("agent-mode").value === "propose"; };
$("agent-token-hide").onclick = () => { $("agent-token").value = ""; $("agent-token-box").hidden = true; };
$("agent-form").onsubmit = event => {
  event.preventDefault();
  guard(async () => {
    const grant = await api("agents", {
      name: $("agent-name").value,
      clients: [...$("agent-clients").querySelectorAll("input:checked")].map(e => e.value),
      mode: $("agent-mode").value,
      permissions: $("agent-mode").value === "propose" ? [] : [...$("agent-permissions").querySelectorAll("input:checked")].map(e => e.value),
      daily_bytes: Number($("agent-bytes").value) * 1024 ** 3,
      daily_torrents: Number($("agent-count").value),
      reserve_bytes: Number($("agent-reserve").value) * 1024 ** 3,
    });
    $("agent-token").value = grant.token; $("agent-token-box").hidden = false;
    await loadAgents();
  });
};

$("navigation-toggle").onclick = () => {
  const collapsed = document.body.classList.toggle("navigation-collapsed");
  $("navigation-toggle").setAttribute("aria-expanded", String(!collapsed));
};

if (matchMedia("(max-width: 1050px)").matches) {
  document.body.classList.add("navigation-collapsed");
  $("navigation-toggle").setAttribute("aria-expanded", "false");
}

function renderPlan() {
  const offset = state.planOffset || 0;
  const rows = state.planRows.slice(offset, offset + 100);
  table("plan-result", rows, [...searchColumns(),
    {label: say("Download folder", "Dossier de téléchargement"), render: row => row.folder || "—"},
    {label: "Client", render: row => {
      const select = document.createElement("select");
      for (const p of state.setup.clients.filter(p => p.enabled)) select.add(new Option(p.name, p.id));
      select.value = row.client_id || state.clientId;
      select.onchange = () => { row.client_id = select.value; };
      return select;
    }},
  ], state.planSelected);
  $("plan-page").textContent = `${state.planRows.length ? offset + 1 : 0}–${offset + rows.length} / ${state.planRows.length}`;
  $("plan-prev").disabled = offset === 0;
  $("plan-next").disabled = offset + 100 >= state.planRows.length;
}
$("plan-prev").onclick = () => { state.planOffset = Math.max(0, (state.planOffset || 0) - 100); renderPlan(); };
$("plan-next").onclick = () => { state.planOffset = (state.planOffset || 0) + 100; renderPlan(); };

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
