/* Same owner APIs as desktop; chat Markdown is rendered safely by the server. */
let assistantView = "chat", assistantConversation = "", assistantRun = "", assistantSnapshot = null;
let assistantRefreshBusy = false, assistantRenderKey = "", assistantLoadVersion = 0;
const assistantDrafts = new Map();
const assistantCollapsedFolders = new Set();
const at = (en, fr) => say(en, fr);
const assistantRoot = () => $("view-assistant");
function aFolderLabel(folder) {
  return ({"": at("General", "Général"), uploads: at("Uploads", "Uploads"), film_research: at("Film research", "Recherche de films"), series_research: at("Series research", "Recherche de séries"), troubleshooting: at("Troubleshooting", "Dépannage")})[folder] ?? folder;
}
function aConversationFolders(container, conversations) {
  const key = JSON.stringify([assistantConversation, conversations.map(c => [c.id, c.name, c.folder])]);
  if (container.dataset.snapshot === key) return;
  for (const group of container.querySelectorAll(":scope > .assistant-folder")) {
    group.open ? assistantCollapsedFolders.delete(group.dataset.folder) : assistantCollapsedFolders.add(group.dataset.folder);
  }
  container.dataset.snapshot = key;
  const groups = new Map();
  for (const chat of conversations) {
    const folder = chat.folder || "";
    if (!groups.has(folder)) groups.set(folder, []);
    groups.get(folder).push(chat);
  }
  container.replaceChildren();
  for (const [folder, chats] of groups) {
    const group = element("details", undefined, "assistant-folder");
    group.dataset.folder = folder;
    group.open = !assistantCollapsedFolders.has(folder);
    group.addEventListener("toggle", () => {
      if (group.isConnected) group.open ? assistantCollapsedFolders.delete(folder) : assistantCollapsedFolders.add(folder);
    });
    const title = element("summary", aFolderLabel(folder));
    const icon = element("span", "▱", "assistant-folder-icon"); icon.setAttribute("aria-hidden", "true"); title.prepend(icon);
    group.append(title);
    for (const chat of chats) {
      const item = button(chat.name, async () => { assistantConversation = chat.id; assistantRun = ""; await loadAssistant(); }, assistantConversation === chat.id ? "active" : "");
      item.title = chat.name;
      if (assistantConversation === chat.id) item.setAttribute("aria-current", "page");
      group.append(item);
    }
    container.append(group);
  }
}
function aMoveConversation(current, conversations) {
  const {dialog, form} = aDialog(at("Move to folder…", "Déplacer vers un dossier…"));
  const choices = [...new Set(["", "uploads", "film_research", "series_research", "troubleshooting", ...conversations.map(c => c.folder || "")])];
  let newValue = "__new__";
  while (choices.includes(newValue)) newValue += "_";
  const folder = aField(form, at("Folder", "Dossier"), current.folder || "", "", [...choices.map(f => [f, aFolderLabel(f)]), [newValue, at("New folder…", "Nouveau dossier…")]]);
  const name = aField(form, at("Folder name", "Nom du dossier")); name.maxLength = 80; name.parentElement.hidden = true;
  const automatic = aField(form, at("Let the assistant organize this conversation", "Laisser l’assistant classer cette conversation"), current.folder_source !== "manual", "checkbox");
  folder.onchange = () => { name.parentElement.hidden = folder.value !== newValue; automatic.checked = false; };
  aActions(dialog, form, async () => {
    const value = folder.value === newValue ? name.value.trim() : folder.value;
    if (folder.value === newValue && !value) { name.setCustomValidity(at("Enter a folder name", "Saisissez un nom de dossier")); name.reportValidity(); return false; }
    await api(`assistant/conversations/${current.id}/folder`, {folder: value, automatic: automatic.checked}, "PUT");
  });
  name.oninput = () => name.setCustomValidity("");
}
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
  footer.append(button(at("Save", "Enregistrer"), async () => { if (await save() === false) return; dialog.close(); await loadAssistant(); }, "primary"), button(at("Cancel", "Annuler"), () => dialog.close()));
  form.onsubmit = e => e.preventDefault(); form.append(footer);
}
async function loadAssistant() {
  const version = ++assistantLoadVersion;
  const setup = await api("setup/assistant");
  if (version !== assistantLoadVersion) return;
  assistantSnapshot = setup;
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
  side.append(button(at("New discussion", "Nouvelle discussion"), async () => {
    assistantConversation = ""; assistantRun = ""; assistantDrafts.delete("");
    await loadAssistant(); $("assistant-prompt")?.focus();
  }, "primary"));
  const conversations = await api("assistant/conversations");
  if (version !== assistantLoadVersion) return;
  const folders = element("div"); folders.id = "assistant-folders";
  aConversationFolders(folders, conversations); side.append(folders);
  layout.append(side, main); root.append(layout);
  const current = conversations.find(c => c.id === assistantConversation);
  if (current) side.append(button(at("Move to folder…", "Déplacer vers un dossier…"), async () => {
    const latest = await api("assistant/conversations");
    const selected = latest.find(c => c.id === assistantConversation);
    if (selected) aMoveConversation(selected, latest);
  }));
  if (current) side.append(button(at("Delete discussion", "Supprimer la discussion"), async () => {
    if (!confirm(at("Delete this discussion and its history? Pending proposals will be rejected. Torrents and files will not be removed.", "Supprimer cette discussion et son historique ? Les propositions en attente seront refusées. Les torrents et fichiers ne seront pas supprimés."))) return;
    await api(`assistant/conversations/${current.id}`, undefined, "DELETE");
    assistantDrafts.delete(current.id); assistantConversation = ""; assistantRun = "";
    await loadAssistant();
  }));
  if (assistantConversation && !current) { assistantConversation = ""; return loadAssistant(); }
  const defaults = await api("setup/assistant/chat"), config = current || defaults;
  if (version !== assistantLoadVersion) return;
  main.append(element("p", `${current ? current.name + " · " : ""}${config.policy.mode === "propose" ? at("Proposals only", "Propositions uniquement") : at("Execute within limits", "Exécution dans les limites")}`, "muted"));
  const transcript = element("div", undefined, "assistant-transcript"); transcript.id = "assistant-transcript";
  if (!current) {
    const welcome = element("div", undefined, "assistant-welcome");
    welcome.append(element("h2", at("What would you like to do?", "Que souhaitez-vous faire ?")), element("p", at("Prepare an Upload, build a Zen Plan or review your torrents.", "Préparez un Upload, créez un Plan Zen ou examinez vos torrents.")));
    transcript.append(welcome);
  }
  main.append(transcript);
  const form = element("form", undefined, "assistant-composer"), prompt = element("textarea");
  prompt.id = "assistant-prompt"; prompt.maxLength = 16000; prompt.rows = 3;
  prompt.value = assistantDrafts.get(assistantConversation) || "";
  prompt.oninput = () => assistantDrafts.set(assistantConversation, prompt.value);
  prompt.placeholder = at("Give a task or ask a question…", "Donnez une tâche ou posez une question…"); prompt.setAttribute("aria-label", at("Message", "Message"));
  const controls = element("div", undefined, "toolbar assistant-chat-controls");
  const model = element("select"); model.id = "assistant-model";
  model.setAttribute("aria-label", at("Model connection", "Connexion au modèle"));
  for (const p of assistantSnapshot.providers) { const o = element("option", `${p.name} · ${p.model}`); o.value = p.id; model.append(o); }
  if ([...model.options].some(o => o.value === config.provider_id)) model.value = config.provider_id;
  model.onchange = () => guard(async () => {
    if (current) {
      const {id, ...body} = current;
      send.disabled = true; model.disabled = true; settings.disabled = true;
      try { await api(`assistant/conversations/${id}`, {...body, provider_id: model.value}, "PUT"); current.provider_id = model.value; }
      catch (e) { model.value = current.provider_id; throw e; }
      finally { send.disabled = !model.value; model.disabled = false; settings.disabled = false; }
    }
  });
  const settings = button(at("Discussion settings", "Paramètres de la discussion"), () => aTaskEditor(false, {...config, provider_id: model.value}, !current));
  settings.id = "assistant-chat-settings";
  const send = element("button", at("Send", "Envoyer"), "primary"); send.type = "submit"; send.id = "assistant-send";
  send.disabled = !model.value; settings.disabled = !model.value;
  controls.append(model, settings, send, button(at("Stop", "Arrêter"), async () => { if (assistantRun) await api(`assistant/jobs/${assistantRun}/cancel`, {}); }));
  form.append(prompt, controls);
  if (!assistantSnapshot.providers.length) main.append(button(at("Connect a model", "Connecter un modèle"), async () => { assistantView = "connections"; await loadAssistant(); }));
  prompt.onkeydown = e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!send.disabled) form.requestSubmit(); } };
  form.onsubmit = e => { e.preventDefault(); guard(async () => {
    if (!prompt.value.trim() || send.disabled) return;
    send.disabled = true;
    const origin = assistantConversation, message = prompt.value;
    let identifier = origin;
    try {
      if (!identifier) {
        const chat = await api("assistant/conversations", {...defaults, provider_id: model.value, name: "Discussion"});
        identifier = chat.id;
        assistantDrafts.set(identifier, message); assistantDrafts.delete("");
      }
      const run = await api("assistant/jobs", {conversation_id: identifier, message});
      assistantDrafts.delete(identifier);
      if (assistantConversation === origin) {
        assistantConversation = identifier; assistantRun = run.id;
        await loadAssistant(); $("assistant-prompt")?.focus();
      }
    } catch (e) {
      if (assistantConversation === origin && identifier) {
        assistantConversation = identifier; await loadAssistant();
      }
      throw e;
    } finally { send.disabled = !model.value; }
  }); };
  main.append(form); await aRefreshChat();
}
async function aRefreshChat() {
  if (state.view !== "assistant" || assistantView !== "chat" || !assistantConversation || !$("assistant-transcript") || assistantRefreshBusy) return;
  assistantRefreshBusy = true;
  const identifier = assistantConversation, transcript = $("assistant-transcript");
  try {
    const [rows, conversations] = await Promise.all([api(`assistant/jobs?conversation_id=${encodeURIComponent(identifier)}`), api("assistant/conversations")]);
    if (assistantConversation !== identifier || $("assistant-transcript") !== transcript) return;
    if ($("assistant-folders")) aConversationFolders($("assistant-folders"), conversations);
    const key = JSON.stringify(rows); if (key === assistantRenderKey) return;
    assistantRenderKey = key;
    const position = transcript.scrollTop, bottom = position >= transcript.scrollHeight - transcript.clientHeight - 20;
    transcript.replaceChildren(...[...rows].reverse().map(aRunCard));
    transcript.scrollTop = bottom ? transcript.scrollHeight : position;
    const active = rows.find(r => ["queued", "running", "awaiting_approval", "awaiting_user", "waiting_settings"].includes(r.status));
    assistantRun = active?.id || rows[0]?.id || "";
    $("assistant-send").disabled = !!active || !$("assistant-model").value;
    $("assistant-model").disabled = !!active;
    $("assistant-chat-settings").disabled = !!active;
  } finally { assistantRefreshBusy = false; }
}
function aMarkdown(message) {
  const content = element("div", undefined, "assistant-markdown");
  // HTML comes only from the server's restricted Markdown renderer.
  if (message.html) content.innerHTML = message.html;
  else content.textContent = message.content;
  for (const link of content.querySelectorAll("a")) {
    const href = link.getAttribute("href") || "";
    // Tool citations are app-relative; retain the reverse proxy's mount path.
    if (href.startsWith("/documentation/")) link.href = new URL(href.slice(1), document.baseURI).href;
    link.rel = "noopener noreferrer";
    link.target = "_blank";
  }
  for (const image of content.querySelectorAll("img")) {
    image.addEventListener("error", () => {
      image.replaceWith(element("span", at("Image unavailable", "Image indisponible"), "assistant-image-error"));
    }, {once: true});
  }
  return content;
}
const assistantExpandedActivity = new Set();
const assistantExpandedCommands = new Set();
function aCommand(event, key) {
  const details = element("details", undefined, "assistant-command");
  details.open = assistantExpandedCommands.has(key);
  const summary = element("summary");
  const update = () => { summary.textContent = details.open ? at("Hide full command", "Masquer la commande complète") : at("Show full command", "Afficher la commande complète"); };
  update();
  details.addEventListener("toggle", () => {
    update();
    if (details.isConnected) details.open ? assistantExpandedCommands.add(key) : assistantExpandedCommands.delete(key);
  });
  const command = Object.fromEntries(["tool", "arguments", "review"].filter(k => k in event).map(k => [k, event[k]]));
  details.append(summary, aJson(command));
  return details;
}
function aJson(value) {
  const pre = element("pre", undefined, "assistant-json"), code = element("code");
  pre.setAttribute("tabindex", "0");
  pre.setAttribute("aria-label", at("Full command (JSON)", "Commande complète (JSON)"));
  const text = JSON.stringify(value, null, 2);
  const tokens = /"(?:\\.|[^"\\])*"\s*(?=:)|"(?:\\.|[^"\\])*"|\b(?:true|false|null)\b|-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g;
  let end = 0;
  for (const match of text.matchAll(tokens)) {
    code.append(document.createTextNode(text.slice(end, match.index)));
    const value = match[0], next = text.slice(match.index + value.length).trimStart();
    const kind = next.startsWith(":") ? "key" : value.startsWith('"') ? "string" : ["true", "false", "null"].includes(value) ? "literal" : "number";
    code.append(element("span", value, `json-${kind}`));
    end = match.index + value.length;
  }
  code.append(document.createTextNode(text.slice(end))); pre.append(code);
  return pre;
}

const assistantExpandedToolEvents = new Set();
const aToolDescription = event => at(event.description?.en, event.description?.fr) || event.tool.replaceAll("_", " ");
const aToolError = event => String(event.error || event.result?.error || event.result?.job?.error ||
  ((event.status === "failed" || event.result?.job?.status === "failed") ? at("Tool call failed.", "Échec de l’appel d’outil.") : "")).slice(0, 2000);
function aActivity(card, run, indexed, anchor) {
  const key = `${run.id}:${anchor}`;
  const activity = element("details", undefined, "assistant-activity");
  activity.open = assistantExpandedActivity.has(key);
  activity.addEventListener("toggle", () => { if (activity.isConnected) activity.open ? assistantExpandedActivity.add(key) : assistantExpandedActivity.delete(key); });
  const usage = `${run.calls} ${at("calls", "appels")} · ${run.tokens} tokens`;
  const failures = indexed.filter(([, event]) => aToolError(event));
  const label = indexed.length ? `${aToolDescription((failures.at(-1) || indexed.at(-1))[1])} · ${indexed.length}` : usage;
  let groupStatus = indexed.length ? (indexed.find(([, event]) => ["running", "waiting", "failed"].includes(event.status))?.[1].status || "finished") : run.status;
  if (groupStatus === "waiting") groupStatus = run.status;
  if (failures.length) { if (groupStatus === "finished") groupStatus = "failed"; activity.classList.add("has-tool-error"); }
  activity.append(element("summary", `${label} · ${aStatus(groupStatus)}`));
  const entries = element("div", undefined, "assistant-tool-list");
  entries.append(element("p", usage, "assistant-usage"));
  if (run.compactions) entries.append(element("p", at("Context compacted; full history retained.", "Contexte compacté ; historique complet conservé."), "assistant-usage"));
  activity.append(entries); card.append(activity);
  for (const [index, event] of indexed) {
    const detail = element("details", undefined, "assistant-tool"), result = event.result || {};
    const eventKey = `${run.id}:${index}`;
    const error = aToolError(event);
    if (error) detail.classList.add("has-tool-error");
    detail.append(element("summary", `${aToolDescription(event)} · ${aStatus(error ? "failed" : event.status === "waiting" ? run.status : event.status)}`));
    const content = element("div"); detail.append(content);
    const fill = () => {
      if (detail.open && !content.childElementCount) {
        if (error) content.append(element("p", error, "assistant-tool-error"));
        content.append(aJson(Object.fromEntries(["tool", "arguments", "result", "review", "error"].filter(k => k in event).map(k => [k, event[k]]))));
        if (result.job_id) content.append(button(at("Job progress", "Avancement de la tâche"), async () => {
          const job = await api(`jobs/${result.job_id}`); content.querySelector("pre").replaceWith(aJson(job));
        }));
      }
    };
    detail.open = assistantExpandedToolEvents.has(eventKey); fill();
    detail.addEventListener("toggle", () => {
      if (detail.isConnected) detail.open ? assistantExpandedToolEvents.add(eventKey) : assistantExpandedToolEvents.delete(eventKey);
      fill();
    });
    entries.append(detail);
    if (event.status === "waiting" && result.requires_owner_approval && result.id && !("decision" in event)) {
      const panel = element("section", undefined, "assistant-decision card");
      panel.append(element("h3", at("Action requires your approval", "Action à approuver")));
      const fields = element("div", undefined, "assistant-request-summary");
      for (const line of at(event.summary?.en, event.summary?.fr) || [event.tool]) fields.append(element("p", line));
      fields.append(aCommand(event, `${run.id}:${index}`));
      const decide = async approve => { await api(`assistant/jobs/${run.id}/decisions/${index}`, {approve}); await aRefreshChat(); };
      panel.append(fields, button(at("Approve once", "Approuver une fois"), () => decide(true), "primary"), button(at("Reject", "Refuser"), () => decide(false)));
      card.append(panel);
    }
    if (event.status === "waiting" && event.question && !("answer" in event)) {
      const panel = element("section", undefined, "assistant-question card"), choices = element("select"), custom = element("input"), submit = button(at("Submit answer", "Envoyer la réponse"), async () => {
        await api(`assistant/jobs/${run.id}/questions/${index}`, {answer: custom.value.trim() ? custom.value : choices.value}); await aRefreshChat();
      }, "primary");
      choices.append(new Option(at("Choose an answer…", "Choisir une réponse…"), ""));
      for (const option of event.question.options) choices.append(new Option(option, option));
      choices.setAttribute("aria-label", at("Suggested answers", "Réponses suggérées"));
      custom.placeholder = at("Or enter your own answer", "Ou saisir votre réponse"); custom.maxLength = 16000;
      submit.disabled = true;
      const changed = () => { submit.disabled = !custom.value.trim() && !choices.value; };
      choices.addEventListener("change", changed); custom.addEventListener("input", changed);
      panel.append(element("h3", event.question.question), choices, custom, submit); card.append(panel);
    }
  }
}
function aRunCard(run) {
  const card = element("article", undefined, "assistant-run"), groups = new Map();
  let fallback = run.messages.length - 1;
  if (run.messages.at(-1)?.role === "assistant") fallback--;
  run.events.forEach((event, index) => {
    const raw = Number.isInteger(event.after_message_index) ? event.after_message_index : fallback;
    const anchor = Math.max(-1, Math.min(raw, run.messages.length - 1));
    if (!groups.has(anchor)) groups.set(anchor, []);
    groups.get(anchor).push([index, event]);
  });
  if (groups.has(-1)) aActivity(card, run, groups.get(-1), -1);
  run.messages.forEach((message, index) => {
    const block = element("div", undefined, `assistant-message ${message.role}`);
    block.setAttribute("aria-label", message.role === "user" ? at("You", "Vous") : "Assistant");
    block.append(aMarkdown(message)); card.append(block);
    if (groups.has(index)) aActivity(card, run, groups.get(index), index);
  });
  // Keep activity chronological; place card presentations after the response summary.
  for (const event of run.events) {
    if (event.tool === "present_selection" && event.result?.presentation_id) {
      card.append(aSelectionCards(event.result.presentation_id));
    }
  }
  if (!run.events.length) aActivity(card, run, [], run.messages.length);
  if (run.error) card.append(element("p", run.error, "error"));
  if (["queued", "running", "awaiting_approval", "awaiting_user", "waiting_settings"].includes(run.status)) card.append(element("p", at("Working…", "En cours…"), "assistant-working"), button(at("Stop", "Arrêter"), async () => { await api(`assistant/jobs/${run.id}/cancel`, {}); await aRefreshChat(); }));
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
  root.append(button(at("Chat defaults", "Paramètres des nouvelles discussions"), async () => aTaskEditor(false, await api("setup/assistant/chat"), true)));
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
  const contextAuto = aField(form, at("Detect context automatically", "Détecter automatiquement le contexte"), existing?.context_auto ?? true, "checkbox");
  const contextWindow = aField(form, at("Context window (tokens)", "Fenêtre de contexte (tokens)"), existing?.context_window ?? 32768, "number");
  contextWindow.min = 512; contextWindow.max = 2000000;
  const key = aField(form, at("API key", "Clé API"), "", "password"); key.autocomplete = "new-password";
  key.placeholder = at("Leave blank to keep the saved key", "Laisser vide pour conserver la clé");
  form.append(element("p", at("Detection runs before each task. The configured value is a fallback when metadata is unavailable. Disable detection for a manual override.", "La détection s’effectue avant chaque tâche. La valeur configurée sert de repli si les métadonnées sont indisponibles. Désactivez la détection pour utiliser une valeur manuelle."), "muted"));
  const contextStatus = element("p", "", "muted");
  const contextBody = () => ({name: name.value || "Discovery", kind: kind.value, url: url.value, model: model.value, context_window: +contextWindow.value, context_auto: contextAuto.checked, ...(key.value ? {api_key: key.value} : {})});
  const checkContext = button(at("Check context", "Vérifier le contexte"), async () => {
    const snapshot = JSON.stringify(contextBody());
    checkContext.disabled = true;
    contextStatus.textContent = at("Checking server context…", "Vérification du contexte du serveur…");
    try {
      const result = await api(existing ? `setup/assistant/providers/${existing.id}/context` : "setup/assistant/context", contextBody());
      if (!dialog.isConnected || snapshot !== JSON.stringify(contextBody())) return;
      const source = {server: at("Server context", "Contexte du serveur"), provider: at("Provider context", "Contexte du fournisseur"), manual: at("Manual context", "Contexte manuel"), fallback: at("Not reported. Fallback", "Non communiqué. Valeur de repli")};
      contextStatus.textContent = `${source[result.source]}: ${result.context_window.toLocaleString()} tokens`;
    } finally { checkContext.disabled = false; }
  });
  for (const input of [kind, url, model, key, contextWindow, contextAuto]) input.addEventListener("input", () => { contextStatus.textContent = ""; });
  form.append(checkContext, contextStatus);
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
    await api("setup/assistant/providers" + (existing ? `/${existing.id}` : ""), {name: name.value, kind: kind.value, url: url.value, model: model.value, context_window: +contextWindow.value, context_auto: contextAuto.checked, ...(key.value ? {api_key: key.value} : {})}, existing ? "PUT" : "POST");
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
function aTaskEditor(scheduled, existing = null, defaults = false) {
  const {dialog, form} = aDialog(scheduled ? at("Scheduled task", "Tâche programmée") : defaults ? at("Chat defaults", "Paramètres des nouvelles discussions") : at("Discussion settings", "Paramètres de la discussion"));
  const name = aField(form, at("Name", "Nom"), existing?.name || "");
  if (defaults) name.parentElement.hidden = true;
  const provider = aField(form, at("Model connection", "Connexion au modèle"), existing?.provider_id || assistantSnapshot.providers[0]?.id || "", "", assistantSnapshot.providers.map(p => [p.id, `${p.name} · ${p.model}`]));
  const mode = aField(form, at("Action policy", "Politique d’action"), existing?.policy.mode || "propose", "", [["propose", at("Proposals only", "Propositions uniquement")], ["execute", at("Execute within limits", "Exécuter dans les limites")]]);
  const clients = element("fieldset"); clients.append(element("legend", at("Allowed Torrent Clients", "Clients torrent autorisés"))); form.append(clients);
  const clientInputs = state.setup.clients.filter(c => c.enabled).map(c => [c.id, aField(clients, c.name, existing ? existing.policy.clients.includes(c.id) : c.id === state.setup.client_id, "checkbox")]);
  const details = element("details"); details.append(element("summary", at("Permissions and limits", "Autorisations et limites"))); form.append(details);
  const permissions = ["queue", "downloads", "controls", "reseed", "uploads"].map(p => [p, aField(details, ({queue: at("Prepare and edit download queue", "Préparer et modifier la file"), downloads: at("Start downloads", "Démarrer les téléchargements"), controls: at("Torrent controls", "Commandes des torrents"), reseed: at("Reseeds", "Remises en seed"), uploads: "Uploads"})[p], existing?.policy.permissions.includes(p) || false, "checkbox")]);
  const updateMode = () => { for (const [, el] of permissions) el.disabled = mode.value === "propose"; }; mode.onchange = updateMode; updateMode();
  const bytes = aField(details, at("Downloads per day, GiB", "Téléchargements par jour, Gio"), (existing?.policy.daily_bytes ?? 10 * 1024 ** 3) / 1024 ** 3, "number");
  const torrents = aField(details, at("Torrents per day", "Torrents par jour"), existing?.policy.daily_torrents ?? 20, "number");
  const reserve = aField(details, at("Keep free, GiB", "Conserver libres, Gio"), (existing?.policy.reserve_bytes ?? 10 * 1024 ** 3) / 1024 ** 3, "number");
  const calls = aField(details, at("Maximum model calls per run", "Appels au modèle par exécution"), existing?.max_calls ?? (scheduled ? 12 : 0), "number");
  const seconds = aField(details, at("Maximum duration, seconds", "Durée maximale, secondes"), existing?.max_seconds ?? (scheduled ? 300 : 0), "number");
  if (!scheduled) details.append(element("p", at("Set calls or duration to 0 for no per-run limit. Stop remains available.", "Indiquez 0 pour ne pas limiter les appels ou la durée. Le bouton Arrêter reste disponible.")));
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
  const body = () => ({name: name.value, provider_id: provider.value, policy: {name: name.value, clients: clientInputs.filter(([, e]) => e.checked).map(([id]) => id), mode: mode.value, permissions: permissions.filter(([, e]) => e.checked && !e.disabled).map(([id]) => id), daily_bytes: Math.round(+bytes.value * 1024 ** 3), daily_torrents: +torrents.value, reserve_bytes: Math.round(+reserve.value * 1024 ** 3)}, web: web.checked, max_output_tokens: existing?.max_output_tokens ?? 2048, max_calls: +calls.value, max_seconds: +seconds.value,
    ...(scheduled ? {instruction: instruction.value, kind: kind.value, frequency: frequency.value, interval_minutes: +interval.value, at: atTime.value, timezone: timezone.value, weekdays: [...days.querySelectorAll("input:checked")].map(e => +e.value), enabled: enabled.checked} : {})});
  if (scheduled) form.append(button(at("Preview next run", "Voir la prochaine exécution"), async () => { const preview = await api("assistant/schedules/preview", body()); form.append(element("p", new Date(preview.next_at * 1000).toLocaleString())); }));
  aActions(dialog, form, async () => {
    if (scheduled) {
      await api("assistant/schedules" + (existing ? `/${existing.id}` : ""), body(), existing ? "PUT" : "POST");
    } else {
      await api(defaults ? "setup/assistant/chat" : `assistant/conversations/${existing.id}`, body(), "PUT");
    }
  });
}
setInterval(() => { if (state.view === "assistant" && assistantView === "chat") guard(aRefreshChat); }, 1500);

function aStatus(value) {
  return ({queued: at("Queued", "En attente"), running: at("Running", "En cours"), completed: at("Completed", "Terminée"), failed: at("Failed", "Échec"), cancelled: at("Cancelled", "Annulée"), interrupted: at("Interrupted", "Interrompue"), awaiting_approval: at("Awaiting approval", "Validation requise"), awaiting_user: at("Awaiting your answer", "Réponse requise"), waiting_settings: at("Waiting for settings to finish updating", "Mise à jour des paramètres en cours"), finished: at("Finished", "Terminé")})[value] || value;
}
