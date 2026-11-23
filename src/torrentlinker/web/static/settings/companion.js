"use strict";
// The browser companion, per Tracker: Settings > Connections > Companion, and the one-line
// state on each Tracker's own tab. Only c411 can be paired so far (the companion extension
// has no tr4ker support yet, #179): tr4ker shows as unavailable, never as a fake pairing.
const companionTrackers = () => {
  const found = ["c411"];
  if (draft("connections").trackers?.tr4ker?.enabled) found.push("tr4ker");
  return found;
};
const trackerCanPair = (tracker) => snapshot.tracker_registry?.[tracker]?.companion === true;
const tr4kerSoon = () => say("soon: tr4ker companion (#179)", "bientôt : compagnon tr4ker (#179)");
// What one paired Tracker's session is doing, from the companion state.
function companionState(data) {
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
    ? element("span", companionState(data).tag, `conn-tag ${companionState(data).kind}`.trim())
    : element("span", say("Unavailable", "Indisponible"), "conn-tag bad");
// A Tracker tab's one-line companion state, with a way to the Companion tab.
async function companionLine(card, tracker) {
  const client = environment.client_id;
  const data = trackerCanPair(tracker) ? await request("companion", { action: "state" }) : {};
  if (!card.isConnected || client !== environment.client_id) return;
  const line = element("p");
  line.append(`${say("Browser companion", "Compagnon du navigateur")} : `, companionBadge(tracker, data), " ");
  if (!trackerCanPair(tracker)) line.append(element("span", tr4kerSoon(), "unavailable"), " ");
  else if (data.paired && data.api?.username)
    line.append(`${say("account", "compte")} `, element("b", data.api.username), " · ");
  const open = element("button", say("Manage in the Companion tab", "Gérer dans l’onglet Compagnon"), "conn-link");
  open.type = "button";
  open.onclick = () => {
    connectionTab = "companion";
    render();
  };
  line.append(open);
  card.querySelector("h3").after(line);
}
function companionRow(root, tracker, data) {
  const row = element("div", undefined, "conn-row");
  row.dataset.tracker = tracker;
  const who = element("div", undefined, "who");
  const title = element("b", tracker);
  const state = trackerCanPair(tracker) ? companionState(data) : null;
  const text = element("p", undefined, "muted");
  if (state) {
    if (data.paired && data.api?.username)
      text.append(`${say("Account", "Compte")} `, element("b", data.api.username), " · ");
    text.append(state.line);
  } else text.append(element("span", tr4kerSoon(), "unavailable"));
  who.append(title, " ", companionBadge(tracker, data), text);
  const actions = element("div", undefined, "settings-actions");
  if (state) {
    const unavailable = !data.api?.account_id || Boolean(data.error);
    const pair = (label) => {
      const node = button(label, async () => {
        await request("companion", { action: "pair" });
        return say("Complete the connection in your browser.", "Terminez la connexion dans votre navigateur.");
      });
      node.disabled = unavailable;
      return node;
    };
    if (data.paired)
      actions.append(
        pair(say("Connect another browser", "Connecter un autre navigateur")),
        button(say("Unpair", "Dissocier"), async () => {
          await request("companion", { action: "disconnect" });
          await loadSettingsCompanion(root);
        }),
      );
    else actions.append(pair(say("Pair", "Appairer")));
  }
  row.append(who, actions);
  return row;
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
  disconnect.disabled = !data.paired && !data.companion;
  actions.append(
    button(say("Save extension…", "Enregistrer l’extension…"), () =>
      request("companion", { action: "extension" }),
    ),
    button(say("Refresh", "Actualiser"), () => loadSettingsCompanion(root)),
    disconnect,
  );
  extension.append(actions);
  const trackers = element("section", undefined, "settings-card");
  trackers.append(element("h3", "Trackers"));
  const all = element("div", undefined, "settings-actions");
  const pairAll = button(
    say("Connect all Trackers", "Connecter tous les trackers"),
    async () => {
      // Every Tracker the companion supports and not yet paired; tr4ker is not one yet.
      if (data.paired)
        return say("Every supported Tracker is already paired", "Tous les trackers pris en charge sont déjà appairés");
      await request("companion", { action: "pair" });
      return say("Complete the connection in your browser.", "Terminez la connexion dans votre navigateur.");
    },
    "primary bigbtn",
  );
  pairAll.disabled = !data.api?.account_id || Boolean(data.error);
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
