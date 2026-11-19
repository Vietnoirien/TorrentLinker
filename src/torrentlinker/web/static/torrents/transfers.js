"use strict";
let transferOptions = null,
  transferDraft = null,
  transferPlan = null,
  transferTimer = null;
const transferStatus = {
  review: ["À vérifier", "Review"],
  running: ["En cours", "Running"],
  complete: ["Terminé", "Complete"],
  attention: ["À examiner", "Needs attention"],
  ready: ["Prêt", "Ready"],
  blocked: ["Bloqué", "Blocked"],
  copying: ["Envoi vers la destination", "Sending to destination"],
  verifying: ["Vérification du contenu", "Checking file hashes"],
  adding: ["Ajout en pause", "Adding paused"],
  seeding: ["Confirmation du seed", "Confirming seeding"],
  confirmed: ["En partage sur la destination", "Seeding at destination"],
  failed: ["Échec · source conservée", "Failed · source retained"],
  interrupted: ["Interrompu · reprise possible", "Interrupted · can resume"],
};
const transferLabel = (s) => (transferStatus[s] ? t(...transferStatus[s]) : s);
function transferClose() {
  clearTimeout(transferTimer);
  $("dialog").close();
  $("dialog").classList.remove("transfer-dialog");
}
async function openTransfer() {
  const items = [...selected]
    .map((k) => rowCache.get(k))
    .filter(Boolean)
    .map((r) => ({ client_id: r.raw.client_id, hash: r.raw.hash }));
  transferOptions = await request("transfer-options", { items });
  transferDraft = {
    destination:
      transferOptions.clients.find(
        (c) => !items.some((i) => i.client_id === c.id),
      )?.id || "",
    overrides: {},
    remove_torrent: false,
    remove_files: false,
  };
  transferPlan = null;
  drawTransfer();
  if (!$("dialog").open) $("dialog").showModal();
}
function transferFolders() {
  const c = transferOptions.clients.find(
    (c) => c.id === transferDraft.destination,
  );
  return {
    ...(c?.folders || {}),
    ...(transferDraft.overrides[transferDraft.destination] || {}),
  };
}
function transferShared() {
  const folders = transferFolders();
  return (
    !remoteClients().some((c) => c.access?.configured) &&
    transferOptions.sources.length &&
    transferOptions.sources.every((r) => folders[r.category] === r.source)
  );
}
function transferCapture() {
  if (!$("transfer-destination")) return;
  const paths = {};
  $("dialog")
    .querySelectorAll("[data-transfer-folder]")
    .forEach((i) => (paths[i.dataset.transferFolder] = i.value));
  transferDraft.overrides[transferDraft.destination] = paths;
  transferDraft.remove_torrent = $("cleanup-torrent").checked;
  transferDraft.remove_files = $("cleanup-files").checked;
}
function drawTransfer() {
  const d = $("dialog"),
    editing = !transferPlan;
  d.classList.add("transfer-dialog");
  d.onclose = () => {
    clearTimeout(transferTimer);
    d.classList.remove("transfer-dialog");
  };
  const stage = editing ? 0 : transferPlan.status === "review" ? 1 : 2;
  d.innerHTML = `<div class="transfer-heading"><h2>${t("Transférer vers un autre client", "Transfer to another client")}</h2><button id="transfer-close" aria-label="${t("Fermer", "Close")}">×</button></div><p class="muted">${t("Préparer une destination, vérifier chaque torrent, puis décider du nettoyage à la source.", "Prepare a destination, verify each torrent, then confirm source cleanup.")}</p><div class="transfer-steps">${[
    ["Préparer", "Prepare"],
    ["Vérifier le plan", "Check the plan"],
    ["Transférer et suivre", "Transfer and follow up"],
  ]
    .map(
      (label, i) =>
        `<span class="badge ${i === stage ? "active-step" : ""}">${i + 1} · ${t(...label)}</span>`,
    )
    .join("")}</div><div id="transfer-content"></div>`;
  $("transfer-close").onclick = transferClose;
  if (editing) drawTransferSetup();
  else drawTransferProgress();
  drawRemoteAccess();
}
function drawTransferSetup() {
  const folders = transferFolders(),
    shared = transferShared();
  if (shared) transferDraft.remove_files = false;
  $("transfer-content").innerHTML =
    `<div class="transfer-grid"><section class="panel transfer-card"><h3>${t("Destination", "Destination")}</h3><label>${t("Client", "Client")}<select id="transfer-destination">${!transferDraft.destination ? `<option value="">${t("Aucun autre client disponible", "No other client available")}</option>` : ""}${transferOptions.clients.map((c) => `<option value="${escape(c.id)}" ${c.id === transferDraft.destination ? "selected" : ""} ${transferOptions.sources.some((r) => r.client_id === c.id) ? "disabled" : ""}>${escape(c.name)}${transferOptions.sources.some((r) => r.client_id === c.id) ? " · source" : ""}</option>`).join("")}</select></label><label>${t("Accès aux fichiers", "File access")}<select id="transfer-method"><option value="copy" ${shared ? "disabled" : "selected"}>${t("Copier vers la destination", "Copy to destination")}</option><option value="shared" ${shared ? "selected" : "disabled"}>${t("Réutiliser un dossier partagé", "Reuse a shared folder")}</option></select></label><p>${shared ? t("Réutilisation proposée · même dossier", "Proposed reuse · same folder") : t("Copie vers les dossiers de destination", "Copy to destination folders")}</p><p class="muted">${t("Le plan vérifiera le stockage réel et les accès. Configurez un accès SFTP pour un stockage non monté.", "The plan checks actual storage and access. Configure SFTP access for storage which is not mounted.")}</p><h4>${t("Dossiers par catégorie", "Category folders")}</h4>${Object.keys(
      folders,
    )
      .map(
        (category) =>
          `<div class="transfer-category"><strong>${escape(category || t("Sans catégorie", "No category"))}</strong><label>${t("Destination pour ce transfert", "Destination for this transfer")}<div class="transfer-path"><input data-transfer-folder="${escape(category)}" value="${escape(folders[category])}"><button data-transfer-browse="${escape(category)}">${t("Parcourir…", "Browse…")}</button></div></label><button data-transfer-default="${escape(category)}">${t("Rétablir le dossier configuré", "Restore configured folder")}</button></div>`,
      )
      .join(
        "",
      )}<p class="muted">${t("Les réglages de catégorie restent inchangés.", "Category settings stay unchanged.")}</p></section><section class="panel transfer-card"><h3>${t("À la source, après le transfert", "At the source, after transfer")}</h3><div class="cleanup-toggles"><label><input id="cleanup-torrent" type="checkbox" role="switch" ${transferDraft.remove_torrent ? "checked" : ""}>${t("Retirer le torrent", "Remove torrent")}</label><label><input id="cleanup-files" type="checkbox" role="switch" ${transferDraft.remove_files ? "checked" : ""} ${shared ? "disabled" : ""}>${t("Supprimer les fichiers", "Delete files")}</label></div><p>${shared ? t("Les fichiers partagés restent utilisés par la destination.", "The destination still uses shared files.") : t("La source reste intacte jusqu’à la copie vérifiée et au seed confirmé. Supprimer seulement les fichiers conserve le torrent source en pause.", "The source stays intact until the copy is verified and destination seeding confirmed. Deleting only files keeps the source torrent paused.")}</p><p class="note">${t("Le nettoyage exige une confirmation distincte après réussite.", "Cleanup requires separate confirmation after success.")}</p><p>${transferOptions.sources.length} torrents · ${formatBytes(transferOptions.sources.reduce((n, r) => n + r.total, 0))}</p></section></div><div class="transfer-footer"><button id="transfer-check" class="primary" ${!transferDraft.destination ? "disabled" : ""}>${t("Vérifier le plan", "Check the plan")}</button></div>`;
  $("transfer-destination").onchange = (e) => {
    transferCapture();
    transferDraft.destination = e.target.value;
    drawTransfer();
  };
  $("cleanup-torrent").onchange = transferCapture;
  $("cleanup-files").onchange = transferCapture;
  $("dialog")
    .querySelectorAll("[data-transfer-folder]")
    .forEach(
      (i) =>
        (i.onchange = () => {
          transferCapture();
          drawTransfer();
        }),
    );
  $("dialog")
    .querySelectorAll("[data-transfer-default]")
    .forEach(
      (b) =>
        (b.onclick = () => {
          transferCapture();
          delete transferDraft.overrides[transferDraft.destination][
            b.dataset.transferDefault
          ];
          drawTransfer();
        }),
    );
  $("dialog")
    .querySelectorAll("[data-transfer-browse]")
    .forEach(
      (b) =>
        (b.onclick = () =>
          transferGuard(() => transferBrowse(b.dataset.transferBrowse))),
    );
  $("transfer-check").onclick = () =>
    transferGuard(async () => {
      transferCapture();
      const folders = transferFolders();
      $("transfer-check").disabled = true;
      try {
        transferPlan = await request("transfer-prepare", {
          destination: transferDraft.destination,
          remove_torrent: transferDraft.remove_torrent,
          remove_files: transferDraft.remove_files,
          items: transferOptions.sources.map((r) => ({
            client_id: r.client_id,
            hash: r.hash,
            folder: folders[r.category] || "",
          })),
        });
        drawTransfer();
      } finally {
        if ($("transfer-check")) $("transfer-check").disabled = false;
      }
    });
}
async function transferBrowse(category, path = "") {
  transferCapture();
  const remote = transferOptions.clients.find((c) => c.id === transferDraft.destination)?.access?.configured;
  const result = await request(remote ? "transfer-remote-browse" : "transfer-browse", { path, client_id: transferDraft.destination });
  if (result.selected !== undefined) {
    if (result.selected)
      transferDraft.overrides[transferDraft.destination][category] =
        result.selected;
    drawTransfer();
    return;
  }
  const d = $("dialog");
  d.innerHTML = `<h2>${t("Choisir un dossier", "Choose a folder")}</h2><p>${escape(result.path)}</p><div class="transfer-folders">${[result.parent, ...result.folders].map((p, i) => `<button data-folder-path="${escape(p)}">${i === 0 ? "↑ " : ""}${escape(p || t("Racines", "Roots"))}</button>`).join("")}</div><div class="transfer-footer"><button id="browse-cancel">${t("Annuler", "Cancel")}</button><button id="browse-select" class="primary" ${result.path ? "" : "disabled"}>${t("Choisir ce dossier", "Use this folder")}</button></div>`;
  d.querySelectorAll("[data-folder-path]").forEach(
    (b) =>
      (b.onclick = () =>
        transferGuard(() => transferBrowse(category, b.dataset.folderPath))),
  );
  $("browse-cancel").onclick = drawTransfer;
  $("browse-select").onclick = () => {
    transferDraft.overrides[transferDraft.destination] ||= {};
    transferDraft.overrides[transferDraft.destination][category] = result.path;
    drawTransfer();
  };
}
function drawTransferProgress() {
  const p = transferPlan,
    review = p.status === "review",
    blocked = p.rows.filter((r) => ["blocked", "failed"].includes(r.status));
  $("transfer-content").innerHTML =
    `<p class="note">${t("Destination", "Destination")} · ${escape(transferOptions?.clients.find((c) => c.id === p.destination)?.name || p.destination)}</p><p class="note">${t("Nettoyage prévu", "Planned cleanup")} · ${p.remove_torrent ? t("retirer le torrent", "remove torrent") : t("conserver le torrent", "keep torrent")} · ${p.remove_files ? t("supprimer les fichiers", "delete files") : t("conserver les fichiers", "keep files")}</p><div class="transfer-list">${p.rows.map((r) => `<article class="panel transfer-item ${["blocked", "failed"].includes(r.status) ? "transfer-blocked" : ""}"><div><strong>${escape(r.name || r.hash)}</strong><p class="muted">${escape(r.source || "")} → ${r.folder ? escape(r.folder) : `<strong class="missing-destination">⚠ ${t("Dossier manquant", "Missing folder")}</strong>`}</p><p>${r.cleanup_done ? t("Nettoyage confirmé terminé", "Confirmed cleanup completed") : t("Source conservée", "Source retained")}</p></div><div><span class="badge ${["blocked", "failed"].includes(r.status) ? "blocking-badge" : ""}">${["blocked", "failed"].includes(r.status) ? "⚠ " : ""}${transferLabel(r.status)}</span>${r.error ? `<p>${escape(transferError(r.error))}</p>` : ""}${review && r.status === "blocked" ? `<button data-fix="${r.index}">${t("Corriger la préparation…", "Fix preparation…")}</button>` : ""}${r.status === "confirmed" && !r.cleanup_done && (p.remove_torrent || p.remove_files) ? `<button data-cleanup="${r.index}">${t("Confirmer le nettoyage prévu…", "Confirm planned cleanup…")}</button>` : ""}</div>${(["copying", "verifying"].includes(r.status) || (["interrupted", "failed"].includes(r.status) && r.bytes > 0)) ? `<div class="transfer-progress"><div><strong>${transferLabel(r.status)}</strong><span>${Math.round(r.fraction * 100)}%</span></div><progress max="1" value="${r.fraction}"></progress><small>${formatBytes(r.bytes)} / ${formatBytes(r.total)}${r.speed ? ` · ${formatBytes(r.speed)}/s · ${Math.ceil((r.total - r.bytes) / r.speed)} s` : ""}</small></div>` : ""}<details><summary>${t("Historique de cet élément", "This item’s history")}</summary>${r.history.map((h) => `<p>${new Date(h.time * 1000).toLocaleTimeString()} · ${transferLabel(h.status)}</p>`).join("")}</details></article>`).join("")}</div>${review && !p.can_start ? `<p class="note transfer-blocking-summary">⚠ ${t("Démarrage bloqué. Corrigez tous les éléments signalés.", "Start blocked. Resolve all flagged items.")}</p>` : ""}<div class="transfer-footer">${review ? `<button id="transfer-edit">${t("Modifier", "Edit")}</button><button id="transfer-start" class="primary" ${p.can_start ? "" : "disabled"}>${t("Démarrer le transfert", "Start transfer")}</button>` : p.status === "running" ? `<button id="transfer-stop">${t("Interrompre", "Interrupt")}</button>` : p.status === "attention" ? `<button id="transfer-start">${t("Reprendre après correction", "Resume after correction")}</button>` : ""}</div>`;
  const edit = () => {
    transferPlan = null;
    drawTransfer();
  };
  if ($("transfer-edit")) $("transfer-edit").onclick = edit;
  $("dialog")
    .querySelectorAll("[data-fix]")
    .forEach((b) => (b.onclick = edit));
  if ($("transfer-start"))
    $("transfer-start").onclick = () =>
      transferGuard(async () => {
        transferPlan = await request("transfer-start", { id: p.id });
        drawTransfer();
        pollTransfer();
      });
  if ($("transfer-stop"))
    $("transfer-stop").onclick = () =>
      transferGuard(async () => {
        await request("transfer-stop", { id: p.id });
        pollTransfer();
      });
  $("dialog")
    .querySelectorAll("[data-cleanup]")
    .forEach(
      (b) =>
        (b.onclick = () =>
          transferGuard(() => confirmTransferCleanup(+b.dataset.cleanup))),
    );
}
async function pollTransfer() {
  clearTimeout(transferTimer);
  if (!$("dialog").open || !transferPlan) return;
  const scroll = $("dialog").scrollTop,
    opened = [...$("dialog").querySelectorAll(".transfer-item details")].map(
      (d) => d.open,
    );
  transferPlan = await request("transfer-get", { id: transferPlan.id });
  drawTransfer();
  $("dialog")
    .querySelectorAll(".transfer-item details")
    .forEach((d, i) => (d.open = !!opened[i]));
  $("dialog").scrollTop = scroll;
  if (transferPlan.status === "running")
    transferTimer = setTimeout(() => transferGuard(pollTransfer), 1000);
}
async function confirmTransferCleanup(index) {
  clearTimeout(transferTimer);
  const result = await request("transfer-review-cleanup", {
      id: transferPlan.id,
      index,
    }),
    r = result.row,
    d = $("dialog");
  const label = result.remove_files
    ? result.remove_torrent
      ? t(
          "Supprimer le torrent et ses fichiers source",
          "Delete source torrent and files",
        )
      : t(
          "Supprimer les fichiers et garder le torrent en pause",
          "Delete files and keep torrent paused",
        )
    : t("Retirer sans supprimer les fichiers", "Remove without deleting files");
  d.innerHTML = `<h2>${t("Confirmer le nettoyage à la source", "Confirm source cleanup")}</h2><p><strong>${escape(r.name)}</strong></p><p>${r.method === "shared" ? t("La destination utilise ces mêmes fichiers. Ils restent conservés.", "The destination uses these same files. They will be retained.") : t("La copie est vérifiée à destination.", "The destination copy is verified.")}</p><p>${escape(r.source)} → ${escape(r.folder)}</p>${result.remove_files ? `<p>${t("Les fichiers source seront supprimés définitivement.", "Source files will be permanently deleted.")}</p>` : ""}<button id="cleanup-cancel">${t("Conserver la source", "Keep the source")}</button><button id="cleanup-confirm" class="primary">${label}</button>`;
  $("cleanup-cancel").onclick = drawTransfer;
  $("cleanup-confirm").onclick = () =>
    transferGuard(async () => {
      transferPlan = await request("transfer-cleanup", {
        id: transferPlan.id,
        index,
        token: result.token,
      });
      drawTransfer();
    });
}
async function transferHistory() {
  const result = await request("transfer-list"),
    d = $("dialog");
  d.classList.add("transfer-dialog");
  d.innerHTML = `<h2>${t("Transferts entre clients", "Client transfers")}</h2>${result.plans.map((p) => `<p><button data-transfer-id="${p.id}">${p.rows.length} torrents · ${escape(p.destination)} · ${transferLabel(p.status)}</button></p>`).join("") || `<p>${t("Aucun transfert", "No transfers")}</p>`}<button id="history-close">${t("Fermer", "Close")}</button>`;
  d.showModal();
  $("history-close").onclick = transferClose;
  d.querySelectorAll("[data-transfer-id]").forEach(
    (b) =>
      (b.onclick = () =>
        transferGuard(async () => {
          transferPlan = await request("transfer-get", {
            id: b.dataset.transferId,
          });
          transferOptions =
            transferPlan.status === "review"
              ? await request("transfer-options", {
                  items: transferPlan.rows.map((r) => ({
                    client_id: r.client_id,
                    hash: r.hash,
                  })),
                })
              : { clients: snapshot.clients, sources: [] };
          transferDraft = {
            destination: transferPlan.destination,
            overrides: {
              [transferPlan.destination]: Object.fromEntries(
                transferOptions.sources.map((r, i) => [
                  r.category,
                  transferPlan.rows[i].folder,
                ]),
              ),
            },
            remove_torrent: transferPlan.remove_torrent,
            remove_files: transferPlan.remove_files,
          };
          drawTransfer();
          pollTransfer();
        })),
  );
}

const transferErrors = {
  "Check SFTP access before preparing the transfer": "Vérifiez l’accès SFTP avant de préparer le transfert",
  "SFTP operation timed out": "Le délai de connexion SFTP a expiré",
  "The mapped folder does not exist": "Le dossier correspondant n’existe pas",
  "The server does not report available space": "Le serveur ne fournit pas l’espace disponible",
  "SFTP symlink paths are not supported": "Les chemins SFTP contenant des liens symboliques ne sont pas pris en charge",
  "Use an absolute path without parent traversal": "Utilisez un chemin absolu sans remontée vers un dossier parent",
  "Enter file-access credentials": "Renseignez les identifiants d’accès aux fichiers",
  "Confirm the server identity before saving access": "Confirmez l’identité du serveur avant d’enregistrer l’accès",
  "Server identity is unavailable": "L’identité du serveur est indisponible",
  "Source content changed; cleanup refused": "Le contenu source a changé ; suppression refusée",
  "Source content changed during cleanup review": "Le contenu source a changé pendant la vérification",

  "Original .torrent metadata is unavailable; use a torrent already cached in TorrentLinker":
    "Le fichier .torrent d’origine est indisponible ; utilisez un torrent déjà mis en cache dans TorrentLinker",
  "Choose an existing accessible destination folder":
    "Choisissez un dossier de destination existant et accessible",
  "Remote storage needs a configured accessible path mapping":
    "Le stockage distant nécessite un chemin monté et configuré",
  "Destination file already exists; it will not be overwritten":
    "Le fichier de destination existe déjà ; il ne sera pas écrasé",
  "Destination folder is not writable":
    "Le dossier de destination ne permet pas l’écriture",
  "Shared source files cannot be deleted":
    "Les fichiers partagés ne peuvent pas être supprimés",
  "Insufficient destination space": "Espace insuffisant à destination",
  "Insufficient destination space for the entire batch":
    "Espace insuffisant pour l’ensemble du transfert",
  "The destination cannot be a source client":
    "La destination ne peut pas être un client source",
  "Torrent already exists at destination":
    "Le torrent existe déjà à destination",
  "Client settings changed; prepare a new transfer":
    "Les réglages du client ont changé ; préparez un nouveau transfert",
  "Source torrent is incomplete or being checked":
    "Le torrent source est incomplet ou en cours de vérification",
  "Protected Reseed files cannot be transferred":
    "Les fichiers protégés par la remise en seed ne peuvent pas être transférés",
  "Selected torrents have overlapping destination files":
    "Plusieurs torrents sélectionnés utilisent les mêmes fichiers de destination",
  "Source files changed; prepare a new plan":
    "Les fichiers source ont changé ; préparez un nouveau plan",
  "Transfer interrupted; source retained":
    "Transfert interrompu ; source conservée",
  "Destination content verification failed; source retained":
    "La vérification à destination a échoué ; source conservée",
  "Application stopped; resume after review":
    "Application arrêtée ; reprenez après vérification",
  "Destination torrent belongs to another operation":
    "Le torrent de destination appartient à une autre opération",
  "Destination copy changed outside this transfer":
    "La copie de destination a été modifiée hors de ce transfert",
  "Destination verification timed out; source retained":
    "La vérification à destination a expiré ; source conservée",
  "Destination seeding not confirmed; source retained":
    "Le seed à destination n’est pas confirmé ; source conservée",
  "Symlink storage requires its protected Reseed workflow":
    "Les liens symboliques nécessitent le parcours protégé de remise en seed",
  "Renamed torrent files require their original layout":
    "Les fichiers renommés nécessitent leur organisation d’origine",
};
function transferError(message) {
  return transferErrors[message]
    ? t(transferErrors[message], message)
    : t("Impossible de poursuivre. Détails : ", "") + message;
}

async function transferGuard(fn) {
  try {
    document.getElementById("transfer-error")?.remove();
    await fn();
  } catch (error) {
    const dialog = $("dialog");
    if (!dialog.open) {
      notify(String(error.message || error));
      return;
    }
    const message = document.createElement("p");
    message.id = "transfer-error";
    message.className = "note transfer-blocking-summary";
    message.setAttribute("role", "alert");
    message.textContent = transferError(String(error.message || error));
    dialog.append(message);
    message.scrollIntoView({ block: "nearest" });
  }
}

let remoteDraft = null;
function remoteClients() {
  const ids = new Set([
    ...(transferOptions?.sources || []).map((s) => s.client_id),
    transferPlan?.destination || transferDraft?.destination,
  ]);
  return (transferOptions?.clients || []).filter((c) => ids.has(c.id));
}
function drawRemoteAccess() {
  const content = $("transfer-content");
  if (!content || !transferOptions) return;
  const panel = document.createElement("section");
  panel.className = "panel remote-access";
  panel.innerHTML = `<h3>${t("Accès aux fichiers · indépendant du client torrent", "File access · separate from the torrent client")}</h3>${remoteClients().map((c) => `<div class="remote-row ${c.access?.configured && !c.access.checked ? "needs-access" : ""}"><div><strong>${escape(c.name)}</strong><p>${c.access?.configured ? `<span class="badge">${c.access.checked ? t("Vérifié · SFTP", "Checked · SFTP") : t("À vérifier · SFTP", "Check SFTP access")}</span> ${escape(c.access.username)}@${escape(c.access.host)}` : t("Dossiers accessibles à TorrentLinker", "Folders accessible to TorrentLinker")}</p>${c.access?.configured ? `<small>${escape(c.access.client_root)} → ${escape(c.access.file_root)}</small>` : ""}</div><button data-remote-edit="${escape(c.id)}" ${transferPlan?.status === "running" ? "disabled" : ""}>${c.access?.configured ? t("Modifier l’accès…", "Edit access…") : t("Configurer l’accès…", "Configure access…")}</button></div>`).join("")}`;
  const route = document.createElement("div");
  route.className = "note remote-route";
  route.innerHTML = `<strong>${t("Trajet des fichiers", "File route")}</strong><p>${escape([...new Set(transferOptions.sources.map((r) => transferOptions.clients.find((c) => c.id === r.client_id)?.name || r.client_id))].join(", "))} → ${mode === "desktop" ? t("ce PC · TorrentLinker", "this PC · TorrentLinker") : t("serveur TorrentLinker", "TorrentLinker server")} → ${escape(transferOptions.clients.find((c) => c.id === (transferPlan?.destination || transferDraft?.destination))?.name || "")}</p><small>${mode === "web" ? t("Le navigateur pilote le transfert. Il ne relaie pas les fichiers.", "The browser controls the transfer. It does not relay files.") : t("L’application doit rester ouverte pendant le transfert.", "The application must remain open during transfer.")} ${t("La vérification relit les données à destination avant le seed.", "Verification reads destination data before seeding.")}</small>`;
  content.before(route, panel);
  panel.querySelectorAll("[data-remote-edit]").forEach((button) => {
    button.onclick = () => {
      transferCapture();
      clearTimeout(transferTimer);
      openRemoteAccess(button.dataset.remoteEdit);
    };
  });
}
function openRemoteAccess(identifier) {
  const client = transferOptions.clients.find((c) => c.id === identifier);
  const p = client.access || {};
  remoteDraft = {client_id: identifier, config: {
    host: p.host || "", port: p.port || 22, username: p.username || "",
    auth: p.auth || "key", client_root: p.client_root || "", file_root: p.file_root || "",
  }, credential: "", host_key: p.host_key || "", fingerprint: p.fingerprint || "",
  trusted: !!p.host_key, result: "", error: ""};
  drawRemoteDialog();
}
function captureRemote() {
  if (!$("remote-host")) return;
  const previous = remoteDraft.config;
  const config = {host: $("remote-host").value.trim(), port: Number($("remote-port").value),
    username: $("remote-user").value.trim(), auth: $("remote-auth").value,
    client_root: $("remote-client-root").value.trim(), file_root: $("remote-file-root").value.trim()};
  if (previous.host !== config.host || previous.port !== config.port) {
    remoteDraft.host_key = ""; remoteDraft.fingerprint = ""; remoteDraft.trusted = false;
  }
  remoteDraft.config = config;
  remoteDraft.credential = $("remote-credential").value;
}
function drawRemoteDialog() {
  const d = $("dialog"), p = remoteDraft, c = p.config;
  const client = transferOptions.clients.find((client) => client.id === p.client_id);
  d.innerHTML = `<div class="transfer-heading"><div><small>${t("CONNEXION AUX FICHIERS", "FILE CONNECTION")}</small><h2>${escape(client.name)}</h2></div><button id="remote-back" aria-label="${t("Retour", "Back")}">×</button></div><p class="muted">${t("Ces identifiants sont propres aux fichiers. La connexion au client torrent reste séparée.", "These credentials are for files. The torrent client connection stays separate.")}</p><div class="transfer-grid"><section class="panel transfer-card"><h3>SFTP</h3><label>${t("Serveur", "Host")}<input id="remote-host" value="${escape(c.host)}" autocomplete="off"></label><div class="remote-fields"><label>Port<input id="remote-port" type="number" min="1" max="65535" value="${c.port}"></label><label>${t("Utilisateur", "Username")}<input id="remote-user" value="${escape(c.username)}" autocomplete="off"></label></div><label>${t("Authentification", "Authentication")}<select id="remote-auth"><option value="key" ${c.auth === "key" ? "selected" : ""}>${t("Clé SSH", "SSH key")}</option><option value="password" ${c.auth === "password" ? "selected" : ""}>${t("Mot de passe", "Password")}</option></select></label><label>${c.auth === "key" ? t("Clé privée SSH", "Private SSH key") : t("Mot de passe", "Password")}${c.auth === "key" ? `<textarea id="remote-credential" autocomplete="off">${escape(p.credential)}</textarea>` : `<input id="remote-credential" type="password" autocomplete="new-password" value="${escape(p.credential)}">`}</label><small>${client.access?.has_credential ? t("Laissez vide pour conserver le secret enregistré.", "Leave blank to keep the saved credential.") : ""}</small><p class="muted">${mode === "web" ? t("Les identifiants et fichiers sont utilisés par le serveur TorrentLinker, pas par votre navigateur.", "Credentials and files are used by the TorrentLinker server, not your browser.") : t("Les identifiants sont conservés dans le trousseau de ce PC.", "Credentials are stored in this PC’s keyring.")}</p></section><section class="panel transfer-card"><h3>${t("Correspondance des dossiers", "Folder mapping")}</h3><label>${t("Racine vue par le client torrent", "Root seen by the torrent client")}<input id="remote-client-root" value="${escape(c.client_root)}"></label><label>${t("Racine vue en SFTP", "Root seen over SFTP")}<div class="transfer-path"><input id="remote-file-root" value="${escape(c.file_root)}"><button id="remote-browse" ${client.access?.checked ? "" : "disabled"}>${t("Parcourir…", "Browse…")}</button></div></label><p class="muted">${t("Exemple : le client voit /downloads, le compte SFTP voit /home/seed/downloads. Des noms identiques ne prouvent pas un stockage partagé.", "Example: the client sees /downloads, while SFTP sees /home/seed/downloads. Identical names do not prove shared storage.")}</p><h3>${t("Identité du serveur", "Server identity")}</h3>${p.fingerprint ? `<code class="fingerprint">${escape(p.fingerprint)}</code><label class="trust-key"><input id="remote-trust" type="checkbox" ${p.trusted ? "checked" : ""}>${t("Empreinte comparée à celle fournie par mon hébergeur", "Fingerprint compared with my provider’s value")}</label>` : `<p class="muted">${t("Tester l’accès affiche l’empreinte avant toute authentification.", "Check access displays the fingerprint before authentication.")}</p>`}</section></div><section class="panel remote-access ${p.error ? "needs-access" : ""}"><h3>${t("Résultat du contrôle", "Check result")}</h3><p id="remote-result" role="status">${escape(p.error || p.result || t("Accès non vérifié", "Access not checked"))}</p></section><div class="transfer-footer"><button id="remote-test">${t("Tester l’accès", "Check access")}</button><button id="remote-done" class="primary">${t("Revenir au transfert", "Back to transfer")}</button></div>`;
  $("remote-browse").onclick = () => {captureRemote(); transferGuard(() => browseRemoteRoot());};
  $("remote-auth").onchange = () => {captureRemote(); drawRemoteDialog();};
  if ($("remote-trust")) $("remote-trust").onchange = (e) => {p.trusted = e.target.checked;};
  $("remote-back").onclick = $("remote-done").onclick = async () => {
    remoteDraft = null;
    await transferGuard(async () => {
      const items = transferOptions.sources.map((r) => ({client_id: r.client_id, hash: r.hash}));
      transferOptions = await request("transfer-options", {items});
      drawTransfer();
      if (transferPlan) pollTransfer();
    });
  };
  $("remote-test").onclick = async () => {
    captureRemote();
    $("remote-test").disabled = true;
    try {
      const identity = await request("transfer-access-discover", {client_id:p.client_id, config:p.config});
      if (!p.host_key || identity.host_key !== p.host_key) {
        Object.assign(p, identity, {trusted:false, error:"", result:t("Comparez l’empreinte fournie par votre hébergeur, puis confirmez-la.", "Compare the fingerprint with your provider’s value, then confirm it.")});
      } else {
        if (!p.trusted) throw new Error(t("Confirmez l’identité du serveur.", "Confirm the server identity."));
        client.access = await request("transfer-access-save", p);
        p.credential = "";
        const checked = await request("transfer-access-check", {client_id:p.client_id});
        client.access = checked;
        p.error = "";
        p.result = t("Accès vérifié", "Access verified") + ` · ${formatBytes(checked.free_bytes)} ` + t("disponibles", "available");
        // Defaults must now use client-visible paths, not the previous mounted namespace.
        delete transferDraft.overrides[p.client_id];
      }
    } catch (error) {p.error = transferError(error.message); p.result = "";}
    drawRemoteDialog();
  };
}

async function browseRemoteRoot(path = "") {
  const p = remoteDraft, client = transferOptions.clients.find((c) => c.id === p.client_id);
  const access = client.access;
  const result = await request("transfer-remote-browse", {client_id:p.client_id, path});
  const mapped = (value) => access.file_root.replace(/\/$/, "") + value.slice(access.client_root.replace(/\/$/, "").length);
  $("dialog").innerHTML = `<h2>${t("Parcourir les dossiers SFTP", "Browse SFTP folders")}</h2><p>${escape(mapped(result.path))}</p><div class="transfer-folders">${[result.parent, ...result.folders].map((folder, i) => `<button data-sftp-folder="${escape(folder)}">${i === 0 ? "↑ " : ""}${escape(mapped(folder))}</button>`).join("")}</div><div class="transfer-footer"><button id="root-cancel">${t("Annuler", "Cancel")}</button><button id="root-select" class="primary">${t("Choisir ce dossier", "Use this folder")}</button></div>`;
  $("dialog").querySelectorAll("[data-sftp-folder]").forEach((b) => {b.onclick = () => transferGuard(() => browseRemoteRoot(b.dataset.sftpFolder));});
  $("root-cancel").onclick = drawRemoteDialog;
  $("root-select").onclick = () => {p.config.file_root = mapped(result.path); p.result = ""; drawRemoteDialog();};
}
