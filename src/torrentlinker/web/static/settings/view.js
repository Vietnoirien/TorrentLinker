"use strict";
const $ = (id) => document.getElementById(id);
let language = "en",
  environment = {},
  request,
  snapshot,
  loadingClient,
  section = "connections",
  generation = 0,
  agentTokenGeneration = 0;
const drafts = new Map();
const draftBaselines = new Map();
const say = (en, fr) => (language === "fr" ? fr : en);
function clearAgentToken() {
  agentTokenGeneration++;
  if ($("agent-token")) $("agent-token").value = "";
  if ($("agent-token-box")) $("agent-token-box").hidden = true;
}
const sections = () => ({
  connections: say("Connections", "Connexions"),
  clients: "Clients",
  companion: "Companion",
  agents: say("Agent access", "Accès agent"),
  assistant: "Assistant",
  general: say("General", "Général"),
  library: say("Library Folders", "Dossiers de bibliothèque"),
  downloads: say("Download Folders", "Dossiers de téléchargement"),
  paths: say("Client Paths", "Chemins du client"),
  matching: say("Search & Matching", "Recherche et correspondance"),
  zen: "Zen",
});
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
async function guard(work) {
  $("settings-error").textContent = "";
  document
    .querySelectorAll(".settings-modal-error")
    .forEach((node) => node.remove());
  try {
    return await work();
  } catch (error) {
    $("settings-status").textContent = "";
    $("settings-error").textContent = error.message;
    const modal = document.querySelector("dialog[open]");
    if (modal) {
      const message = element("p", error.message, "settings-modal-error");
      message.setAttribute("role", "alert");
      modal.append(message);
    }
  }
}
function button(text, action, className = "") {
  const client = environment.client_id;
  const node = element("button", text, className);
  node.type = "button";
  node.onclick = () =>
    guard(() => {
      if (client !== environment.client_id || snapshot?.client_id !== client)
        throw Error(
          say(
            "Wait for the selected client's settings.",
            "Attendez les paramètres du client sélectionné.",
          ),
        );
      return action();
    });
  return node;
}
const draftKey = (group) => `${environment.client_id}:${group}`;
function draft(group) {
  const key = draftKey(group);
  if (!drafts.has(key)) {
    const value = structuredClone(snapshot[group] || {});
    delete value.secrets;
    delete value.managed_secrets;
    drafts.set(key, value);
    draftBaselines.set(key, JSON.stringify(value));
  }
  return drafts.get(key);
}
function field(form, label, data, key, type = "text", options = null) {
  const wrapper = element("label", label, "settings-field");
  const input = element(
    options ? "select" : type === "textarea" ? "textarea" : "input",
  );
  input.setAttribute("aria-label", label);
  if (options)
    for (const [value, text] of options) {
      const option = element("option", text);
      option.value = value;
      input.append(option);
    }
  else if (type !== "textarea") input.type = type;
  if (type === "checkbox") input.checked = Boolean(data[key]);
  else input.value = data[key] ?? "";
  input.oninput = () => {
    data[key] =
      type === "checkbox"
        ? input.checked
        : type === "number"
          ? Number(input.value)
          : input.value;
    $("settings-status").textContent = say(
      "Unsaved changes",
      "Modifications non enregistrées",
    );
  };
  if (type === "checkbox") {
    wrapper.className = "settings-check";
    wrapper.prepend(input);
  } else wrapper.append(input);
  form.append(wrapper);
  return input;
}
function secret(form, label, data, key, saved) {
  const input = field(form, label, data, key, "password");
  input.autocomplete = "new-password";
  input.placeholder = saved
    ? say(
        "Saved; leave blank to keep",
        "Enregistré ; laisser vide pour conserver",
      )
    : say("Not saved", "Non enregistré");
  input.oninput = () => {
    if (input.value) data[key] = input.value;
    else delete data[key];
    $("settings-status").textContent = say(
      "Unsaved changes",
      "Modifications non enregistrées",
    );
  };
  const connection = draft("connections");
  const kind =
    { qbittorrent: "qbit", bittorrent: "utorrent" }[connection.client.client] ||
    connection.client.client;
  let name =
    key === "tmdb_api_key"
      ? "tmdb-api-key"
      : key === "announce_url"
        ? "announce-url"
        : key === "api_key"
          ? data === connection.indexer
            ? "indexer-api-key"
            : "qbit-api-key"
          : data === connection.proxy
            ? "proxy-password"
            : `${kind}-password`;
  if (data === connection.client && environment.client_id !== "default")
    name = `client-${environment.client_id}-${name}`;
  if (snapshot.connections.managed_secrets.includes(name)) {
    input.disabled = true;
    input.placeholder = say("Managed by deployment", "Géré par le déploiement");
  } else if (saved) {
    input.parentElement.append(
      button(say("Clear saved value", "Effacer la valeur enregistrée"), () => {
        data[key] = "";
        input.value = "";
        input.placeholder = say(
          "Will be cleared on Save",
          "Sera effacé à l’enregistrement",
        );
      }),
    );
  }
  return input;
}
function box(form, title) {
  const box = element("section", undefined, "settings-card"),
    fields = element("div", undefined, "settings-fields");
  box.append(element("h3", title), fields);
  form.append(box);
  return fields;
}
function connections(form) {
  const data = draft("connections"),
    saved = snapshot.connections.secrets;
  const client = box(form, say("Torrent Client", "Client torrent"));
  field(
    client,
    say("Client name", "Nom du client"),
    data.client,
    "name",
  ).required = true;
  const choice = field(
    client,
    say("Client type", "Type de client"),
    data.client,
    "client",
    "",
    [
      ["qbittorrent", "qBittorrent"],
      ["deluge", "Deluge"],
      ["transmission", "Transmission"],
      ["utorrent", "µTorrent"],
      ["bittorrent", "BitTorrent"],
      ["rtorrent", "rTorrent"],
    ],
  );
  choice.oninput = () => {
    data.client.client = choice.value;
    render();
  };
  field(client, say("Address", "Adresse"), data.client, "host").required = true;
  if (data.client.client !== "deluge")
    field(client, say("Username", "Identifiant"), data.client, "username");
  secret(
    client,
    say("Password", "Mot de passe"),
    data.client,
    "password",
    saved.password,
  );
  if (data.client.client === "qbittorrent")
    secret(
      client,
      say("Client API key", "Clé API du client"),
      data.client,
      "api_key",
      saved.api_key,
    );
  field(
    client,
    say("Reseed link folder", "Dossier des liens de remise en seed"),
    data,
    "reseed_link_root",
  );
  if (data.client.client === "transmission")
    field(
      client,
      say(
        "Turn off Transmission’s .part filenames when testing",
        "Désactiver les noms .part de Transmission lors du test",
      ),
      data.client,
      "turn_off_partial_names",
      "checkbox",
    );
  client.append(
    button(say("Test connection", "Tester la connexion"), async () => {
      const result = await request("test-connection", {
        group: "client",
        value: structuredClone(data.client),
      });
      $("settings-status").textContent =
        `${say("Connected", "Connecté")} · ${result.version}`;
    }),
  );
  const indexer = box(form, say("Indexer", "Indexeur"));
  field(indexer, say("Indexer URL", "URL de l’indexeur"), data.indexer, "url");
  secret(
    indexer,
    say("Indexer API key", "Clé API de l’indexeur"),
    data.indexer,
    "api_key",
    saved.indexer_api_key,
  );
  secret(
    indexer,
    say("Announce URL", "URL d’annonce"),
    data,
    "announce_url",
    saved.announce_url,
  );
  const extras = element(
    "label",
    say(
      "Replace additional API keys",
      "Remplacer les clés API supplémentaires",
    ),
    "settings-field",
  );
  const replace = element("input");
  replace.type = "checkbox";
  replace.disabled = snapshot.connections.managed_secrets.some((name) =>
    name.startsWith("indexer-extra-key-"),
  );
  replace.checked = data.indexer.extra_keys !== undefined;
  const keys = element("textarea");
  keys.setAttribute(
    "aria-label",
    say(
      "Additional API keys, one per line",
      "Clés API supplémentaires, une par ligne",
    ),
  );
  keys.value = (data.indexer.extra_keys || []).join("\n");
  keys.hidden = !replace.checked;
  replace.onchange = () => {
    keys.hidden = !replace.checked;
    if (replace.checked)
      data.indexer.extra_keys = keys.value.split("\n").filter(Boolean);
    else delete data.indexer.extra_keys;
  };
  keys.oninput = () => {
    data.indexer.extra_keys = keys.value
      .split("\n")
      .map((k) => k.trim())
      .filter(Boolean);
  };
  extras.className = "settings-check";
  extras.prepend(replace);
  extras.append(keys);
  indexer.append(extras);
  indexer.append(
    button(say("Test Indexer", "Tester l’indexeur"), async () => {
      const result = await request("test-connection", {
        group: "indexer",
        value: structuredClone(data.indexer),
      });
      $("settings-status").textContent =
        `${result.categories} ${say("categories found", "catégories trouvées")}`;
    }),
  );
  const tmdb = box(form, "TMDb");
  secret(
    tmdb,
    say("TMDb API key", "Clé API TMDb"),
    data,
    "tmdb_api_key",
    saved.tmdb_api_key,
  );
  const proxy = box(form, "Proxy");
  field(proxy, say("Proxy address", "Adresse du proxy"), data.proxy, "address");
  field(
    proxy,
    say("Proxy username", "Identifiant du proxy"),
    data.proxy,
    "username",
  );
  secret(
    proxy,
    say("Proxy password", "Mot de passe du proxy"),
    data.proxy,
    "password",
    saved.proxy_password,
  );
  field(
    proxy,
    say("Also for the Torrent Client", "Également pour le client torrent"),
    data.proxy,
    "torrent_client",
    "checkbox",
  );
  proxy.append(
    button(say("Test proxy", "Tester le proxy"), async () => {
      const result = await request("test-connection", {
        group: "proxy",
        value: structuredClone(data.proxy),
      });
      $("settings-status").textContent =
        `${say("Address seen by c411", "Adresse vue par c411")} : ${result.ip}`;
    }),
  );
}
async function manageClient(action, value) {
  const client = environment.client_id;
  const result = await request("clients", { action, value });
  if (client !== environment.client_id) return;
  snapshot = result;
  render();
}
function numberField(form, label, data, key, min, max, factor = 1) {
  const input = field(form, label, data, key, "number");
  input.value = (data[key] ?? 0) * factor;
  input.min = min;
  input.max = max;
  input.step = "any";
  input.oninput = () => {
    data[key] = Number(input.value) / factor;
    $("settings-status").textContent = say(
      "Unsaved changes",
      "Modifications non enregistrées",
    );
  };
  return input;
}
function linesField(form, label, data, key) {
  const input = field(form, label, data, key, "textarea");
  input.value = (data[key] || []).join("\n");
  input.oninput = () => {
    data[key] = input.value
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
  };
}
function categoryName(id) {
  const categories = snapshot.storage.indexer_categories;
  const names = [],
    seen = new Set();
  while (id !== null && id !== undefined && !seen.has(String(id))) {
    seen.add(String(id));
    const category = categories[id];
    names.unshift(category?.name || String(id));
    id = category?.parent;
  }
  return names.join(" › ");
}
function preferences(form, group) {
  const data = draft(group),
    fields = box(form, sections()[group]);
  if (group === "general") {
    field(
      fields,
      say(
        "Download video sequentially for playback",
        "Télécharger les vidéos dans l’ordre pour la lecture",
      ),
      data,
      "sequential_video",
      "checkbox",
    );
    field(fields, say("Language", "Langue"), data, "language", "", [
      ["auto", say("Automatic", "Automatique")],
      ["en", "English"],
      ["fr", "Français"],
    ]);
    field(fields, say("Theme", "Thème"), data, "theme", "", [
      ["auto", say("System", "Système")],
      ["light", say("Light", "Clair")],
      ["dark", say("Dark", "Sombre")],
    ]);
    field(
      fields,
      say("Media interface", "Interface multimédia"),
      data,
      "media_layout",
      "",
      [
        ["cinematic", say("Cinematic home", "Accueil cinéma")],
        ["focus", "Focus"],
        ["collection", "Collection"],
      ],
    );
    field(
      fields,
      say("Show XXX content", "Afficher le contenu XXX"),
      data,
      "adult_content",
      "checkbox",
    );
    if (environment.mode === "desktop") {
      const input = field(
        fields,
        say("Interface size", "Taille de l’interface"),
        data,
        "ui_scale",
        "",
        [0.75, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2].map((value) => [
          value,
          `${Math.round(value * 100)}%`,
        ]),
      );
      input.oninput = () => {
        data.ui_scale = Number(input.value);
      };
      form.append(
        element(
          "p",
          say(
            "Restart TorrentLinker to apply interface size and application menu language.",
            "Redémarrez TorrentLinker pour appliquer la taille de l’interface et la langue des menus.",
          ),
          "muted",
        ),
      );
    } else
      form.append(
        element(
          "p",
          say(
            "Use browser zoom to change interface size.",
            "Utilisez le zoom du navigateur pour modifier la taille de l’interface.",
          ),
          "muted",
        ),
      );
    form.append(
      button(say("Export diagnostics…", "Exporter le diagnostic…"), () =>
        request("diagnostics", {}),
      ),
    );
  } else if (group === "matching") {
    form.append(
      button(
        say(
          "Refresh Indexer categories",
          "Actualiser les catégories de l’indexeur",
        ),
        () => storageRequest("categories"),
      ),
    );
    form.append(
      element(
        "p",
        say(
          "No category selected means all categories for that content kind.",
          "Aucune catégorie sélectionnée signifie toutes les catégories pour ce type de contenu.",
        ),
        "muted",
      ),
    );
    for (const [kind, label] of Object.entries({
      movie: say("Movies", "Films"),
      series: say("Series", "Séries"),
      music: say("Music", "Musique"),
      ebook: say("Books", "Livres"),
      game: say("Games", "Jeux"),
      "3d-model": say("3D models", "Modèles 3D"),
      adult: "XXX",
      other: say("Other", "Autres"),
    })) {
      const input = field(
        fields,
        `${say("Categories", "Catégories")} · ${label}`,
        data.kind_categories,
        kind,
        "",
        Object.keys(snapshot.storage.indexer_categories).map((id) => [
          id,
          categoryName(id),
        ]),
      );
      input.multiple = true;
      input.size = 5;
      for (const id of data.kind_categories[kind] || []) {
        if (![...input.options].some((option) => option.value === String(id)))
          input.add(new Option(String(id), String(id)));
      }
      for (const option of input.options)
        option.selected = (data.kind_categories[kind] || []).includes(
          Number(option.value),
        );
      input.oninput = () => {
        data.kind_categories[kind] = [...input.selectedOptions].map((option) =>
          Number(option.value),
        );
        $("settings-status").textContent = say(
          "Unsaved changes",
          "Modifications non enregistrées",
        );
      };
    }
    numberField(
      fields,
      say("Size tolerance (%)", "Tolérance de taille (%)"),
      data,
      "size_tolerance",
      0,
      20,
      100,
    );
    numberField(
      fields,
      say(
        "Minimum Partial Match coverage (%)",
        "Couverture minimale d’une correspondance partielle (%)",
      ),
      data,
      "min_partial_coverage",
      1,
      100,
      100,
    );
    linesField(
      fields,
      say("Ignored Files", "Fichiers ignorés"),
      data,
      "ignore_patterns",
    );
    linesField(
      fields,
      say("Excluded from Plans", "Exclus des Plans"),
      data,
      "plan_exclusions",
    );
  } else if (group === "zen") {
    field(fields, say("Class", "Classe"), data, "zen_class", "", [
      ["tanker", "Tanker"],
      ["swarm-keeper", "Swarm Keeper"],
      ["reuploader", "Reuploader"],
    ]);
    numberField(
      fields,
      say("Tree bonus unlocked (%)", "Bonus d’arbre débloqué (%)"),
      data,
      "tree_bonus",
      0,
      5,
      100,
    );
    numberField(
      fields,
      say("Shop badges bonus (%)", "Bonus des badges boutique (%)"),
      data,
      "badge_bonus",
      0,
      100,
      100,
    );
    numberField(
      fields,
      say("Seed hours per day", "Heures de seed par jour"),
      data,
      "seed_hours",
      0,
      24,
    );
    numberField(
      fields,
      say("Torrent cap (0 = no cap)", "Limite de torrents (0 = illimitée)"),
      data,
      "torrent_cap",
      0,
      100000,
    );
    numberField(
      fields,
      say(
        "Free space kept on each disk (%)",
        "Espace libre conservé sur chaque disque (%)",
      ),
      data,
      "free_space_margin",
      0,
      90,
      100,
    );
  }
}
function clients(form) {
  for (const client of snapshot.clients) {
    const card = element("section", undefined, "client-card");
    card.append(element("h3", client.name), element("p", client.client));
    if (client.id === snapshot.default_client_id)
      card.append(element("span", say("Default", "Par défaut"), "muted"));
    const actions = element("div", undefined, "settings-actions");
    actions.append(
      button(say("Edit settings", "Modifier les paramètres"), () =>
        request("select-client", { client_id: client.id }),
      ),
      button(say("Make default", "Définir par défaut"), () =>
        manageClient("default", { client_id: client.id }),
      ),
      button(say("Remove client", "Supprimer le client"), async () => {
        if (
          !confirm(
            say(
              `Remove ${client.name}? Torrents and files will be kept.`,
              `Supprimer ${client.name} ? Les torrents et fichiers seront conservés.`,
            ),
          )
        )
          return;
        await manageClient("remove", { client_id: client.id, confirmed: true });
      }),
    );
    card.append(actions);
    form.append(card);
  }
  const data = draft("clients");
  field(form, say("New client name", "Nom du nouveau client"), data, "name");
  form.append(
    button(
      say("Add client", "Ajouter un client"),
      () => manageClient("add", { name: data.name || "" }),
      "primary",
    ),
  );
}
async function storageRequest(action, value = {}) {
  const client = environment.client_id;
  const result = await request("storage", { action, value });
  if (client !== environment.client_id) return null;
  if (result?.storage) {
    snapshot = result;
    render();
  }
  return result;
}
function storageEditor(form, group) {
  const data = draft(group),
    storage = snapshot.storage;
  data.local ??= "";
  data.client_path ??= "";
  data.kind ??= "other";
  if (data.depth === undefined) data.depth = 1;
  const fields = box(form, say("Folder", "Dossier"));
  field(
    fields,
    say("Folder on the TorrentLinker host", "Dossier sur l’hôte TorrentLinker"),
    data,
    "local",
  );
  const browser = element("div", undefined, "settings-actions");
  async function browse(path = "") {
    if (environment.mode === "desktop") {
      const chosen = await request("choose-folder", { path });
      if (chosen) {
        data.local = chosen;
        render();
      }
      return;
    }
    const result = await storageRequest("browse", { path });
    if (!result) return;
    browser.replaceChildren();
    if (result.path)
      browser.append(
        button(say("Use this folder", "Utiliser ce dossier"), () => {
          data.local = result.path;
          render();
        }),
      );
    if (result.parent) browser.append(button("↑", () => browse(result.parent)));
    for (const folder of result.folders)
      browser.append(button(folder, () => browse(folder)));
  }
  fields.append(
    button(say("Browse…", "Parcourir…"), () => browse(data.local)),
    browser,
  );
  const discovered = element("div", undefined, "settings-actions");
  fields.append(
    button(
      say("Read folders from client", "Lire les dossiers du client"),
      async () => {
        const result = await storageRequest("client-folders");
        if (!result || !discovered.isConnected) return;
        discovered.replaceChildren(
          ...result.folders
            .filter((folder) => folder.path)
            .map((folder) =>
              button(
                `${folder.name || say("Default", "Par défaut")} · ${folder.path}`,
                () => {
                  data.client_path = group === "library" ? "" : folder.path;
                  data.local = folder.local || folder.path;
                  render();
                },
              ),
            ),
        );
        if (!discovered.children.length)
          discovered.textContent = say(
            "No folders reported by the client.",
            "Aucun dossier indiqué par le client.",
          );
      },
    ),
    discovered,
  );
  if (group === "library") {
    field(fields, say("Content kind", "Type de contenu"), data, "kind", "", [
      ["other", say("Automatic", "Automatique")],
      ["movie", say("Movies", "Films")],
      ["series", say("Series", "Séries")],
      ["music", say("Music", "Musique")],
      ["ebook", say("Books", "Livres")],
      ["game", say("Games", "Jeux")],
      ["3d-model", say("3D models", "Modèles 3D")],
      ...(snapshot.general.adult_content || data.kind === "adult"
        ? [["adult", "XXX"]]
        : []),
    ]);
    const depth = field(
      fields,
      say("Grouping depth", "Profondeur de regroupement"),
      data,
      "depth",
      "",
      [
        ["auto", say("Automatic", "Automatique")],
        ...Array.from({ length: 11 }, (_, i) => [String(i), String(i)]),
      ],
    );
    depth.value = data.depth === null ? "auto" : String(data.depth);
    depth.oninput = () => {
      data.depth = depth.value === "auto" ? null : Number(depth.value);
    };
  } else if (group === "downloads") {
    const category = field(
      fields,
      say("Category", "Catégorie"),
      data,
      "category",
      "",
      [
        ["", say("Default", "Par défaut")],
        ...Object.keys(storage.indexer_categories).map((id) => [
          id,
          categoryName(id),
        ]),
      ],
    );
    category.value = data.category ?? "";
    category.oninput = () => {
      data.category = category.value === "" ? null : Number(category.value);
    };
  }
  if (group === "paths")
    field(
      fields,
      say("Torrent Client path", "Chemin du client torrent"),
      data,
      "client_path",
    );
  const feedback = element("p", undefined, "muted");
  fields.append(feedback);
  if (group === "paths")
    fields.append(
      button(
        say("Detect mappings", "Détecter les correspondances"),
        async () => {
          const result = await storageRequest("suggest");
          if (!result || !discovered.isConnected) return;
          discovered.replaceChildren(
            ...result.suggestions.map((suggestion) =>
              button(
                `${suggestion.mapping.local} → ${suggestion.mapping.qbit}`,
                () => {
                  data.local = suggestion.mapping.local;
                  data.client_path = suggestion.mapping.qbit;
                  render();
                },
              ),
            ),
          );
          if (!result.suggestions.length)
            feedback.textContent = say(
              "No matching file found. Check the mount and enter both paths.",
              "Aucun fichier correspondant. Vérifiez le montage et indiquez les deux chemins.",
            );
        },
      ),
    );
  const value = () => ({
    ...data,
    ...(group === "library" ? { client_path: "" } : {}),
    purpose: group === "library" ? "library" : "download",
  });
  if (group === "library")
    fields.append(
      button(say("Preview grouping", "Aperçu du regroupement"), async () => {
        const result = await storageRequest("preview", value());
        if (result)
          feedback.textContent = [
            `${result.count} ${say("items", "éléments")} · ${result.episodes} ${say("episodes", "épisodes")}`,
            ...(result.items || []).map((item) => item.name),
            ...(result.errors || []),
          ].join("\n");
      }),
    );
  if (group === "paths")
    fields.append(
      button(say("Test mapping", "Tester la correspondance"), async () => {
        const result = await storageRequest("test", value());
        if (result) {
          feedback.textContent = [
            result.warning ||
              say("Mapping verified", "Correspondance vérifiée"),
            ...(result.checks || []).map((check) =>
              say(
                `${check.found} of ${check.total} torrents found`,
                `${check.found} torrents sur ${check.total} trouvés`,
              ),
            ),
            ...(result.unreachable || []).map((path) =>
              say(
                `The client cannot save into this Download Folder: ${path}`,
                `Le client ne peut pas enregistrer dans ce dossier de téléchargement : ${path}`,
              ),
            ),
          ].join("\n");
        }
      }),
    );
  fields.append(
    button(
      say("Save folder", "Enregistrer le dossier"),
      async () => {
        if (!data.local)
          throw Error(say("Choose a folder.", "Choisissez un dossier."));
        await storageRequest(
          group === "downloads"
            ? "download"
            : group === "paths"
              ? "mapping"
              : "save",
          value(),
        );
      },
      "primary",
    ),
  );
}
function storageSection(form, group) {
  const storage = snapshot.storage;
  if (group === "downloads") {
    const summary = box(
      form,
      say("Effective destinations", "Destinations effectives"),
    );
    for (const id of Object.keys(storage.indexer_categories)) {
      const row = element("div", undefined, "settings-field");
      row.append(
        element("strong", categoryName(id)),
        element(
          "span",
          storage.download_folders.effective[id] ||
            say(
              "Excluded: no download folder",
              "Exclu : aucun dossier de téléchargement",
            ),
        ),
      );
      summary.append(row);
    }
  }
  const rows =
    group === "library"
      ? storage.folders
      : group === "paths"
        ? storage.mappings.map((m) => ({ local: m.local, client_path: m.qbit }))
        : [
            ...(storage.download_folders.default
              ? [{ local: storage.download_folders.default, category: null }]
              : []),
            ...Object.entries(storage.download_folders.by_category).map(
              ([category, local]) => ({ local, category: Number(category) }),
            ),
          ];
  for (const row of rows) {
    const card = element("section", undefined, "client-card");
    card.append(element("h3", row.local));
    if (group === "paths") card.append(element("p", row.client_path));
    if (group === "downloads")
      card.append(
        element(
          "p",
          row.category === null
            ? say("Default", "Par défaut")
            : storage.indexer_categories[row.category]?.name || row.category,
        ),
      );
    const actions = element("div", undefined, "settings-actions");
    actions.append(
      button(say("Edit", "Modifier"), () => {
        drafts.set(draftKey(group), {
          ...row,
          ...(group === "library" ? { original_local: row.local } : {}),
          ...(group === "paths"
            ? {
                original_local: row.local,
                original_client_path: row.client_path,
              }
            : {}),
        });
        render();
      }),
    );
    actions.append(
      button(say("Remove", "Retirer"), async () => {
        if (
          !confirm(
            say(
              "Remove this folder from Settings? Files will be kept.",
              "Retirer ce dossier des paramètres ? Les fichiers seront conservés.",
            ),
          )
        )
          return;
        await storageRequest(group === "paths" ? "remove-mapping" : "remove", {
          ...row,
          purpose: group === "library" ? "library" : "download",
          confirmed: true,
        });
      }),
    );
    card.append(actions);
    form.append(card);
  }
  storageEditor(form, group);
}
async function saveGroup(group, form) {
  if (
    form.dataset.clientId !== environment.client_id ||
    snapshot?.client_id !== environment.client_id
  )
    throw Error(
      say(
        "The target client changed. Reopen Settings.",
        "Le client cible a changé. Rouvrez les paramètres.",
      ),
    );
  if (!form.reportValidity()) return;
  const client = environment.client_id;
  $("settings-status").textContent = say("Saving…", "Enregistrement…");
  const submitted = structuredClone(draft(group));
  const value = await request("save", { group, value: submitted });
  if (client !== environment.client_id) return;
  snapshot = value;
  if (JSON.stringify(draft(group)) === JSON.stringify(submitted))
    drafts.delete(draftKey(group));
  $("settings-status").textContent = say(
    "Settings saved",
    "Paramètres enregistrés",
  );
  render();
}
function render() {
  if (!snapshot || snapshot.client_id !== environment.client_id) return;
  $("settings-title").textContent = say("Settings", "Paramètres");
  const names = sections();
  $("settings-navigation").replaceChildren(
    ...Object.entries(names).map(([key, title]) => {
      const node = button(title, async () => {
        if (section === "agents") clearAgentToken();
        document.querySelectorAll("dialog").forEach((dialog) => dialog.close());
        section = key;
        render();
        await request("section", { section });
      });
      if (key === section) node.setAttribute("aria-current", "page");
      return node;
    }),
  );
  if (!snapshot) return;
  const form = element(
    ["agents", "assistant", "companion"].includes(section) ? "section" : "form",
    undefined,
    "settings-form",
  );
  form.dataset.clientId = snapshot.client_id;
  form.onsubmit = (event) => event.preventDefault();
  form.append(element("h2", names[section]));
  if (["connections", "general", "matching", "zen"].includes(section)) {
    if (section === "connections") connections(form);
    else preferences(form, section);
    const actions = element("div", undefined, "settings-actions");
    actions.append(
      button(
        say("Save", "Enregistrer"),
        () => saveGroup(section, form),
        "primary",
      ),
      button(say("Discard changes", "Annuler les modifications"), () => {
        drafts.delete(draftKey(section));
        render();
      }),
    );
    form.append(actions);
  } else if (section === "agents") {
    const root = element("div");
    form.append(root);
    queueMicrotask(() => settingsAgents(root));
  } else if (section === "companion") {
    const root = element("section", undefined, "settings-card");
    form.append(root);
    queueMicrotask(() => guard(() => loadSettingsCompanion(root)));
  } else if (section === "assistant") {
    const root = element("div");
    root.id = "assistant-connections-body";
    form.append(root);
    queueMicrotask(() => guard(loadSettingsAssistant));
  } else if (["library", "downloads", "paths"].includes(section)) {
    storageSection(form, section);
  } else if (section === "clients") {
    clients(form);
  }
  $("settings-body").replaceChildren(form);
}
async function applyEnvironment(value) {
  const changed = environment.client_id !== value.client_id;
  const activated = !environment.active && value.active;
  if (changed || (environment.active && !value.active)) {
    clearAgentToken();
    document.querySelectorAll("dialog").forEach((dialog) => dialog.close());
  }
  const translated = language !== (value.language || "en");
  const previousSection = section;
  const missing = !snapshot;
  if (
    value.section &&
    value.section !== environment.section &&
    Object.hasOwn(sections(), value.section)
  )
    section = value.section;
  environment = value;
  language = value.language || "en";
  document.documentElement.lang = language;
  document.documentElement.dataset.theme = value.theme || "dark";
  if (!request) return;
  if (!snapshot && loadingClient === environment.client_id) return;
  if (changed || !snapshot || activated) {
    for (const group of ["connections", "general", "matching", "zen"]) {
      const key = draftKey(group);
      if (
        drafts.has(key) &&
        JSON.stringify(drafts.get(key)) === draftBaselines.get(key)
      ) {
        drafts.delete(key);
        draftBaselines.delete(key);
      }
    }
    snapshot = null;
    $("settings-navigation").inert = true;
    $("settings-body").replaceChildren(
      element("p", say("Loading Settings…", "Chargement des paramètres…")),
    );
    const current = ++generation;
    loadingClient = environment.client_id;
    let result;
    try {
      result = await request("snapshot");
    } finally {
      if (current === generation) loadingClient = undefined;
    }
    if (current !== generation) return;
    snapshot = result;
    $("settings-navigation").inert = false;
  }
  if (
    changed ||
    translated ||
    missing ||
    activated ||
    section !== previousSection
  )
    render();
}
window.addEventListener("settings-environment", (event) =>
  guard(() => applyEnvironment(event.detail)),
);
window.addEventListener("message", (event) => {
  if (
    event.source !== parent ||
    event.origin !== location.origin ||
    event.data?.type !== "settings-clear-secrets"
  )
    return;
  clearAgentToken();
  document.querySelectorAll("dialog").forEach((dialog) => dialog.close());
});
window.addEventListener("DOMContentLoaded", async () => {
  const transport = await TLPanel.connect("settings", { asynchronous: true });
  request = (action, body = {}) =>
    transport(action, { ...body, _client: environment.client_id });
  window.settingsReady();
});
