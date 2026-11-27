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
// Secrets shown by their eye (secrets.js), hidden again when Settings clears secrets.
const revealedSecrets = new Set();
function hideRevealedSecrets() {
  for (const hide of [...revealedSecrets]) hide();
}
function clearAgentToken() {
  agentTokenGeneration++;
  if ($("agent-token")) $("agent-token").value = "";
  if ($("agent-token-box")) $("agent-token-box").hidden = true;
}
// A Member's Settings hold only their account, and Utilisateurs for a manager (#135).
const sections = () =>
  environment.member
    ? Object.fromEntries(
        [
          ["account", say("My account", "Mon compte")],
          ["notifications", say("Notifications", "Notifications")],
          ["users", say("Users", "Utilisateurs")],
        ].filter(([key]) => (environment.sections || []).includes(key)),
      )
    : ownerSections();
const ownerSections = () => ({
  connections: say("Connections", "Connexions"),
  community_site: say("Join the community", "Rejoindre la communauté"),
  agents: say("Agent access", "Accès agent"),
  assistant: "Assistant",
  general: say("General", "Général"),
  library: say("Library Folders", "Dossiers de bibliothèque"),
  downloads: say("Download Folders", "Dossiers de téléchargement"),
  paths: say("Client Paths", "Chemins du client"),
  matching: say("Search & Matching", "Recherche et correspondance"),
  release_score: "ReleaseScore",
  zen: "Zen",
  // Members share only a Web or Docker server; the desktop stays the Owner's.
  ...(environment.mode === "web" && environment.members_enabled
    ? { users: say("Users", "Utilisateurs"), account: say("My account", "Mon compte"), notifications: "Notifications" }
    : {}),
});
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
// The server's fixed sentences, in the user's language; several lines become one message.
const settingsMessages = {
  "Client address: enter for example http://192.168.0.50:8080, without user name, password, query or fragment.":
    "Adresse du client : saisissez par exemple http://192.168.0.50:8080, sans identifiant, mot de passe, paramètres ni fragment.",
  "Client address: the port must be between 1 and 65535.":
    "Adresse du client : le port doit être compris entre 1 et 65535.",
  "Indexer address: enter a full address such as https://c411.org/api/torznab, without user name, password, query or fragment.":
    "Adresse de l’indexeur : saisissez une adresse complète comme https://c411.org/api/torznab, sans identifiant, mot de passe, paramètres ni fragment.",
  "Client address: enter rTorrent's SCGI address as scgi://host:port, for example scgi://192.168.0.50:5000.":
    "Adresse du client : saisissez l’adresse SCGI de rTorrent sous la forme scgi://hôte:port, par exemple scgi://192.168.0.50:5000.",
  "Client address: scgi:// is only for rTorrent; use http://host:port.":
    "Adresse du client : scgi:// est réservé à rTorrent ; utilisez http://hôte:port.",
};
function settingsError(message) {
  return String(message)
    .split("\n")
    .map((line) =>
      language !== "fr"
        ? line
        : settingsMessages[line] ||
          line.replace(/^Invalid value: /, "Valeur invalide : "),
    )
    .join(" ");
}
async function guard(work) {
  $("settings-error").textContent = "";
  document
    .querySelectorAll(".settings-modal-error")
    .forEach((node) => node.remove());
  try {
    return await work();
  } catch (error) {
    error.message = settingsError(fileAccessError(error.message));
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
// Every action button: busy while it runs (panel/toast.js); its result is a toast (an action
// may return the message to show; failures and the status line reach it below).
function button(text, action, className = "") {
  const client = environment.client_id;
  const node = element("button", text, className);
  node.type = "button";
  node.onclick = () =>
    TLToast.busy(node, () =>
      guard(() => {
        if (client !== environment.client_id || snapshot?.client_id !== client)
          throw Error(
            say(
              "Wait for the selected client's settings.",
              "Attendez les paramètres du client sélectionné.",
            ),
          );
        return action();
      }),
    );
  return node;
}
// Whatever the panel writes to its status or error line also becomes a toast, so no result
// is ever out of sight; "Unsaved changes" and progress ("Saving…") stay quiet.
function toastLines() {
  const watch = (id, kind) => {
    const line = $(id);
    if (!line) return;
    new MutationObserver(() => {
      const text = line.textContent.trim();
      if (text && !text.endsWith("…") && !/^(Unsaved changes|Modifications non enregistrées)$/.test(text))
        TLToast.show(text, kind);
    }).observe(line, { childList: true, characterData: true, subtree: true });
  };
  watch("settings-status", "ok");
  watch("settings-error", "bad");
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
function secret(form, label, data, key, saved, own = null) {
  const input = field(form, label, data, key, "password");
  input.autocomplete = "new-password";
  input.placeholder = saved ? "" : say("Not saved", "Non enregistré");
  input.oninput = () => {
    if (input.value) data[key] = input.value;
    else delete data[key];
    $("settings-status").textContent = say(
      "Unsaved changes",
      "Modifications non enregistrées",
    );
  };
  const connection = draft("connections");
  let cleared = false;
  const reference =
    own?.reference ??
    (key === "tmdb_api_key"
      ? "tmdb-api-key"
      : key === "announce_url"
        ? "announce-url"
        : key === "api_key"
          ? data === connection.indexer
            ? "indexer-api-key"
            : "client-api-key"
          : data === connection.proxy
            ? "proxy-password"
            : "client-password");
  const kind =
    { qbittorrent: "qbit", bittorrent: "utorrent" }[connection.client.client] ||
    connection.client.client;
  let name = own?.name ??
    (key === "tmdb_api_key"
      ? "tmdb-api-key"
      : key === "announce_url"
        ? "announce-url"
        : key === "api_key"
          ? data === connection.indexer
            ? "indexer-api-key"
            : "qbit-api-key"
          : data === connection.proxy
            ? "proxy-password"
            : `${kind}-password`);
  if (!own && data === connection.client && environment.client_id !== "default")
    name = `client-${environment.client_id}-${name}`;
  if (snapshot.connections.managed_secrets.includes(name)) {
    input.disabled = true;
    input.placeholder = say("Managed by deployment", "Géré par le déploiement");
  } else {
    // The eye also shows a value being typed; only a stored one is fetched.
    const wrap = secretInput(input, reference, () => saved && !cleared);
    if (saved)
      wrap.after(
        button(say("Clear saved value", "Effacer la valeur enregistrée"), () => {
          cleared = true;
          hideRevealedSecrets();
          data[key] = "";
          unmaskSecret(input);
          input.placeholder = say(
            "Will be cleared on Save",
            "Sera effacé à l’enregistrement",
          );
        }),
      );
  }
  return input;
}
const EXTRA_KEY_LIMIT = 4;
// Each saved additional API key is its own masked field with an eye and a remove button; the
// page never holds the saved values, so an untouched one is sent back as `{keep: slot}`.
function extraKeys(parent, data, slots) {
  const managed = snapshot.connections.managed_secrets.some((name) =>
    name.startsWith("indexer-extra-key-"),
  );
  const rows = (
    data.indexer.extra_keys ?? slots.map((slot) => ({ keep: slot }))
  ).map((entry) =>
    typeof entry === "string"
      ? { slot: null, value: entry }
      : { slot: entry.keep, value: "" },
  );
  const changed = () => {
    data.indexer.extra_keys = rows.map((row) =>
      row.value || row.slot === null ? row.value : { keep: row.slot },
    );
    $("settings-status").textContent = say(
      "Unsaved changes",
      "Modifications non enregistrées",
    );
  };
  const card = element("div", undefined, "settings-field");
  card.append(
    element("span", say("Additional API keys", "Clés API supplémentaires")),
  );
  const list = element("div"),
    add = button(say("Add an API key", "Ajouter une clé API"), () => {
      rows.push({ slot: null, value: "" });
      changed();
      draw();
    });
  const draw = () => {
    hideRevealedSecrets();
    list.replaceChildren();
    rows.forEach((row, index) => {
      const item = element("div", undefined, "extra-key-row"),
        input = element("input"),
        label = `${say("Additional API key", "Clé API supplémentaire")} ${index + 1}`;
      input.type = "password";
      input.autocomplete = "new-password";
      input.setAttribute("aria-label", label);
      input.value = row.value;
      input.placeholder = managed
        ? say("Managed by deployment", "Géré par le déploiement")
        : "";
      input.disabled = managed;
      input.oninput = () => {
        row.value = input.value;
        changed();
      };
      item.append(input);
      if (!managed) {
        item.append(secretInput(
            input,
            row.slot === null ? "" : `extra-key:${row.slot}`,
            () => row.slot !== null && !row.value,
          ));
        const remove = button(say("Remove", "Retirer"), () => {
          rows.splice(index, 1);
          changed();
          draw();
        });
        remove.setAttribute(
          "aria-label",
          `${say("Remove", "Retirer")} ${label.toLowerCase()}`,
        );
        item.append(remove);
      }
      list.append(item);
    });
    add.hidden = managed || rows.length >= EXTRA_KEY_LIMIT;
  };
  draw();
  card.append(list, add);
  parent.append(card);
}
function box(form, title) {
  const box = element("section", undefined, "settings-card"),
    fields = element("div", undefined, "settings-fields");
  box.append(element("h3", title), fields);
  form.append(box);
  return fields;
}
// Connections is one draft saved by one button; its tabs only decide which cards are shown.
const connectionTabs = () => [
  ["c411", "c411"],
  ["tr4ker", "tr4ker"],
  ["indexers", say("Indexers", "Indexeurs")],
  ["clients", "Clients"],
  ["companion", say("Companion", "Compagnon")],
  ["services", "Services"],
];
let connectionTab = "c411";
// An older link or saved location to Clients, Indexers or Companion lands on that tab.
const connectionTabOf = (value) =>
  ["clients", "indexers", "companion"].includes(value) ? value : null;
const hasSecret = (data, key, saved) => Boolean(data[key]) || (saved && data[key] !== "");
function connectionTabBar(form) {
  const data = draft("connections");
  const bar = element("div", undefined, "conn-tabs");
  bar.setAttribute("role", "tablist");
  for (const [id, label] of connectionTabs()) {
    const node = element("button", label);
    node.type = "button";
    node.setAttribute("role", "tab");
    node.setAttribute("aria-selected", String(id === connectionTab));
    if (id === "tr4ker" && data.trackers?.tr4ker?.enabled)
      node.append(" ", element("span", say("on", "actif"), "conn-tag on"));
    const count = id === "indexers" ? snapshot.indexer_count : id === "clients" ? snapshot.clients.length : null;
    if (count !== null) node.append(" ", element("small", String(count), "muted"));
    node.onclick = () => {
      if (id === connectionTab) return;
      hideRevealedSecrets();
      document.querySelectorAll("dialog").forEach((dialog) => dialog.close());
      connectionTab = id;
      $("settings-status").textContent = "";
      render();
    };
    bar.append(node);
  }
  form.append(bar);
}
function saveBar(form, group) {
  const actions = element("div", undefined, "settings-actions");
  actions.append(
    button(say("Save", "Enregistrer"), () => saveGroup(group, form), "primary"),
    button(say("Discard changes", "Annuler les modifications"), () => {
      drafts.delete(draftKey(group));
      render();
    }),
  );
  form.append(actions);
}
function connections(form) {
  connectionTabBar(form);
  if (connectionTab === "indexers") {
    const root = element("div");
    form.append(root);
    queueMicrotask(() => guard(() => settingsIndexers(root)));
    return;
  }
  if (connectionTab === "companion") {
    const root = element("div");
    form.append(root);
    queueMicrotask(() => guard(() => loadSettingsCompanion(root)));
    return;
  }
  if (connectionTab === "c411") c411Tab(form);
  else if (connectionTab === "tr4ker") tr4kerTab(form);
  else if (connectionTab === "clients") clientsTab(form);
  else servicesTab(form);
  saveBar(form, "connections");
}
function note(text) {
  return element("p", text, "muted");
}
function c411Tab(form) {
  const data = draft("connections"),
    saved = snapshot.connections.secrets;
  form.append(
    note(
      say(
        "The c411 Tracker: the Indexer's address and keys, the Announce URL and its backup hosts. The other search Indexers are in the Indexers tab.",
        "Le tracker c411 : adresse et clés de l’indexeur, adresse d’annonce et hôtes de secours. Les autres indexeurs de recherche sont dans l’onglet Indexeurs.",
      ),
    ),
  );
  const indexer = box(form, say("c411 Indexer", "Indexeur c411"));
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
  const hostsLabel = element(
    "label",
    say(
      "c411 announce hosts · current first, then backups",
      "Hôtes d’annonce c411 · actuel puis secours",
    ),
    "settings-field",
  );
  const hosts = element("textarea");
  hosts.value = (data.announce_hosts || []).join("\n");
  hosts.oninput = () => {
    data.announce_hosts = hosts.value.split(/\s+/).filter(Boolean);
  };
  hostsLabel.append(hosts);
  indexer.append(hostsLabel);
  extraKeys(indexer, data, saved.extra_key_slots || []);
  indexer.append(button(say("Test Indexer", "Tester l’indexeur"), async () => {
    const result = await request("test-connection", {
      group: "indexer",
      value: structuredClone(data.indexer),
    });
    return [
      `c411 ${say("answers", "répond")}`,
      `${result.categories} ${say("categories", "catégories")}`,
      `${result.keys} ${say(result.keys === 1 ? "key" : "keys", result.keys === 1 ? "clé" : "clés")}`,
    ].join(" · ");
  }));
  indexer.parentElement.append(
    element(
      "p",
      say(
        "Additional keys are other keys of the same account (up to 4, ADR-0008).",
        "Les clés supplémentaires sont d’autres clés du même compte (jusqu’à 4, ADR-0008).",
      ),
      "muted card-note",
    ),
  );
  const card = element("section", undefined, "settings-card");
  card.append(element("h3", say("c411 companion", "Compagnon c411")));
  form.append(card);
  queueMicrotask(() => guard(() => companionLine(card, "c411")));
}
const declinedAdoption = new Set();
let adoptedNotice = false;
// The saved switch of the draft, kept in step when an action (adopting) changes it at once.
function changeDraft(change) {
  const key = draftKey("connections"),
    clean = !drafts.has(key) || JSON.stringify(drafts.get(key)) === draftBaselines.get(key);
  change(draft("connections"));
  if (clean) draftBaselines.set(key, JSON.stringify(drafts.get(key)));
}
function adoptCard(offer) {
  const card = element("section", undefined, "settings-card conn-offer");
  const history = offer.history;
  const records = say(
    `${history} ${history === 1 ? "record" : "records"}`,
    `${history} ${history > 1 ? "enregistrements" : "enregistrement"}`,
  );
  const crossSeeds = say(
    `${history} Cross-${history === 1 ? "seed" : "seeds"}`,
    `${history} cross-seed${history > 1 ? "s" : ""}`,
  );
  card.append(
    element("h3", say("A tr4ker Indexer already exists", "Un indexeur tr4ker existe déjà")),
    element(
      "p",
      say(
        `“${offer.name}”${offer.source ? `, imported from ${offer.source},` : ""} points to tr4ker. You can take it over here: the history of its Cross-seeds (${records}) moves to tr4ker, which then searches its own address with its own API key${offer.needs_key ? " (enter it below; the hub's key is not tr4ker's)" : ""}, and it leaves the Indexers list, so tr4ker is never searched twice.`,
        `« ${offer.name} »${offer.source ? `, importé de ${offer.source},` : ""} pointe vers tr4ker. Vous pouvez le reprendre ici : l’historique de ses cross-seeds (${records}) passe à tr4ker, qui cherche ensuite à sa propre adresse avec sa propre clé API${offer.needs_key ? " (saisissez-la ci-dessous ; la clé du hub n’est pas celle de tr4ker)" : ""}, et il quitte la liste des indexeurs, pour que tr4ker ne soit jamais cherché deux fois.`,
      ),
    ),
  );
  const actions = element("div", undefined, "settings-actions");
  actions.append(
    button(
      say("Take over this Indexer", "Reprendre cet indexeur"),
      async () => {
        const client = environment.client_id;
        const result = await request("adopt-indexer", { tracker: "tr4ker" });
        if (client !== environment.client_id) return;
        snapshot = result;
        adoptedNotice = true;
        changeDraft((data) => (data.trackers.tr4ker.enabled = true));
        render();
        return say(
          `Indexer taken over: API key and ${crossSeeds} kept; it left the Indexers list`,
          `Indexeur repris : clé API et ${crossSeeds} conservé${history > 1 ? "s" : ""} ; il a quitté la liste des indexeurs`,
        );
      },
      "primary",
    ),
    button(say("Leave it in the Indexers", "Le laisser dans les indexeurs"), async () => {
      declinedAdoption.add("tr4ker");
      render();
      return say(
        "Indexer left in the list. Note: tr4ker would be searched twice if you turn it on here.",
        "Indexeur laissé dans la liste. Attention : tr4ker serait cherché deux fois si vous l’activez ici.",
      );
    }),
  );
  card.append(
    actions,
    element(
      "p",
      say("A new Prowlarr sync will not create it again.", "Une nouvelle synchronisation Prowlarr ne le recréera pas."),
      "muted",
    ),
  );
  return card;
}
function tr4kerTab(form) {
  const data = draft("connections").trackers.tr4ker,
    saved = snapshot.connections.secrets.trackers.tr4ker,
    registry = snapshot.tracker_registry.tr4ker,
    offer = snapshot.adoptable.tr4ker;
  form.append(
    note(
      say(
        "tr4ker is a Tracker in its own right, like c411: an account, an API and its own rules. Its results join c411's, each row carrying its Tracker.",
        "tr4ker est un tracker à part entière, comme c411 : un compte, une API et ses propres règles. Ses résultats s’ajoutent à ceux de c411, chaque ligne portant son tracker.",
      ),
    ),
  );
  if (offer && !declinedAdoption.has("tr4ker")) form.append(adoptCard(offer));
  const power = element("section", undefined, "settings-card");
  power.append(element("h3", "tr4ker"));
  const toggle = field(power, say("Turn on tr4ker", "Activer tr4ker"), data, "enabled", "checkbox");
  toggle.addEventListener("change", () => {
    $("settings-status").textContent = data.enabled
      ? say("tr4ker turned on: enter its API key", "tr4ker activé : saisissez sa clé API")
      : say("tr4ker turned off", "tr4ker désactivé");
    render();
  });
  if (adoptedNotice)
    power.append(
      note(
        say(
          "Indexer taken over: Cross-seed history kept; tr4ker searches its own address with its own API key.",
          "Indexeur repris : historique des cross-seeds conservé ; tr4ker cherche à sa propre adresse avec sa propre clé API.",
        ),
      ),
    );
  form.append(power);
  const api = element("section", undefined, `settings-card${data.enabled ? "" : " is-off"}`);
  api.append(element("h3", say("API access", "Accès à l’API")));
  const fields = element("div", undefined, "settings-fields");
  api.append(fields);
  const keyInput = secret(fields, say("tr4ker API key", "Clé API de tr4ker"), data, "api_key", saved.api_key, {
    reference: "indexer:tr4ker",
    name: "indexer-key-tr4ker",
  });
  const passkeyInput = secret(fields, say("tr4ker passkey", "Passkey de tr4ker"), data, "passkey", saved.passkey, {
    reference: "passkey:tr4ker",
    name: "indexer-passkey-tr4ker",
  });
  const announce = element("label", say("Announce URL", "URL d’annonce"), "settings-field");
  const shown = element("input");
  shown.readOnly = true;
  shown.value = `https://${registry.announce_host}/announce/…`;
  shown.setAttribute("aria-label", say("tr4ker Announce URL", "URL d’annonce tr4ker"));
  announce.append(shown);
  fields.append(announce);
  const live = () => data.enabled && hasSecret(data, "api_key", saved.api_key);
  const test = button(say("Test tr4ker", "Tester tr4ker"), async () => {
    const result = await request("test-connection", {
      group: "tr4ker",
      value: { api_key: secretValue(keyInput) || undefined },
    });
    const ids = result.searchable_ids.map(idLabel);
    return [
      say("tr4ker answers", "tr4ker répond"),
      `${say("search by", "recherche par")} ${ids.join(` ${say("and", "et")} `) || say("name", "nom")}`,
      `${result.modes} ${say("search modes", "modes de recherche")}`,
    ].join(" · ");
  });
  fields.append(test);
  api.append(
    note(
      say(
        `The API key serves search, Cross-seed and .torrent downloads. The passkey serves the RSS feeds and the Announce URL (host ${registry.announce_host}). Both are kept in the keyring and never sent back to the screen.`,
        `La clé API sert à la recherche, au cross-seed et au téléchargement des .torrent. Le passkey sert aux flux RSS et à l’adresse d’annonce (hôte ${registry.announce_host}). Les deux sont conservés dans le trousseau, jamais renvoyés à l’écran.`,
      ),
    ),
  );
  form.append(api);
  const companion = element("section", undefined, `settings-card${data.enabled ? "" : " is-off"}`);
  companion.append(element("h3", say("tr4ker companion", "Compagnon tr4ker")));
  form.append(companion);
  queueMicrotask(() => guard(() => companionLine(companion, "tr4ker")));
  companion.append(
    note(
      say(
        "The profile, the torrent details and publishing go through your tr4ker session in the browser; no cookie leaves the browser.",
        "Le profil, le détail des torrents et la publication passent par votre session tr4ker dans le navigateur ; aucun cookie ne quitte le navigateur.",
      ),
    ),
  );
  const works = element("section", undefined, "settings-card");
  works.append(element("h3", say("What works", "Ce qui fonctionne")));
  const table = element("table", undefined, "file-access-capabilities");
  const body = element("tbody");
  table.append(body);
  works.append(table);
  form.append(works);
  // The companion line below reports whether a tr4ker session is paired.
  let sessionPaired = false;
  form.addEventListener("companion-state", (event) => {
    sessionPaired = event.detail.paired;
    drawCapabilities();
  });
  const drawCapabilities = () => {
    const has = (name) => registry.capabilities.includes(name);
    const row = (name, state, why) => {
      const cell = element("td");
      if (state === "live") cell.append(element("span", say("Available", "Disponible"), "conn-tag on"));
      else if (state === "needs") cell.append(element("span", why, "conn-tag warn"));
      else
        cell.append(
          element("span", say("Unavailable", "Indisponible"), "conn-tag bad"),
          " ",
          element("span", why, "unavailable"),
        );
      const line = element("tr");
      line.append(element("th", name), cell);
      body.append(line);
    };
    body.replaceChildren();
    if (has("search") || has("crossseed"))
      row(
        say("Search, Cross-seed and downloads", "Recherche, Cross-seed et téléchargements"),
        live() ? "live" : "needs",
        say("API key needed", "Clé API requise"),
      );
    if (has("rss"))
      row(
        say("RSS feeds and Announce URL", "Flux RSS et adresse d’annonce"),
        data.enabled && hasSecret(data, "passkey", saved.passkey) ? "live" : "needs",
        say("Passkey needed", "Passkey requis"),
      );
    if (has("profile") || has("upload") || has("community"))
      row(
        say("Profile, torrent details, publishing", "Profil, détail d’un torrent, publication"),
        registry.companion ? (sessionPaired ? "live" : "needs") : "none",
        registry.companion
          ? say("Paired tr4ker session needed", "Session tr4ker appairée requise")
          : say("Unavailable", "Indisponible"),
      );
    if (!has("zen"))
      row(
        "Zen",
        "none",
        say(
          "tr4ker has no Zen: its credits are a learned estimate",
          "tr4ker n’a pas de Zen : ses crédits sont une estimation apprise",
        ),
      );
    test.disabled = !live();
  };
  drawCapabilities();
  for (const input of [keyInput, passkeyInput]) input.addEventListener("input", drawCapabilities);
  // Clearing a saved value is a click, not typing.
  for (const clear of fields.querySelectorAll("button"))
    if (clear !== test) clear.addEventListener("click", () => queueMicrotask(drawCapabilities));
}
function clientsTab(form) {
  form.append(
    note(
      say(
        "The Torrent Clients where Reseeds, Cross-seeds and Plans are added, whichever Tracker. Paths stay in “Client Paths”.",
        "Les clients torrent où les remises en seed, cross-seeds et plans sont ajoutés, quel que soit le tracker. Les chemins restent dans « Chemins du client ».",
      ),
    ),
  );
  clients(form);
  const data = draft("connections"),
    saved = snapshot.connections.secrets;
  const client = box(form, say("Torrent Client", "Client torrent"));
  client.parentElement.id = "client-box";
  client.before(
    element(
      "p",
      `${say("Selected client", "Client sélectionné")} : ${data.client.name || snapshot.clients.find((c) => c.id === snapshot.client_id)?.name || ""}`,
      "muted selected-client",
    ),
  );
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
  const requiresLinks = ["utorrent", "bittorrent", "rtorrent"].includes(
    data.client.client,
  );
  const layout = field(
    client,
    say("Reseed layout", "Organisation de la remise en seed"),
    data,
    "reseed_layout",
    "text",
    requiresLinks
      ? [
          [
            "auto",
            say(
              "Links required for this client",
              "Liens requis pour ce client",
            ),
          ],
          ["links", say("Links", "Liens")],
        ]
      : [
          [
            "auto",
            say(
              "Default: rename inside the client",
              "Par défaut : renommer dans le client",
            ),
          ],
          [
            "client",
            say("Rename inside the client", "Renommer dans le client"),
          ],
          [
            "links",
            say(
              "Links: keep original torrent paths",
              "Liens : conserver les chemins du torrent",
            ),
          ],
        ],
  );
  if (requiresLinks) {
    layout.disabled = true;
    layout.value = data.reseed_layout === "links" ? "links" : "auto";
  }
  const linkFolder = field(
    client,
    say("Reseed link folder", "Dossier des liens de remise en seed"),
    data,
    "reseed_link_root",
  );
  const layoutNote = element("p", undefined, "file-access-note");
  client.append(layoutNote);
  const showLayout = () => {
    const links = requiresLinks || data.reseed_layout === "links";
    linkFolder.closest("label").hidden = !links;
    layoutNote.textContent = links
      ? say(
          "Links preserve original files and the torrent’s paths. Keep the Link Folder outside the Library for as long as its torrents seed. This client choice also applies to Local Items.",
          "Les liens préservent les fichiers originaux et les chemins du torrent. Conservez le dossier de liens hors bibliothèque tant que ses torrents partagent. Ce choix s’applique aussi aux éléments locaux.",
        )
      : say(
          "Paths are renamed inside the Torrent Client. Original files stay in place; no Link Folder is needed. Existing link layouts are kept.",
          "Les chemins sont renommés dans le client torrent. Les fichiers originaux restent en place ; aucun dossier de liens n’est nécessaire. Les liens existants sont conservés.",
        );
  };
  layout.addEventListener("input", showLayout);
  showLayout();
  client.append(linkFolderCard(data.client.client, requiresLinks, data.reseed_link_root));
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
  client.append(button(say("Test connection", "Tester la connexion"), async () => {
    const result = await request("test-connection", {
      group: "client",
      value: structuredClone(data.client),
    });
    return `${say("Connected", "Connecté")} · ${result.version}`;
  }));
  fileAccessCard(form);
}
// What the Link Folder is used for with this client, and whether the client requires it.
const linkFolderNative = {
  qbittorrent: ["setLocation and renaming the torrent's paths", "setLocation et le renommage des chemins du torrent"],
  deluge: ["move_storage and renaming the torrent's paths", "move_storage et le renommage des chemins du torrent"],
  transmission: ["torrent-set-location and renaming the torrent's paths", "torrent-set-location et le renommage des chemins du torrent"],
};
function linkFolderCard(type, required, root) {
  const name = { qbittorrent: "qBittorrent", deluge: "Deluge", transmission: "Transmission", utorrent: "µTorrent", bittorrent: "BitTorrent", rtorrent: "rTorrent" }[type] || type;
  const native = say(...(linkFolderNative[type] || ["", ""]));
  const uses = [
    [
      say("Reseed of a torrent whose file or subfolder names differ from the library", "Remise en seed d’un torrent dont les noms de fichiers ou de sous-dossiers diffèrent de la médiathèque"),
      required
        ? say("Always through links: this client cannot rename a torrent's paths, and renaming would change your original files. Links reproduce the torrent's layout without touching the originals.", "Toujours par liens : ce client ne sait pas renommer les chemins d’un torrent, renommer changerait vos fichiers d’origine. Les liens reproduisent la disposition du torrent sans toucher aux originaux.")
        : say("By default the client renames the paths inside the torrent: no links. Choose “Links” only to keep the torrent's original layout (cross-seed).", "Par défaut le client renomme les chemins dans le torrent : aucun lien. Choisissez « Liens » seulement pour garder la disposition d’origine du torrent (cross-seed)."),
    ],
    [
      say("Organisation (Fichiers › Organisation) of files already seeding", "Organisation (Fichiers › Organisation) des fichiers déjà en partage"),
      required
        ? say("The client cannot rename: the file is renamed on disk, then the torrent is pointed at it again and rechecked through the Link Folder. Without one, those rows read “needs a Link Folder”.", "Le client ne peut pas renommer : le fichier est renommé sur le disque, puis le torrent est re-pointé et revérifié via le Dossier de liens. Sans lui, ces lignes affichent « nécessite un Dossier de liens ».")
        : say(`The client renames and moves by itself (${native}): no Link Folder. It only serves a torrent whose layout differs from the library (a Subs/ folder, extra files at the root).`, `Le client renomme et déplace lui-même (${native}) : pas de Dossier de liens. Il ne sert que pour un torrent dont la disposition diffère de la bibliothèque (dossier Subs/, fichiers en plus à la racine).`),
    ],
    [
      say("Moving a seeding file (Fichiers › Explorateur)", "Déplacement d’un fichier en partage (Fichiers › Explorateur)"),
      required
        ? say("Pause, move, point again, recheck, resume: done by TorrentLinker, without a Link Folder, but the client is stopped during the operation.", "Pause, déplacement, re-pointage, revérification, reprise : fait par TorrentLinker, sans Dossier de liens, mais le client doit être arrêté pendant l’opération.")
        : say("Native: the client moves it itself, the Link Folder does not take part.", "Natif : le client déplace lui-même, le Dossier de liens n’intervient pas."),
    ],
  ];
  const card = element("div", undefined, "link-folder-card");
  const head = element("div", undefined, "link-folder-head");
  const text = uses.map(([title, detail]) => `${title} : ${detail}`).join("\n\n") + "\n\n" + say("Keep the Link Folder outside the library for as long as its torrents seed: links are permanent.", "Gardez le Dossier de liens hors de la bibliothèque tant que ses torrents partagent : les liens sont permanents.");
  const info = document.createElement("span");
  info.innerHTML = TLInfo.html(text, say("What the Link Folder is used for", "À quoi sert le Dossier de liens"));
  head.append(
    element("b", say(`Link Folder · ${name}`, `Dossier de liens · ${name}`)), info.firstChild,
    element("span", required ? say("Required", "Requis") : say("Optional", "Facultatif"), required ? "link-folder-badge required" : "link-folder-badge"),
  );
  card.append(head);
  if (required && !String(root || "").trim()) {
    const todo = element("p", undefined, "link-folder-warn");
    const why = document.createElement("span");
    why.innerHTML = TLInfo.html(say(`Enter the folder above, outside the library, so that Reseed and Organisation can work with ${name}.`, `Indiquez le dossier ci-dessus, hors de la bibliothèque, pour que Remise en seed et Organisation puissent fonctionner avec ${name}.`), say("Why", "Pourquoi"));
    todo.append(element("b", say("To set up", "À configurer")), " ", why.firstChild);
    card.append(todo);
  }
  return card;
}
function servicesTab(form) {
  const data = draft("connections"),
    saved = snapshot.connections.secrets;
  const tmdb = box(form, "TMDb");
  const tmdbKey = secret(
    tmdb,
    say("TMDb API key", "Clé API TMDb"),
    data,
    "tmdb_api_key",
    saved.tmdb_api_key,
  );
  tmdb.append(button(say("Test the TMDb key", "Tester la clé TMDb"), async () => {
    await request("test-connection", {
      group: "tmdb",
      value: { api_key: secretValue(tmdbKey) || undefined },
    });
    return say("TMDb answers · key accepted", "TMDb répond · clé acceptée");
  }));
  tmdb.parentElement.append(
    element(
      "small",
      say(
        "Also gives films and series their French Age Rating when their NFO has none.",
        "Donne aussi aux films et séries leur classification française quand leur NFO n’en a pas.",
      ),
      "muted",
    ),
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
  proxy.append(button(say("Test proxy", "Tester le proxy"), async () => {
    const result = await request("test-connection", {
      group: "proxy",
      value: structuredClone(data.proxy),
    });
    return `${say("Address seen by c411", "Adresse vue par c411")} : ${result.ip}`;
  }));
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
    const layout = field(
      fields,
      say("Media interface", "Interface multimédia"),
      data,
      "media_layout",
      "",
      [
        ["cinematic", say("Cinematic home", "Accueil cinéma")],
        ["focus", "Focus"],
        ["horizon", "Horizon"],
      ],
    );
    const horizon = field(
      fields,
      say("Horizon view", "Vue Horizon"),
      data,
      "media_horizon",
      "",
      [
        ["home", say("Home", "Accueil")],
        ["showcase", "Showcase"],
        ["wall", say("Wall", "Mur")],
      ],
    );
    // Horizon's own choice shows only while Horizon is the interface.
    const showHorizon = () =>
      (horizon.parentElement.hidden = layout.value !== "horizon");
    layout.addEventListener("input", showHorizon);
    showHorizon();
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
    const card = element(
      "section",
      undefined,
      `client-card${client.id === snapshot.client_id ? " selected" : ""}`,
    );
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
  render();
  $("settings-status").textContent = say(
    "Settings saved",
    "Paramètres enregistrés",
  );
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
    ["agents", "assistant", "users", "account", "notifications", "community_site"].includes(section) ||
      (section === "connections" && ["indexers", "companion"].includes(connectionTab))
      ? "section"
      : "form",
    undefined,
    "settings-form",
  );
  form.dataset.clientId = snapshot.client_id;
  form.onsubmit = (event) => event.preventDefault();
  form.append(element("h2", names[section]));
  if (["connections", "general", "matching", "zen"].includes(section)) {
    if (section === "connections") connections(form);
    else {
      preferences(form, section);
      saveBar(form, section);
    }
  } else if (section === "release_score") {
    settingsReleaseScore(form);
  } else if (section === "agents") {
    const root = element("div");
    form.append(root);
    queueMicrotask(() => settingsAgents(root));
  } else if (section === "users") {
    const root = element("div");
    form.append(root);
    queueMicrotask(() => guard(() => settingsMembers(root)));
  } else if (section === "community_site") {
    const root = element("section", undefined, "settings-card");
    form.append(root);
    queueMicrotask(() => guard(() => communitySiteSettings(root)));
  } else if (section === "notifications") {
    const root = element("div"); form.append(root);
    queueMicrotask(() => guard(() => settingsNotifications(root)));
  } else if (section === "account") {
    const root = element("div");
    form.append(root);
    queueMicrotask(() => guard(() => settingsAccount(root)));
  } else if (section === "assistant") {
    const root = element("div");
    root.id = "assistant-connections-body";
    form.append(root);
    queueMicrotask(() => guard(loadSettingsAssistant));
  } else if (["library", "downloads", "paths"].includes(section)) {
    storageSection(form, section);
  }
  $("settings-body").replaceChildren(form);
}
async function applyEnvironment(value) {
  const changed = environment.client_id !== value.client_id;
  const activated = !environment.active && value.active;
  if (changed || (environment.active && !value.active)) {
    clearAgentToken();
    clearFileAccess();
    document.querySelectorAll("dialog").forEach((dialog) => dialog.close());
  }
  const translated = language !== (value.language || "en");
  const previousSection = section;
  const previousTab = connectionTab;
  const missing = !snapshot;
  // Clients, Indexers and Companion are tabs of Connections now: an older location lands there.
  const wanted = connectionTabOf(value.section) ? "connections" : value.section;
  if (value.section && value.section !== environment.section) {
    if (connectionTabOf(value.section) && !value.member) connectionTab = connectionTabOf(value.section);
    if (Object.hasOwn(sections(), wanted)) section = wanted;
  }
  environment = value;
  if (!Object.hasOwn(sections(), section))
    section = Object.hasOwn(sections(), wanted) ? wanted : Object.keys(sections())[0];
  language = value.language || "en";
  document.documentElement.lang = language;
  document.documentElement.dataset.theme = value.theme || "dark";
  if (!request) return;
  if (!snapshot && loadingClient === environment.client_id) return;
  if (changed || !snapshot || activated) {
    fileAccessValues.delete(environment.client_id);
    for (const group of ["connections", "general", "matching", "zen", "release_score"]) {
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
    section !== previousSection ||
    connectionTab !== previousTab
  )
    render();
  if (translated) fileAccessEditor?.redraw();
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
  hideRevealedSecrets();
  document.querySelectorAll("dialog").forEach((dialog) => dialog.close());
});
window.addEventListener("DOMContentLoaded", async () => {
  const transport = await TLPanel.connect("settings", { asynchronous: true });
  request = (action, body = {}) =>
    transport(action, { ...body, _client: environment.client_id });
  toastLines();
  window.settingsReady();
});
