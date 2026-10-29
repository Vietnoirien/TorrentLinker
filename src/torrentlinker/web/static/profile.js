"use strict";

let profileState = null;
let profileLoading = false;
const profileNumber = (v) =>
  typeof v === "number"
    ? v.toLocaleString(undefined, { maximumFractionDigits: 1 })
    : "—";
const profileBytes = (v) => (typeof v === "number" ? bytes(v) : "—");
const profileTime = (v) => (v ? new Date(v * 1000).toLocaleString() : "—");
const profileClass = (v) => (v || "—").replaceAll("_", " ");

function profileCard(title, value, note) {
  const card = element("div", undefined, "card");
  card.append(
    element("p", title, "muted"),
    element("strong", value, "profile-value"),
    element("p", note, "muted"),
  );
  return card;
}
function showZenProfile(data) {
  profileState = data;
  const p = data.api || {};
  $("zen-profile-tab").textContent = say("Profile", "Profil");
  $("profile-heading").textContent = say(
    "Your c411 profile",
    "Votre profil c411",
  );
  $("profile-refresh").textContent = say(
    "Refresh profile",
    "Actualiser le profil",
  );
  const errors = {
    "no-key": say(
      "Add an API key with profile:read access in Settings → Indexer.",
      "Ajoutez une clé API avec le droit profile:read dans Paramètres → Indexeur.",
    ),
    unauthorized: say(
      "API key refused. Check Settings → Indexer and refresh.",
      "Clé API refusée. Vérifiez Paramètres → Indexeur puis actualisez.",
    ),
    "missing-scope": say(
      "The API key needs profile:read access.",
      "La clé API nécessite le droit profile:read.",
    ),
    "rate-limited": say(
      "The tracker asked us to wait. Try refreshing later.",
      "Le tracker demande de patienter. Réessayez plus tard.",
    ),
    failed: say(
      "Profile unavailable. Check your connection and refresh.",
      "Profil indisponible. Vérifiez la connexion puis actualisez.",
    ),
  };
  $("profile-notice").textContent =
    errors[data.error] ||
    (data.api_stale
      ? say(
          "Waiting for an API update. Retrying automatically.",
          "En attente des données API. Nouvelle tentative automatique.",
        )
      : say(
          "Account information from the c411 API. Updates automatically every two minutes.",
          "Informations du compte issues de l’API c411. Mise à jour automatique toutes les deux minutes.",
        ));
  $("profile-identity").replaceChildren(
    element(
      "h2",
      p.username ||
        say("Connect your c411 account", "Connectez votre compte c411"),
    ),
    element(
      "p",
      `${say("Account", "Compte")} ${p.account_id || "—"} · ${say("Member since", "Membre depuis")} ${(p.member_since || "—").slice(0, 10)} · ${say("API updated", "API actualisée")} ${profileTime(data.api_updated_at)}`,
      "muted",
    ),
  );
  $("profile-stats").replaceChildren(
    profileCard(
      say("Zen balance", "Solde Zen"),
      `${profileNumber(p.balance)} Zen`,
      `${say("Earned", "Gagnés")} ${profileNumber(p.total_earned)} · ${say("Spent", "Dépensés")} ${profileNumber(p.total_spent)}`,
    ),
    profileCard(
      say("Class & level", "Classe et niveau"),
      profileClass(p.class_slug),
      `${say("Level", "Niveau")} ${profileNumber(p.level)} · ${say("Tree bonus", "Bonus d’arbre")} ${profileNumber(typeof p.tree_bonus === "number" ? p.tree_bonus * 100 : null)}%`,
    ),
    profileCard(
      say("Download access", "Accès au téléchargement"),
      !data.api
        ? "—"
        : p.download_allowed
          ? say("Allowed", "Autorisé")
          : say("Blocked", "Bloqué"),
      p.blocked_reason ||
        (p.freeleech
          ? say("Freeleech active", "Freeleech actif")
          : say(
              "Standard download rules",
              "Règles de téléchargement standard",
            )),
    ),
  );
  const progress = $("profile-progression");
  progress.replaceChildren(
    element("h3", say("Progression", "Progression")),
    element(
      "p",
      `${profileNumber(p.xp_into_level)} ${say("XP in this level", "XP dans ce niveau")} · ${profileNumber(p.xp_to_next_level)} ${say("XP to next level", "XP avant le prochain niveau")}`,
    ),
  );
  if (
    typeof p.xp_into_level === "number" &&
    typeof p.xp_to_next_level === "number"
  ) {
    const bar = element("progress");
    bar.max = p.xp_into_level + p.xp_to_next_level || 1;
    bar.value = p.xp_into_level;
    bar.setAttribute(
      "aria-label",
      say("Level progress", "Progression du niveau"),
    );
    progress.append(bar);
  }
  progress.append(
    element(
      "p",
      `${say("Quests", "Quêtes")} ${profileNumber(p.quests_completed)} / ${profileNumber(p.quests_total)} · ${say("Stars", "Étoiles")} ${profileNumber(p.stars)} · ${p.grade || "—"}`,
    ),
  );
  for (const [key, label] of [
    ["seed", say("Seeding", "Seed")],
    ["upload", say("Uploading", "Upload")],
    ["specialization", say("Specialization", "Spécialisation")],
    ["competitivity", say("Competitiveness", "Compétitivité")],
  ]) {
    const quest = p.quests?.[key] || {};
    const row = element("div", undefined, "profile-row");
    row.append(
      element("span", label),
      element(
        "strong",
        `${profileNumber(quest.questsCompleted)} / ${profileNumber(quest.questsTotal)}`,
      ),
    );
    progress.append(row);
  }
  const transfers = $("profile-transfers");
  transfers.replaceChildren(
    element("h3", say("Transfers · API", "Transferts · API")),
  );
  const table = element("table"),
    head = element("thead"),
    row = element("tr"),
    body = element("tbody");
  for (const title of [
    "",
    say("Uploaded", "Envoyé"),
    say("Downloaded", "Téléchargé"),
  ])
    row.append(element("th", title));
  head.append(row);
  for (const [key, label] of [
    ["actual", say("Actual", "Réel")],
    ["credit", say("Credit", "Crédit")],
    ["total", say("Total", "Total")],
  ]) {
    const row = element("tr");
    for (const value of [
      label,
      profileBytes(p[`uploaded_${key}`]),
      profileBytes(p[`downloaded_${key}`]),
    ])
      row.append(element("td", value));
    body.append(row);
  }
  table.append(head, body);
  transfers.append(table);
  $("profile-advanced-heading").textContent = say(
    "Advanced activity · Browser companion",
    "Activité détaillée · Extension navigateur",
  );
  const advanced = $("profile-advanced"),
    snapshot = data.companion;
  advanced.replaceChildren();
  if (snapshot) {
    advanced.append(
      element(
        "p",
        `${data.stale ? say("Waiting for a browser update", "En attente du navigateur") : say("Automatic sync connected", "Synchronisation automatique connectée")} · ${say("c411 browser · Last sync", "Navigateur c411 · Dernière synchronisation")} ${profileTime(data.received_at)}`,
      ),
    );
    const details = snapshot.details || {},
      cards = element("div", undefined, "profile-grid");
    cards.append(
      profileCard(
        say("Active seeds", "Seeds actifs"),
        profileNumber(snapshot.activeSeeds?.total),
        say("Reported by c411", "Indiqués par c411"),
      ),
      profileCard(
        say("Validated uploads", "Uploads validés"),
        profileNumber(details.validatedUploadsCount),
        say("At last sync", "À la dernière synchronisation"),
      ),
      profileCard(
        say("Total seed time", "Durée totale de seed"),
        `${profileNumber(typeof details.totalSeedingTimeSec === "number" ? details.totalSeedingTimeSec / 86400 : null)} ${say("days", "jours")}`,
        say("Combined across torrents", "Cumulée sur tous les torrents"),
      ),
    );
    advanced.append(
      cards,
      element(
        "p",
        `${say("Actual upload", "Envoi réel")} ${profileBytes(details.actualUploaded)} · ${say("Actual download", "Téléchargement réel")} ${profileBytes(details.actualDownloaded)}`,
      ),
      element(
        "p",
        `${say("Credited upload", "Envoi crédité")} ${profileBytes(details.creditedUploaded)} · ${say("Credited download", "Téléchargement crédité")} ${profileBytes(details.creditedDownloaded)}`,
      ),
    );
  } else {
    advanced.append(
      element(
        "p",
        data.paired
          ? say(
              "Connected. Waiting for the first automatic browser update.",
              "Connecté. En attente de la première mise à jour automatique du navigateur.",
            )
          : say(
              "Connect the companion to see advanced activity.",
              "Connectez l’extension pour afficher l’activité détaillée.",
            ),
      ),
      element(
        "p",
        say(
          "Active seeds, validated uploads and total seed time require a browser snapshot.",
          "Les seeds actifs, uploads validés et la durée de seed nécessitent un aperçu du navigateur.",
        ),
      ),
    );
  }
  $("profile-privacy").textContent = say(
    "Connect and manage the companion in Settings → Companion. Your login stays in the browser.",
    "Connectez et gérez l’extension dans Réglages → Extension. Votre session reste dans le navigateur.",
  );
  $("companion-heading").textContent = say(
    "Browser companion",
    "Extension navigateur",
  );
  $("companion-privacy").textContent = say(
    "Connect once to automatically sync account statistics, transfer totals, seed time and active seed count every two minutes. Your login stays in the browser. Keep a signed-in c411 tab open.",
    "Connectez une fois pour synchroniser automatiquement les statistiques du compte, les transferts, la durée et le nombre de seeds toutes les deux minutes. Votre session reste dans le navigateur. Gardez un onglet c411 connecté ouvert.",
  );
  const downloads = data.downloads || {};
  $("companion-status").textContent = !data.paired
    ? say("Not connected.", "Non connecté.")
    : downloads.blocked
      ? say(
          "c411 refused the session. Check the account and reconnect.",
          "c411 a refusé la session. Vérifiez le compte et reconnectez.",
        )
      : downloads.retry_after
        ? `${say("c411 asked us to wait", "c411 demande d’attendre")} ${downloads.retry_after} s`
        : downloads.available
          ? say("Connected. The browser tab is ready.", "Connecté. L’onglet du navigateur est prêt.")
          : say(
              "Connected. Keep a signed-in c411 tab open.",
              "Connecté. Gardez un onglet c411 connecté ouvert.",
            );
  $("session-downloads").disabled = !data.paired;
  $("session-downloads").checked = !!data.paired && !!downloads.enabled;
  $("session-downloads-label").textContent = say(
    "Download .torrent files with my c411 session",
    "Télécharger les .torrent avec ma session c411",
  );
  $("session-downloads-note").textContent = say(
    "Only while this is on and the companion is connected. If c411 refuses the session, downloads stop; they never fall back to the API key.",
    "Uniquement lorsque l’option est activée et l’extension connectée. Si c411 refuse la session, les téléchargements s’arrêtent ; ils ne basculent jamais sur la clé API.",
  );
  $("profile-extension").textContent = say(
    "Download extension",
    "Télécharger l’extension",
  );
  $("profile-pair").textContent = data.paired
    ? say("Connect another browser", "Connecter un autre navigateur")
    : say("Connect companion", "Connecter l’extension");
  $("profile-pair").disabled = !p.account_id || !!data.error;
  $("profile-disconnect").textContent = say(
    "Disconnect & clear",
    "Déconnecter et effacer",
  );
  $("profile-disconnect").disabled =
    !snapshot && !data.paired && $("profile-pairing").hidden;
  if (data.paired) {
    $("profile-pairing").hidden = true;
  }
}
async function loadZenProfile(initial = false) {
  if (profileLoading) return;
  const data = await api("zen/profile");
  showZenProfile(data);
  if (
    state.setup?.indexer_configured &&
    Date.now() / 1000 >= (data.refresh_after || 0)
  )
    await refreshZenProfile();
}
async function refreshZenProfile() {
  if (profileLoading) return;
  profileLoading = true;
  $("profile-refresh").disabled = true;
  try {
    showZenProfile(await api("zen/profile/refresh", {}));
  } finally {
    profileLoading = false;
    $("profile-refresh").disabled = false;
  }
}
$("profile-refresh").onclick = () => guard(refreshZenProfile);
$("profile-pair").onclick = () => {
  const tab = window.open("about:blank", "torrentlinker-companion");
  guard(async () => {
    try {
      // Revalidate the API account before granting the browser a write capability.
      await refreshZenProfile();
      const pairing = await api("zen/profile/pairing", {});
      const target = new URL(".", document.baseURI).href.replace(/\/$/, "");
      const payload = {
        target,
        code: pairing.code,
        accountId: profileState.api.account_id,
      };
      const url =
        target +
        "/companion/connect#" +
        encodeURIComponent(JSON.stringify(payload));
      if (tab) tab.location.href = url;
      else window.location.href = url;
      $("profile-instructions").textContent = say(
        "Connecting in your browser. Once the companion is installed, connection and updates are automatic. Remote WebUI: install the extension downloaded from this server and use HTTPS.",
        "Connexion dans votre navigateur. Une fois l’extension installée, la connexion et les mises à jour sont automatiques. WebUI distant : installez l’extension téléchargée depuis ce serveur et utilisez HTTPS.",
      );
      $("profile-pairing").hidden = false;
      $("profile-disconnect").disabled = false;
    } catch (error) {
      tab?.close();
      throw error;
    }
  });
};
$("profile-disconnect").onclick = () =>
  guard(async () => {
    const data = await api("zen/profile/disconnect", {});
    $("profile-pairing").hidden = true;
    showZenProfile(data);
  });
$("session-downloads").onchange = (event) =>
  guard(async () => {
    try {
      showZenProfile(
        await api("zen/profile/session-downloads", {
          enabled: event.target.checked,
        }),
      );
    } catch (error) {
      await loadZenProfile();
      throw error;
    }
  });
setInterval(() => {
  if (
    !document.hidden &&
    !$("workspace").hidden &&
    ((state.view === "zen" && !$("zen-profile-panel").hidden) ||
      (state.view === "setup" && state.settingsSection === "companion"))
  ) {
    loadZenProfile().catch(() => {});
  }
}, 5000);
showZenProfile({});
