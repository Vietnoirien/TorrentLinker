"use strict";
// The browser companion, per Tracker: Settings > Connections > Companion, and the one-line
// state on each Tracker's own tab. c411 pairs through its API profile; tr4ker pairs the account
// of a signed-in tr4ker tab (#179). Each Tracker's session answers only for itself.
const companionTrackers = () => {
  const found = ["c411"];
  if (draft("connections").trackers?.tr4ker?.enabled) found.push("tr4ker");
  return found;
};
const trackerCanPair = (tracker) => snapshot.tracker_registry?.[tracker]?.companion === true;
// tr4ker's pairing state as the same shape c411's has.
function tr4kerState(data) {
  const t = data.tr4ker || {};
  if (t.paired && t.available)
    return {
      kind: "on",
      tag: say("Paired", "Appairé"),
      line: say("Connected. The browser tab is ready.", "Connecté. L’onglet du navigateur est prêt."),
    };
  if (t.paired)
    return {
      kind: "warn",
      tag: say("Waiting for the tr4ker session", "En attente de la session tr4ker"),
      line: say(
        "Connected. Keep a signed-in tr4ker tab open.",
        "Connecté. Gardez un onglet tr4ker connecté ouvert.",
      ),
    };
  if (t.pending)
    return {
      kind: "warn",
      tag: say("Waiting for the tr4ker session", "En attente de la session tr4ker"),
      line: say(
        "Waiting for the tr4ker session… a signed-in tab is open in the browser.",
        "En attente de la session tr4ker… un onglet connecté est ouvert dans le navigateur.",
      ),
    };
  return { kind: "", tag: say("Not paired", "Non appairé"), line: say("Not connected.", "Non connecté.") };
}
const trackerPaired = (tracker, data) => (tracker === "tr4ker" ? Boolean(data.tr4ker?.paired) : Boolean(data.paired));
const trackerAccount = (tracker, data) =>
  tracker === "tr4ker" ? data.tr4ker?.account?.username : data.api?.username;
// What one paired Tracker's session is doing, from the companion state.
function companionState(data, tracker = "c411") {
  if (tracker === "tr4ker") return tr4kerState(data);
  const downloads = data.downloads || {};
  if (!data.paired)
    return { kind: "", tag: say("Not paired", "Non appairé"), line: say("Not connected.", "Non connecté.") };
  if (downloads.blocked)
    return {
      kind: "bad",
      tag: say("Session c411 refused", "Session c411 refusée"),
      line: say(
        "c411 refused the session. Check the account and reconnect.",
        "c411 a refusé la session. Vérifiez le compte et reconnectez.",
      ),
    };
  if (downloads.retry_after)
    return {
      kind: "warn",
      tag: say("Waiting for the c411 session", "En attente de la session c411"),
      line: `${say("Retry after", "Réessayer après")} ${downloads.retry_after} s`,
    };
  if (downloads.available)
    return {
      kind: "on",
      tag: say("Paired", "Appairé"),
      line: say("Connected. The browser tab is ready.", "Connecté. L’onglet du navigateur est prêt."),
    };
  return {
    kind: "warn",
    tag: say("Waiting for the c411 session", "En attente de la session c411"),
    line: say(
      "Connected. Keep a signed-in c411 tab open.",
      "Connecté. Gardez un onglet c411 connecté ouvert.",
    ),
  };
}
const companionBadge = (tracker, data) =>
  trackerCanPair(tracker)
    ? element("span", companionState(data, tracker).tag, `conn-tag ${companionState(data, tracker).kind}`.trim())
    : element("span", say("Unavailable", "Indisponible"), "conn-tag bad");
// A Tracker tab's one-line companion state, with a way to the Companion tab.
async function companionLine(card, tracker) {
  const client = environment.client_id;
  const data = trackerCanPair(tracker) ? await request("companion", { action: "state" }) : {};
  if (!card.isConnected || client !== environment.client_id) return;
  const line = element("p");
  line.dataset.paired = String(trackerPaired(tracker, data));
  line.append(`${say("Browser companion", "Compagnon du navigateur")} : `, companionBadge(tracker, data), " ");
  if (trackerPaired(tracker, data) && trackerAccount(tracker, data))
    line.append(`${say("account", "compte")} `, element("b", trackerAccount(tracker, data)), " · ");
  const open = element("button", say("Manage in the Companion tab", "Gérer dans l’onglet Compagnon"), "conn-link");
  open.type = "button";
  open.onclick = () => {
    connectionTab = "companion";
    render();
  };
  line.append(open);
  card.querySelector("h3").after(line);
  card.dispatchEvent(new CustomEvent("companion-state", { bubbles: true, detail: { paired: trackerPaired(tracker, data) } }));
}
function companionRow(root, tracker, data) {
  const row = element("div", undefined, "conn-row");
  row.dataset.tracker = tracker;
  const who = element("div", undefined, "who");
  const title = element("b", tracker);
  const state = trackerCanPair(tracker) ? companionState(data, tracker) : null;
  const text = element("p", undefined, "muted");
  if (state) {
    if (trackerPaired(tracker, data) && trackerAccount(tracker, data))
      text.append(`${say("Account", "Compte")} `, element("b", trackerAccount(tracker, data)), " · ");
    text.append(state.line);
  } else text.append(element("span", say("Unavailable", "Indisponible"), "unavailable"));
  who.append(title, " ", companionBadge(tracker, data), text);
  const actions = element("div", undefined, "settings-actions");
  if (state) {
    // c411 pairs through its API profile; tr4ker needs only a signed-in tab.
    const unavailable = tracker === "c411" && (!data.api?.account_id || Boolean(data.error));
    const pair = (label) => {
      const node = button(label, async () => {
        await request("companion", { action: "pair", tracker });
        return say("Complete the connection in your browser.", "Terminez la connexion dans votre navigateur.");
      });
      node.disabled = unavailable;
      return node;
    };
    if (trackerPaired(tracker, data))
      actions.append(
        pair(say("Connect another browser", "Connecter un autre navigateur")),
        button(say("Unpair", "Dissocier"), async () => {
          await request("companion", { action: "disconnect", tracker });
          await loadSettingsCompanion(root);
        }),
      );
    else if (tracker === "tr4ker" && data.tr4ker?.pending)
      actions.append(
        button(say("Cancel pairing", "Annuler l’appairage"), async () => {
          await request("companion", { action: "cancel", tracker });
          await loadSettingsCompanion(root);
        }),
      );
    else actions.append(pair(say("Pair", "Appairer")));
  }
  row.append(who, actions);
  return row;
}
// Which companion last reached the app, and when: the proof a click or a reload did something.
function companionSeenText(seen) {
  if (!seen?.version) return "";
  const when = new Date(seen.at * 1000).toLocaleString(language === "fr" ? "fr-FR" : "en-GB");
  return say(
    `Companion in the browser: version ${seen.version} · last contact ${when}`,
    `Compagnon dans le navigateur : version ${seen.version} · dernier contact ${when}`,
  );
}
async function loadSettingsCompanion(root) {
  const client = environment.client_id;
  const data = await request("companion", { action: "state" });
  if (!root.isConnected || client !== environment.client_id) return;
  root.id = "companion-root";
  const downloads = data.downloads || {};
  const extension = element("section", undefined, "settings-card");
  extension.append(
    element("h3", say("Browser extension", "Extension navigateur")),
    element(
      "p",
      say(
        "Connect once to sync account statistics, transfers, seed time and active seeds every two minutes. Your login stays in the browser.",
        "Connectez une fois pour synchroniser les statistiques du compte, les transferts, la durée et les seeds actifs toutes les deux minutes. Votre session reste dans le navigateur.",
      ),
      "muted",
    ),
  );
  const actions = element("div", undefined, "settings-actions");
  const disconnect = button(say("Disconnect & clear", "Déconnecter et effacer"), async () => {
    await request("companion", { action: "disconnect" });
    await loadSettingsCompanion(root);
  });
  disconnect.disabled = !data.paired && !data.companion && !data.tr4ker?.paired;
  actions.append(
    button(say("Save extension…", "Enregistrer l’extension…"), () =>
      request("companion", { action: "extension" }),
    ),
    button(say("Refresh", "Actualiser"), async () => {
      const fresh = await loadSettingsCompanion(root);
      return companionSeenText(fresh?.companion_seen) || say("Refreshed", "Actualisé");
    }),
    disconnect,
  );
  extension.append(actions);
  const seen = data.companion_seen;
  extension.append(
    element(
      "p",
      companionSeenText(seen) ||
        say(
          "No companion has reached TorrentLinker from a browser yet.",
          "Aucun compagnon n’a encore contacté TorrentLinker depuis un navigateur.",
        ),
      "muted",
    ),
  );
  const folder = data.companion_folder;
  if (folder?.path)
    extension.append(
      element(
        "p",
        say(`Managed folder: ${folder.path}`, `Dossier géré : ${folder.path}`) +
          (folder.version ? ` · ${say("version", "version")} ${folder.version}` : "") +
          (folder.waiting ? ` · ${say("waiting for the server's HTTPS address (open this page over HTTPS or set TL_PUBLIC_URL)", "en attente de l’adresse HTTPS du serveur (ouvrez cette page en HTTPS ou définissez TL_PUBLIC_URL)")}` : "") +
          (folder.error ? ` · ${folder.error}` : ""),
        "muted",
      ),
      element(
        "p",
        say(
          "Load unpacked from this folder once; it updates itself afterwards.",
          "Chargez-la une fois non empaquetée depuis ce dossier ; elle se met ensuite à jour toute seule.",
        ),
        "muted",
      ),
    );
  const trackers = element("section", undefined, "settings-card");
  trackers.append(element("h3", "Trackers"));
  const all = element("div", undefined, "settings-actions");
  const pairAll = button(
    say("Connect all Trackers", "Connecter tous les trackers"),
    async () => {
      // Every Tracker the companion supports and not yet paired: one browser tab each.
      const todo = companionTrackers().filter((tracker) => !trackerPaired(tracker, data));
      if (!todo.length)
        return say("Every supported Tracker is already paired", "Tous les trackers pris en charge sont déjà appairés");
      await request("companion", { action: "pair", trackers: todo });
      return say(
        `Opening a signed-in tab for ${todo.join(" and ")}…`,
        `Ouverture d’un onglet connecté pour ${todo.join(" et ")}…`,
      );
    },
    "primary bigbtn",
  );
  // c411 needs its API profile to pair; tr4ker does not.
  pairAll.disabled = companionTrackers().every(
    (tracker) => trackerPaired(tracker, data) || (tracker === "c411" && (!data.api?.account_id || Boolean(data.error))),
  );
  all.append(pairAll);
  trackers.append(
    all,
    element(
      "p",
      say(
        "Opens a tab in the browser and pairs each signed-in session. Each Tracker can also be paired or unpaired on its own.",
        "Ouvre un onglet dans le navigateur et appaire chaque session connectée. Chaque tracker peut aussi s’appairer ou se dissocier seul.",
      ),
      "muted",
    ),
    ...companionTrackers().map((tracker) => companionRow(root, tracker, data)),
  );
  if (!companionTrackers().includes("tr4ker"))
    trackers.append(
      element(
        "p",
        say(
          "tr4ker appears here once it is turned on in its tab.",
          "tr4ker apparaît ici dès qu’il est activé dans son onglet.",
        ),
        "muted",
      ),
    );
  const label = element("label", undefined, "settings-field settings-check"),
    toggle = element("input");
  toggle.type = "checkbox";
  toggle.checked = Boolean(data.paired && downloads.enabled);
  toggle.disabled = !data.paired;
  toggle.onchange = () =>
    guard(async () => {
      toggle.disabled = true;
      try {
        await request("companion", {
          action: "downloads",
          enabled: toggle.checked,
        });
      } finally {
        await loadSettingsCompanion(root);
      }
    });
  label.append(
    toggle,
    element(
      "span",
      say(
        "Download .torrent files with my c411 session",
        "Télécharger les .torrent avec ma session c411",
      ),
    ),
  );
  const session = element("section", undefined, "settings-card");
  session.append(
    element("h3", say("c411 downloads", "Téléchargements c411")),
    label,
    element(
      "p",
      say(
        "Only while enabled and connected. If c411 refuses the session, downloads stop; they never fall back to the API key.",
        "Uniquement lorsque l’option est activée et l’extension connectée. Si c411 refuse la session, les téléchargements s’arrêtent sans basculer sur la clé API.",
      ),
      "muted",
    ),
  );
  root.replaceChildren(extension, trackers, session);
  return data;
}

let companionPolling = false;
function pollSettingsCompanion() {
  const root = $("companion-root");
  if (
    companionPolling ||
    document.hidden ||
    !environment.active ||
    section !== "connections" ||
    connectionTab !== "companion" ||
    !root ||
    (root.contains(document.activeElement) &&
      document.activeElement.matches("input, textarea, select"))
  )
    return;
  companionPolling = true;
  guard(() => loadSettingsCompanion(root)).finally(() => {
    companionPolling = false;
  });
}
setInterval(pollSettingsCompanion, 5000);
document.addEventListener("visibilitychange", pollSettingsCompanion);
