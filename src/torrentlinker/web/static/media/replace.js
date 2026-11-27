"use strict";
/* Replace a library film with a better release (ADR-0029, #203, #204). On a film of "Meilleures
   versions sur le tracker", the Owner sees the old and the new release side by side, two switches
   and, once Télécharger has sent the release, the timeline of what happens next. A Member sees
   nothing here: they ask (requests.js). */
const mediaReplaceDefault = {use_time: true, hours: 168, use_ratio: true, ratio: 1, combine: "any"};
const mediaReplaceOptions = {replace: false, wait: true, rule: mediaReplaceRule()};
function mediaReplaceRule() {
  try { return {...mediaReplaceDefault, ...JSON.parse(localStorage.getItem("tl-media-fin-du-partage") || "{}")}; } catch { return {...mediaReplaceDefault}; }
}
function mediaReplaceSaveRule(rule) {
  mediaReplaceOptions.rule = rule;
  try { localStorage.setItem("tl-media-fin-du-partage", JSON.stringify(rule)); } catch { /* the rule still applies to this page */ }
}
// What Télécharger sends along: nothing for a film that is not being replaced.
let mediaReplaceRefresh = null;
const mediaReplaceBody = () => ({client_id: mediaClient(), replace: mediaReplaceOptions.replace, wait: mediaReplaceOptions.replace && mediaReplaceOptions.wait, rule: mediaReplaceOptions.rule});
// The ⓘ info box (panel/info.js), as a node.
function mediaReplaceTip(en, french) {
  const holder = document.createElement("span");
  holder.innerHTML = TLInfo.html(say(en, french));
  return holder.firstChild;
}
// The library folder's own name, not its full path (the old release sits one level below it).
function mediaReplaceFolder(path) {
  const parts = String(path).split("/").filter(Boolean), node = element("b", parts.length > 1 ? parts[parts.length - 2] : parts[0] || path);
  node.title = path;
  return node;
}
const mediaReplaceNumber = value => String(value).replace(".", say(".", ","));
function mediaReplaceSize(bytes) {
  const gb = bytes / 1e9;
  if (gb >= 1000) return `${mediaReplaceNumber((gb / 1000).toFixed(1))} ${say("TB", "To")}`;
  return gb >= 1 ? `${mediaReplaceNumber(gb.toFixed(1))} ${say("GB", "Go")}` : `${Math.round(bytes / 1e6)} ${say("MB", "Mo")}`;
}
function mediaReplaceRuleText(rule) {
  const parts = [];
  if (rule.use_time) parts.push(rule.hours % 24 === 0 ? `${rule.hours / 24} ${say("d", "j")}` : `${mediaReplaceNumber(rule.hours)} h`);
  if (rule.use_ratio) parts.push(`ratio ${mediaReplaceNumber(rule.ratio)}`);
  if (!parts.length) return say("no wait", "sans attente");
  return parts.length === 2 ? parts.join(rule.combine === "all" ? say(" and ", " et ") : say(" or ", " ou ")) : parts[0];
}
function mediaReplaceSteps(run, seeds) {
  const list = [["send", say("Sent to the client", "Envoyée au client")], ["download", say("Downloading", "Téléchargement")],
    ["done", say("Done", "Terminé"), say("The new version plays and your watch state is kept.", "La nouvelle version joue et votre état de lecture est conservé.")]];
  if (run.replace && run.wait && seeds) list.push(["fin", say("Old version ending its share", "Ancienne version en fin de partage"), say(`Rule: ${mediaReplaceRuleText(run.rule)}. It is hidden from Media and stays visible in Torrents.`, `Règle : ${mediaReplaceRuleText(run.rule)}. Elle est cachée de Médias et reste visible dans Torrents.`)]);
  if (run.replace) list.push(["trash", say("Old version in the Trash", "Ancienne version à la corbeille"), say("Removed from the client, its files can be restored for 7 days.", "Retirée du client, ses fichiers sont restaurables 7 jours.")]);
  return list;
}
function mediaReplaceToggle(id, on, label, hint, disabled) {
  const toggle = element("div", undefined, "media-replace-toggle");
  toggle.setAttribute("role", "switch"); toggle.tabIndex = 0; toggle.dataset.toggle = id;
  toggle.setAttribute("aria-checked", String(on)); toggle.setAttribute("aria-disabled", String(!!disabled));
  const text = element("span"); text.append(label, " ", ...hint);
  toggle.append(element("span", undefined, "media-replace-switch"), text);
  return toggle;
}
function mediaReplaceRuleDialog(onSave) {
  const rule = mediaReplaceOptions.rule, dialog = element("dialog", undefined, "media-replace-dialog");
  const days = rule.hours % 24 === 0;
  dialog.innerHTML = `<h2></h2>
    <label class="rule"><input type="checkbox" id="mr-use-time"> <span></span>
      <input type="number" id="mr-amount" min="1" step="1"><select id="mr-unit"><option value="h"></option><option value="d"></option></select></label>
    <label class="rule"><input type="checkbox" id="mr-use-ratio"> <span></span><input type="number" id="mr-ratio" min="0.1" step="0.1"></label>
    <div class="combine" id="mr-combine-row"><span></span><select id="mr-combine"><option value="any"></option><option value="all"></option></select></div>
    <div id="mr-none" hidden></div><div class="actions"></div>`;
  const $$ = id => dialog.querySelector("#" + id);
  dialog.querySelector("h2").append(say("End of sharing", "Fin du partage"), " ", mediaReplaceTip("When the replaced old version has finished sharing and may be removed.", "Quand l'ancienne version, remplacée, a fini son partage et peut être retirée."));
  const labels = dialog.querySelectorAll("label.rule span"); labels[0].textContent = say("Shared at least", "Partagée au moins"); labels[1].textContent = say("Ratio of at least", "Ratio d'au moins");
  const [hours, daysOption] = $$("mr-unit").options; hours.textContent = say("hours", "heures"); daysOption.textContent = say("days", "jours");
  dialog.querySelector("#mr-combine-row span").textContent = say("It takes", "Il faut");
  const [any, all] = $$("mr-combine").options; any.textContent = say("either one", "l'un ou l'autre"); all.textContent = say("both", "les deux");
  $$("mr-none").append(say("No wait", "Sans attente"), " ", mediaReplaceTip("No condition ticked: the old version is removed as soon as the new one is complete.", "Aucune condition cochée : l'ancienne version est retirée dès que la nouvelle est complète."));
  $$("mr-use-time").checked = rule.use_time; $$("mr-use-ratio").checked = rule.use_ratio;
  $$("mr-amount").value = days ? rule.hours / 24 : rule.hours; $$("mr-unit").value = days ? "d" : "h";
  $$("mr-ratio").value = rule.ratio; $$("mr-combine").value = rule.combine;
  const sync = () => {
    $$("mr-combine-row").hidden = !($$("mr-use-time").checked && $$("mr-use-ratio").checked);
    $$("mr-none").hidden = $$("mr-use-time").checked || $$("mr-use-ratio").checked;
  };
  dialog.addEventListener("change", sync); sync();
  const cancel = button(say("Cancel", "Annuler"), () => dialog.close()), save = button(say("Save", "Enregistrer"), () => {
    const amount = Math.max(1, Number($$("mr-amount").value) || 1);
    onSave({use_time: $$("mr-use-time").checked, hours: $$("mr-unit").value === "d" ? amount * 24 : amount, use_ratio: $$("mr-use-ratio").checked,
      ratio: Math.max(0.1, Number($$("mr-ratio").value) || 1), combine: $$("mr-combine").value});
    dialog.close();
  }, "primary");
  dialog.querySelector(".actions").append(cancel, save);
  dialog.addEventListener("close", () => dialog.remove());
  document.body.append(dialog); dialog.showModal();
}
// The card of one better version. `context` says what the old release is and where the new one lands.
function mediaReplaceRender(box, context, run) {
  const old = context.old, started = !!run;
  const replace = started ? run.replace : mediaReplaceOptions.replace, wait = started ? run.wait : mediaReplaceOptions.wait;
  box.replaceChildren();
  box.append(element("header", say("Replace the old version", "Remplacer l'ancienne version")));
  const compare = element("div", undefined, "media-replace-compare");
  const version = (cls, title, name, size, score, seed) => {
    const part = element("div", undefined, `media-replace-version ${cls}`);
    part.append(element("b", title), element("span", name, "name"));
    const facts = element("small", `${mediaReplaceSize(size)} · ReleaseScore `);
    if (score !== undefined && score !== null) facts.append(element("span", String(score), `media-replace-score ${cls ? "" : "low"}`));
    part.append(facts);
    if (seed) part.append(seed);
    return part;
  };
  const seed = element("small", old.seeding ? say(`sharing · ${old.hours} h · ratio ${mediaReplaceNumber(old.ratio)}`, `en partage · ${old.hours} h · ratio ${mediaReplaceNumber(old.ratio)}`) : say("no longer sharing", "ne partage plus"), `media-replace-seed ${old.seeding ? "" : "off"}`);
  seed.prepend(element("i"));
  compare.append(version("", say("In your library", "Dans votre médiathèque"), old.name, old.size, old.own_score, seed),
    element("span", "→", "media-replace-arrow"), version("new", say("On the tracker", "Sur le tracker"), context.new.name, context.new.size, context.new_score));
  box.append(compare);
  const where = context.placement, dest = element("p", undefined, `media-replace-dest ${where?.fallback ? "warn" : ""}`);
  if (!where) dest.textContent = context.problem;
  else if (where.fallback) dest.append(say("Downloaded in ", "Téléchargé dans "), mediaReplaceFolder(where.folder), " ", mediaReplaceTip(`Not enough room beside the old version (${mediaReplaceSize(where.beside_free)} free, ${mediaReplaceSize(context.new.size)} needed): the new version goes to the Download Folder (${mediaReplaceSize(where.free)} free).`, `Pas assez de place à côté de l'ancienne version (${mediaReplaceSize(where.beside_free)} libres, ${mediaReplaceSize(context.new.size)} nécessaires) : la nouvelle version va dans le Dossier de téléchargement (${mediaReplaceSize(where.free)} libres).`));
  else dest.append(say("Downloaded in ", "Téléchargé dans "), mediaReplaceFolder(where.folder), " ", mediaReplaceTip(`The new version downloads beside the old one (${mediaReplaceSize(where.free)} free).`, `La nouvelle version se télécharge à côté de l'ancienne (${mediaReplaceSize(where.free)} libres).`));
  box.append(dest);
  const toggles = element("div", undefined, "media-replace-toggles");
  toggles.append(mediaReplaceToggle("replace", replace, say("Replace the old version", "Remplacer l'ancienne version"),
    [old.seeding ? mediaReplaceTip("When the new one is complete, the old one leaves Media, then goes to the Trash.", "Quand la nouvelle est complète, l'ancienne quitte Médias puis part à la corbeille.") : mediaReplaceTip("It no longer shares: it goes to the Trash as soon as the new one is complete.", "Elle ne partage plus : elle part à la corbeille dès que la nouvelle est complète.")], started));
  if (old.seeding) {
    const edit = button("⚙", () => mediaReplaceRuleDialog(rule => { mediaReplaceSaveRule(rule); mediaReplaceRender(box, context, run); }), "media-replace-link media-replace-gear");
    edit.setAttribute("aria-label", say("Set the end of sharing", "Régler la fin du partage")); edit.title = say("Set", "Régler");
    const rule = mediaReplaceRuleText(started ? run.rule : mediaReplaceOptions.rule);
    toggles.append(mediaReplaceToggle("wait", replace && wait, say("Wait for its sharing to end", "Attendre la fin de son partage"),
      [mediaReplaceTip(`Rule: ${rule}. The old version keeps sharing until then.`, `Règle : ${rule}. L'ancienne version reste en partage jusque-là.`), edit], started || !replace));
  }
  box.append(toggles);
  if (started) {
    const list = mediaReplaceSteps(run, old.seeding);
    const at = {downloading: 1, "seeding-out": list.findIndex(([key]) => key === "fin"), done: list.length, "trash-failed": list.length - 1}[run.state] ?? 1;
    const timeline = element("div", undefined, "media-replace-timeline");
    list.forEach(([key, text, why], index) => {
      const step = element("div", undefined, `media-replace-step ${index < at ? "done" : index === at ? "now" : ""}`);
      const label = element("span", text);
      if (why) label.append(" ", mediaReplaceTip(why, why));
      if (key === "fin" && index === at) label.append(" ", button(say("See in Torrents", "Voir dans Torrents"), () => host("go", {view: "torrents"}), "media-replace-link"));
      if (key === "trash" && index <= at) label.append(" ", button(say("Restore", "Restaurer"), () => host("go", {view: "files", section: "trash"}), "media-replace-link"));
      if (run.error && index === at) label.append(" ", element("i", run.error));
      step.append(element("b", index < at ? "✓" : index === at ? "●" : "○"), label); timeline.append(step);
    });
    box.append(timeline);
    if (at >= list.length) box.append(element("p", say("Done.", "Terminé."), "media-replace-note"));
  }
}
async function mediaReplaceCard(row, actions, queue) {
  const hash = row.tracker.hash;
  let context;
  try { context = await api(`media/tracker/${encodeURIComponent(hash)}/replace?${mediaQuery({})}`); } catch { return; }
  if (!context?.available || !actions.isConnected) return;
  context.new_score = row.tracker.score;
  context.old.own_score ??= row.tracker.own_score;
  const content = actions.parentElement, view = $("view-media"), box = element("div", undefined, "media-replace");
  box.addEventListener("click", event => {
    const toggle = event.target.closest("[data-toggle]");
    if (!toggle || toggle.getAttribute("aria-disabled") === "true" || event.target.closest("button")) return;
    if (toggle.dataset.toggle === "replace") mediaReplaceOptions.replace = !mediaReplaceOptions.replace; else mediaReplaceOptions.wait = !mediaReplaceOptions.wait;
    mediaReplaceRender(box, context, null);
  });
  box.addEventListener("keydown", event => {
    if ((event.key === " " || event.key === "Enter") && event.target.matches("[data-toggle]")) { event.preventDefault(); event.target.click(); }
  });
  actions.after(box);
  // The banner is a fixed height; the card makes it as tall as it needs.
  const grow = () => view?.style.setProperty("--media-banner-height", `${380 + Math.ceil(box.getBoundingClientRect().height) + 16}px`);
  let timer = 0;
  const refresh = async () => {
    clearTimeout(timer);
    if (!box.isConnected) { view?.style.removeProperty("--media-banner-height"); return; }
    let run = null;
    try { run = (await api(`media/replacements?client_id=${encodeURIComponent(mediaClient())}`)).replacements.find(r => r.film === context.film && r.new_hash === hash.toLowerCase()) || null; } catch { /* the card stays as it was */ }
    mediaReplaceRender(box, context, run);
    if (run) { queue.textContent = say("Sent", "Envoyée"); queue.disabled = true; }
    grow();
    if (!run || ["downloading", "seeding-out"].includes(run.state)) timer = setTimeout(refresh, run ? 10000 : 30000);
  };
  mediaReplaceRender(box, context, null); grow();
  mediaReplaceRefresh = refresh;
  await refresh();
}
