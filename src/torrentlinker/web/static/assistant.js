/* Same owner APIs as desktop; model output is always rendered as text. */
let assistantView = "chat", assistantConversation = "", assistantRun = "", assistantSnapshot = null;
let assistantRefreshBusy = false, assistantRenderKey = "";
const at = (en, fr) => say(en, fr);
const assistantRoot = () => $("view-assistant");
function aField(form, label, value = "", type = "text", options = null) {
  const wrapper = element("label", label), input = element(options ? "select" : type === "textarea" ? "textarea" : "input");
  if (options) for (const [id, name] of options) { const o = element("option", name); o.value = id; input.append(o); }
  else if (type !== "textarea") input.type = type;
  if (type === "checkbox") input.checked = !!value; else input.value = value;
  wrapper.append(input); form.append(wrapper); return input;
}
function aDialog(title) {
  const dialog = element("dialog", undefined, "assistant-dialog"), form = element("form");
  form.append(element("h2", title)); dialog.append(form); document.body.append(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog.showModal(); return {dialog, form};
}
function aActions(dialog, form, save) {
  const footer = element("div", undefined, "toolbar");
  footer.append(button(at("Save", "Enregistrer"), async () => { await save(); dialog.close(); await loadAssistant(); }, "primary"), button(at("Cancel", "Annuler"), () => dialog.close()));
  form.onsubmit = e => e.preventDefault(); form.append(footer);
}
async function loadAssistant() {
  assistantSnapshot = await api("setup/assistant");
  const root = assistantRoot(); root.replaceChildren(); assistantRenderKey = "";
  const nav = element("div", undefined, "toolbar");
  for (const [id, label] of [["chat", at("Discussion", "Discussion")], ["tasks", at("Automations", "Automatisations")], ["history", at("History", "Historique")], ["connections", at("Connections", "Connexions")]]) {
    nav.append(button(label, async () => { assistantView = id; await loadAssistant(); }, assistantView === id ? "primary" : ""));
  }
  root.append(nav);
  if (assistantView === "connections") return aConnections(root);
  if (assistantView === "tasks") return aTasks(root);
  if (assistantView === "history") {
    const history = await api("assistant/jobs");
    root.append(element("p", at("Runs and tool receipts are stored here. Interrupted actions are never replayed automatically.", "Les exécutions et leurs actions sont conservées ici. Une action interrompue n’est jamais rejouée automatiquement."), "muted"));
    for (const run of history) root.append(aRunCard(run));
    return;
  }
  const layout = element("div", undefined, "assistant-layout"), side = element("aside", undefined, "assistant-conversations"), main = element("div", undefined, "assistant-main");
  side.append(button(at("New discussion", "Nouvelle discussion"), () => aTaskEditor(false), "primary"));
  const conversations = await api("assistant/conversations");
  for (const c of conversations) side.append(button(c.name, async () => { assistantConversation = c.id; assistantRun = ""; await loadAssistant(); }, assistantConversation === c.id ? "active" : ""));
  layout.append(side, main); root.append(layout);
  if (!assistantConversation) {
    main.append(element("h2", at("What would you like to do?", "Que souhaitez-vous faire ?")), element("p", at("Prepare an Upload, build a Zen Plan or review your torrents. Start a discussion and choose its model and permissions.", "Préparez un Upload, créez un Plan Zen ou examinez vos torrents. Créez une discussion et choisissez son modèle et ses autorisations.")));
    if (!assistantSnapshot.providers.length) main.append(button(at("Connect a model", "Connecter un modèle"), () => aProvider()));
    return;
  }
  const current = conversations.find(c => c.id === assistantConversation);
  if (!current) { assistantConversation = ""; return loadAssistant(); }
  main.append(element("p", `${current.name} · ${current.policy.mode === "propose" ? at("Proposals only", "Propositions uniquement") : at("Execute within limits", "Exécution dans les limites")} · ${current.policy.clients.map(id => state.setup.clients.find(c => c.id === id)?.name || id).join(", ")}`, "muted"));
  const transcript = element("div", undefined, "assistant-transcript"); transcript.id = "assistant-transcript";
  main.append(transcript);
  const form = element("form", undefined, "assistant-composer"), prompt = element("textarea");
  prompt.id = "assistant-prompt"; prompt.maxLength = 16000; prompt.rows = 3;
  prompt.placeholder = at("Give a task or ask a question…", "Donnez une tâche ou posez une question…"); prompt.setAttribute("aria-label", at("Message", "Message"));
  const send = element("button", at("Send", "Envoyer"), "primary"); send.type = "submit"; send.id = "assistant-send";
  form.append(prompt, send, button(at("Stop", "Arrêter"), async () => { if (assistantRun) await api(`assistant/jobs/${assistantRun}/cancel`, {}); }));
  prompt.onkeydown = e => { if (e.ctrlKey && e.key === "Enter") { e.preventDefault(); form.requestSubmit(); } };
  form.onsubmit = e => { e.preventDefault(); guard(async () => {
    if (!prompt.value.trim()) return;
    const run = await api("assistant/jobs", {conversation_id: assistantConversation, message: prompt.value});
    assistantRun = run.id; prompt.value = ""; await aRefreshChat();
  }); };
  main.append(form); await aRefreshChat();
}
async function aRefreshChat() {
  if (state.view !== "assistant" || assistantView !== "chat" || !assistantConversation || !$("assistant-transcript") || assistantRefreshBusy) return;
  assistantRefreshBusy = true;
  try {
    const rows = await api(`assistant/jobs?conversation_id=${encodeURIComponent(assistantConversation)}`);
    const key = JSON.stringify(rows); if (key === assistantRenderKey) return;
    assistantRenderKey = key;
    $("assistant-transcript").replaceChildren(...[...rows].reverse().map(aRunCard));
    const active = rows.find(r => ["queued", "running"].includes(r.status));
    assistantRun = active?.id || rows[0]?.id || "";
    $("assistant-send").disabled = !!active;
  } finally { assistantRefreshBusy = false; }
}
function aRunCard(run) {
  const card = element("article", undefined, "assistant-run card");
  card.append(element("p", `${new Date(run.created * 1000).toLocaleString()} · ${aStatus(run.status)} · ${run.calls} ${at("calls", "appels")} · ${run.tokens} tokens`, "muted"));
  for (const m of run.messages) {
    const block = element("div", undefined, `assistant-message ${m.role}`);
    block.append(element("strong", m.role === "user" ? at("You", "Vous") : "Assistant"), element("p", m.content)); card.append(block);
  }
  if (run.error) card.append(element("p", run.error, "error"));
  for (const event of run.events) {
    const detail = element("details"), result = event.result || {};
    detail.append(element("summary", `${event.tool} · ${aStatus(event.status)}`), element("pre", JSON.stringify({arguments: event.arguments, result}, null, 2)));
    if (result.requires_owner_approval && result.id) detail.append(button(at("Review proposal", "Examiner la proposition"), () => aReview(result.id)));
    if (result.job_id) detail.append(button(at("Job progress", "Avancement de la tâche"), async () => {
      const job = await api(`jobs/${result.job_id}`); const pre = detail.querySelector("pre"); pre.textContent = JSON.stringify(job, null, 2);
    }));
    card.append(detail);
  }
  if (["queued", "running"].includes(run.status)) card.append(button(at("Stop", "Arrêter"), async () => { await api(`assistant/jobs/${run.id}/cancel`, {}); await aRefreshChat(); }));
  return card;
}
async function aReview(id, completed = aRefreshChat) {
  const review = await api(`agents/proposals/${id}/review`), {dialog, form} = aDialog(at("Review action", "Vérifier l’action"));
  form.append(element("pre", JSON.stringify(review, null, 2)));
  form.append(button(at("Approve this action", "Approuver cette action"), async () => { await api(`agents/proposals/${id}/approve`, {}); dialog.close(); await completed(); }, "primary"), button(at("Reject", "Refuser"), async () => { await api(`agents/proposals/${id}/reject`, {}); dialog.close(); await completed(); }), button(at("Close", "Fermer"), () => dialog.close()));
}
async function aConnections(root) {
  root.append(element("p", at("Credentials stay in TorrentLinker. Hosted providers receive your messages and tool results. Local connections never fall back to a hosted provider. Daily limit: 200 calls per connection, UTC.", "Les clés restent dans TorrentLinker. Les fournisseurs distants reçoivent vos messages et les résultats des outils. Aucune bascule automatique du local vers une API distante. Limite : 200 appels par connexion et par jour UTC."), "muted"));
  root.append(button(at("Add connection", "Ajouter une connexion"), () => aProvider(), "primary"));
  for (const p of assistantSnapshot.providers) {
    const card = element("div", undefined, "card"); card.append(element("h3", p.name), element("p", `${p.kind} · ${p.model} · ${p.url}`));
    card.append(button(at("Edit", "Modifier"), () => aProvider(p)), button(at("Test tool connection", "Tester les outils"), async () => {
      const result = await api(`setup/assistant/providers/${p.id}/test`, {}); card.append(element("p", result.message));
    })); root.append(card);
  }
  const research = await api("setup/assistant/research"), form = element("form", undefined, "card");
  form.append(element("h3", at("Web research", "Recherche Web")), element("p", at("Choose Brave Search or your SearXNG server. Page reading and book metadata work without a search key. Film metadata uses the TMDb key in Settings.", "Utilisez Brave Search ou votre serveur SearXNG. La lecture de pages et les métadonnées des livres fonctionnent sans clé de recherche. Les films utilisent la clé TMDb des paramètres.")));
  const url = aField(form, "SearXNG URL", research.searxng_url || "", "url"), key = aField(form, "Brave Search API key", "", "password");
  key.placeholder = research.has_brave_key ? at("Saved; leave blank to keep", "Enregistrée ; laisser vide pour conserver") : "";
  form.append(button(at("Save research settings", "Enregistrer la recherche"), async () => {
    await api("setup/assistant/research", {searxng_url: url.value, ...(key.value ? {brave_key: key.value} : {})}, "PUT"); key.value = "";
  })); form.onsubmit = e => e.preventDefault(); root.append(form);
}
function aProvider(existing = null) {
  const {dialog, form} = aDialog(at("Model connection", "Connexion au modèle"));
  const name = aField(form, at("Name", "Nom"), existing?.name || ""), kind = aField(form, at("Provider", "Fournisseur"), existing?.kind || "ollama", "", Object.keys(assistantSnapshot.presets).map(k => [k, k]));
  const url = aField(form, at("Base URL", "Adresse de base"), existing?.url || assistantSnapshot.presets.ollama, "url");
  const model = aField(form, at("Model ID", "Identifiant du modèle"), existing?.model || "");
  const key = aField(form, at("API key", "Clé API"), "", "password"); key.autocomplete = "new-password";
  key.placeholder = at("Leave blank to keep the saved key", "Laisser vide pour conserver la clé");
  form.append(element("p", at("Use an address reachable by TorrentLinker. In Docker, localhost is the container, not your PC. Changing the endpoint clears the saved key unless you supply a new one.", "Utilisez une adresse accessible depuis TorrentLinker. Dans Docker, localhost désigne le conteneur, pas votre PC. Changer l’adresse efface la clé enregistrée, sauf si vous en fournissez une nouvelle."), "muted"));
  kind.onchange = () => { url.value = assistantSnapshot.presets[kind.value]; };
  form.append(button(at("List models", "Lister les modèles"), async () => {
    const unchanged = existing && url.value === existing.url && kind.value === existing.kind && !key.value;
    const models = unchanged ? await api(`setup/assistant/providers/${existing.id}/models`) : await api("setup/assistant/models", {name: name.value || "Discovery", kind: kind.value, url: url.value, model: model.value || "discovery", api_key: key.value});
    form.querySelector("datalist")?.remove();
    const list = element("datalist"); list.id = "assistant-models";
    for (const id of models) { const option = element("option"); option.value = id; list.append(option); }
    form.append(list); model.setAttribute("list", list.id); if (!model.value && models.length) model.value = models[0];
  }));
  aActions(dialog, form, async () => {
    await api("setup/assistant/providers" + (existing ? `/${existing.id}` : ""), {name: name.value, kind: kind.value, url: url.value, model: model.value, ...(key.value ? {api_key: key.value} : {})}, existing ? "PUT" : "POST");
  });
}
async function aTasks(root) {
  root.append(element("p", at("Tasks run while TorrentLinker is running. On desktop, keep the app open; on Docker, closing this browser is fine. Missed intervals are combined into one run. Failed/interrupted runs wait for review and Run now.", "Les tâches s’exécutent lorsque TorrentLinker fonctionne. Sur PC, gardez l’application ouverte ; sur Docker, vous pouvez fermer le navigateur. Les échéances manquées sont regroupées en une seule exécution. Après un échec ou une interruption, vérifiez l’historique puis cliquez sur Exécuter."), "muted"));
  root.append(button(at("Create task", "Créer une tâche"), () => aTaskEditor(true), "primary"));
  for (const t of await api("assistant/schedules")) {
    const card = element("div", undefined, "card"); card.append(element("h3", t.name), element("p", t.instruction), element("p", `${t.enabled ? new Date(t.next_at * 1000).toLocaleString() : at("Paused", "En pause")} · ${t.timezone} · ${t.blocked ? at("Awaiting completion/review", "En attente de fin ou de validation") : t.policy.mode}`));
    if (t.last_error) card.append(element("p", t.last_error, "error"));
    card.append(button(at("Edit", "Modifier"), () => aTaskEditor(true, t)), button(t.enabled ? at("Pause", "Suspendre") : at("Enable", "Activer"), async () => {
      const {id, next_at, last_error, blocked, ...body} = t; await api(`assistant/schedules/${id}`, {...body, enabled: !t.enabled}, "PUT"); await loadAssistant();
    }), button(at("Run now", "Exécuter maintenant"), async () => { await api(`assistant/schedules/${t.id}/run`, {}); assistantView = "history"; await loadAssistant(); })); root.append(card);
  }
}
function aTaskEditor(scheduled, existing = null) {
  const {dialog, form} = aDialog(scheduled ? at("Scheduled task", "Tâche programmée") : at("New discussion", "Nouvelle discussion"));
  const name = aField(form, at("Name", "Nom"), existing?.name || "");
  const provider = aField(form, at("Model connection", "Connexion au modèle"), existing?.provider_id || assistantSnapshot.providers[0]?.id || "", "", assistantSnapshot.providers.map(p => [p.id, `${p.name} · ${p.model}`]));
  const mode = aField(form, at("Action policy", "Politique d’action"), existing?.policy.mode || "propose", "", [["propose", at("Proposals only", "Propositions uniquement")], ["execute", at("Execute within limits", "Exécuter dans les limites")]]);
  const clients = element("fieldset"); clients.append(element("legend", at("Allowed Torrent Clients", "Clients torrent autorisés"))); form.append(clients);
  const clientInputs = state.setup.clients.filter(c => c.enabled).map(c => [c.id, aField(clients, c.name, existing ? existing.policy.clients.includes(c.id) : c.id === state.setup.client_id, "checkbox")]);
  const details = element("details"); details.append(element("summary", at("Permissions and limits", "Autorisations et limites"))); form.append(details);
  const permissions = ["downloads", "controls", "reseed", "uploads"].map(p => [p, aField(details, ({downloads: at("Downloads", "Téléchargements"), controls: at("Torrent controls", "Commandes des torrents"), reseed: at("Reseeds", "Remises en seed"), uploads: "Uploads"})[p], existing?.policy.permissions.includes(p) || false, "checkbox")]);
  const updateMode = () => { for (const [, el] of permissions) el.disabled = mode.value === "propose"; }; mode.onchange = updateMode; updateMode();
  const bytes = aField(details, at("Downloads per day, GiB", "Téléchargements par jour, Gio"), (existing?.policy.daily_bytes ?? 10 * 1024 ** 3) / 1024 ** 3, "number");
  const torrents = aField(details, at("Torrents per day", "Torrents par jour"), existing?.policy.daily_torrents ?? 20, "number");
  const reserve = aField(details, at("Keep free, GiB", "Conserver libres, Gio"), (existing?.policy.reserve_bytes ?? 10 * 1024 ** 3) / 1024 ** 3, "number");
  const calls = aField(details, at("Maximum model calls per run", "Appels au modèle par exécution"), existing?.max_calls ?? 12, "number");
  const seconds = aField(details, at("Maximum duration, seconds", "Durée maximale, secondes"), existing?.max_seconds ?? 300, "number");
  const tokens = aField(details, at("Token limit per run", "Limite de tokens par exécution"), existing?.max_tokens ?? 60000, "number");
  const web = aField(form, at("Allow public Web research", "Autoriser la recherche sur le Web public"), existing?.web || false, "checkbox");
  let instruction, kind, frequency, interval, atTime, timezone, days, enabled;
  if (scheduled) {
    instruction = aField(form, at("Instructions", "Instructions"), existing?.instruction || "", "textarea");
    kind = aField(form, at("Task type", "Type de tâche"), existing?.kind || "model", "", [["model", at("Model task", "Tâche avec modèle")], ["refresh", at("Refresh torrents (no model)", "Actualiser les torrents (sans modèle)")], ["catalogue", at("Refresh Catalogue (no model)", "Actualiser le Catalogue (sans modèle)")]]);
    frequency = aField(form, at("Frequency", "Fréquence"), existing?.frequency || "daily", "", [["interval", at("Every X minutes", "Toutes les X minutes")], ["daily", at("Daily", "Quotidienne")], ["weekly", at("Weekly", "Hebdomadaire")]]);
    interval = aField(form, at("Interval, minutes", "Intervalle, minutes"), existing?.interval_minutes || 60, "number"); interval.min = 5;
    atTime = aField(form, at("Time", "Heure"), existing?.at || "09:00", "time");
    timezone = aField(form, at("Timezone", "Fuseau horaire"), existing?.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone);
    days = element("fieldset"); days.append(element("legend", at("Days", "Jours"))); form.append(days);
    [at("Mon", "Lun"), at("Tue", "Mar"), at("Wed", "Mer"), at("Thu", "Jeu"), at("Fri", "Ven"), at("Sat", "Sam"), at("Sun", "Dim")].forEach((label, i) => { const check = aField(days, label, (existing?.weekdays || [0]).includes(i), "checkbox"); check.value = i; });
    enabled = aField(form, at("Enable schedule", "Activer la programmation"), existing?.enabled || false, "checkbox");
    frequency.onchange = () => { interval.parentElement.hidden = frequency.value !== "interval"; atTime.parentElement.hidden = frequency.value === "interval"; days.hidden = frequency.value !== "weekly"; timezone.parentElement.hidden = frequency.value === "interval"; }; frequency.onchange();
    kind.onchange = () => { provider.disabled = kind.value !== "model"; }; kind.onchange();
  }
  const body = () => ({name: name.value, provider_id: provider.value, policy: {name: name.value, clients: clientInputs.filter(([, e]) => e.checked).map(([id]) => id), mode: mode.value, permissions: permissions.filter(([, e]) => e.checked && !e.disabled).map(([id]) => id), daily_bytes: Math.round(+bytes.value * 1024 ** 3), daily_torrents: +torrents.value, reserve_bytes: Math.round(+reserve.value * 1024 ** 3)}, web: web.checked, max_calls: +calls.value, max_seconds: +seconds.value, max_tokens: +tokens.value,
    ...(scheduled ? {instruction: instruction.value, kind: kind.value, frequency: frequency.value, interval_minutes: +interval.value, at: atTime.value, timezone: timezone.value, weekdays: [...days.querySelectorAll("input:checked")].map(e => +e.value), enabled: enabled.checked} : {})});
  if (scheduled) form.append(button(at("Preview next run", "Voir la prochaine exécution"), async () => { const preview = await api("assistant/schedules/preview", body()); form.append(element("p", new Date(preview.next_at * 1000).toLocaleString())); }));
  aActions(dialog, form, async () => {
    const result = await api(scheduled ? "assistant/schedules" + (existing ? `/${existing.id}` : "") : "assistant/conversations", body(), existing ? "PUT" : "POST");
    if (!scheduled) { assistantConversation = result.id; assistantView = "chat"; }
  });
}
setInterval(() => { if (state.view === "assistant" && assistantView === "chat") guard(aRefreshChat); }, 1500);

function aStatus(value) {
  return ({queued: at("Queued", "En attente"), running: at("Running", "En cours"), completed: at("Completed", "Terminée"), failed: at("Failed", "Échec"), cancelled: at("Cancelled", "Annulée"), interrupted: at("Interrupted", "Interrompue"), awaiting_approval: at("Awaiting approval", "Validation requise"), finished: at("Finished", "Terminé")})[value] || value;
}
