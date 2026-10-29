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
          "API snapshot is older than five minutes. Refresh for current values.",
          "Les données API ont plus de cinq minutes. Actualisez pour les mettre à jour.",
        )
      : say(
          "Account information from the c411 API.",
          "Informations du compte issues de l’API c411.",
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
        `${data.stale ? say("Stale snapshot", "Données anciennes") : say("Snapshot received", "Données reçues")} · ${say("c411 browser · Last sync", "Navigateur c411 · Dernière synchronisation")} ${profileTime(data.received_at)}`,
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
              "Paired. Send a preview from the extension.",
              "Associé. Envoyez un aperçu depuis l’extension.",
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
    "Your browser login stays in the browser. Preview and send only the fields you choose.",
    "Votre session reste dans le navigateur. Prévisualisez et envoyez uniquement les champs choisis.",
  );
  $("profile-extension").textContent = say(
    "Download extension",
    "Télécharger l’extension",
  );
  $("profile-pair").textContent = data.paired
    ? say("Pair again", "Associer à nouveau")
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
    $("profile-code").value = "";
  }
}
async function loadZenProfile(initial = false) {
  if (profileLoading) return;
  const data = await api("zen/profile");
  showZenProfile(data);
  if (initial && !data.api && state.setup?.indexer_configured)
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
$("profile-pair").onclick = () =>
  guard(async () => {
    // Revalidate the API account before granting the browser a write capability.
    await refreshZenProfile();
    const pairing = await api("zen/profile/pairing", {});
    $("profile-address").value = new URL(".", document.baseURI).href.replace(
      /\/$/,
      "",
    );
    $("profile-code").value = pairing.code;
    $("profile-address-label").textContent = say(
      "Receiver address",
      "Adresse de réception",
    );
    $("profile-code-label").textContent = say(
      "Pairing code",
      "Code d’association",
    );
    $("profile-instructions").textContent = say(
      "Extract the extension ZIP and load its folder in your browser’s Extensions page with Developer mode enabled. Open c411 and click the extension. Read a preview, enter this address and code, pair, then send. The code expires in 10 minutes; the connection lasts one hour. Remote WebUI connections require HTTPS.",
      "Extrayez le ZIP et chargez son dossier dans la page Extensions du navigateur en mode développeur. Ouvrez c411 et cliquez sur l’extension. Lisez un aperçu, saisissez l’adresse et le code, associez puis envoyez. Le code expire après 10 minutes ; la connexion dure une heure. Le WebUI distant nécessite HTTPS.",
    );
    $("profile-pairing").hidden = false;
    $("profile-disconnect").disabled = false;
    $("profile-code").focus();
    $("profile-code").select();
  });
$("profile-disconnect").onclick = () =>
  guard(async () => {
    const data = await api("zen/profile/disconnect", {});
    $("profile-pairing").hidden = true;
    $("profile-code").value = "";
    showZenProfile(data);
  });
setInterval(() => {
  if (
    !document.hidden &&
    !$("workspace").hidden &&
    state.view === "zen" &&
    !$("zen-profile-panel").hidden
  ) {
    loadZenProfile().catch(() => {});
  }
}, 5000);
showZenProfile({});
