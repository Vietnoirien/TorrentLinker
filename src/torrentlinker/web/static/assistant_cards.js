/* Persisted selection presentations. Opening details never starts a model turn. */
const assistantPresentationPages = new Map(), assistantPresentationOffsets = new Map();
const aCardKinds = {
  movie: ["Film", "Film"], series: ["Series", "Série"], ebook: ["Book", "Livre"],
  comic: ["Comic", "BD"], music: ["Music", "Musique"], game: ["Game", "Jeu"],
  software: ["Software", "Logiciel"], model3d: ["3D model", "Modèle 3D"], other: ["Content", "Contenu"]
};
function aCardArtwork(item, large = false) {
  const art = element("div", undefined, "selection-artwork" + (large ? " large" : ""));
  art.dataset.kind = item.kind;
  const label = at(...(aCardKinds[item.kind] || aCardKinds.other));
  art.append(element("span", label));
  if (item.image_url && /^https?:\/\//i.test(item.image_url)) {
    const img = element("img");
    img.alt = item.content_title || item.title;
    img.loading = "lazy"; img.decoding = "async"; img.referrerPolicy = "no-referrer";
    img.src = "api/assistant/image?url=" + encodeURIComponent(item.image_url);
    img.addEventListener("load", () => art.querySelector("span")?.remove(), {once: true});
    img.addEventListener("error", () => img.remove(), {once: true});
    art.append(img);
  }
  return art;
}
function aCardSize(item) {
  const size = item.size_bytes == null ? at("Unknown size", "Taille inconnue") : bytes(item.size_bytes);
  return item.presentation_type === "upload_drafts" ? size : size + " · " + (item.seeders ?? "—") + " sources";
}
function aUploadSummary(item) {
  const states = {queued: at("Awaiting review", "À relire"), sending: at("Sending to c411", "Envoi vers c411"),
    sent: at("Sent to c411", "Envoyé à c411"), uncertain: at("Check c411 before retrying", "Vérifiez c411 avant de réessayer")};
  const status = states[(item.draft_changed ? item.saved_status : item.current_status) || item.saved_status] || at("Saved draft", "Brouillon enregistré");
  let text = `${at("Upload draft", "Brouillon Upload")} · ${at("revision", "révision")} ${item.draft_revision} · ${status}`;
  text += ` · ${item.review_summary?.refusals || 0} ${at("refusals", "refus")} · ${item.review_summary?.warnings || 0} ${at("warnings", "avertissements")}`;
  if (item.draft_deleted) text += " · " + at("Draft removed. Saved review snapshot.", "Brouillon supprimé. Copie de relecture enregistrée.");
  else if (item.draft_changed) text += " · " + at("Draft changed. Review the current revision before sending.", "Brouillon modifié. Relisez la révision actuelle avant l'envoi.");
  return element("span", text, "selection-upload-summary");
}
function aCardScores(item) {
  const value = (n, places) => typeof n === "number" && Number.isFinite(n) ? n.toFixed(places) : "—";
  const label = element("span",
    `Note ${value(item.torrent_note, 2)} · ≈ ${value(item.estimated_zen_per_day, 3)} ${at("Zen/day", "Zen/jour")}`,
    "selection-scores");
  label.title = item.zen_assumptions || "";
  return label;
}
async function aPresentationItem(identifier, itemId) {
  return aCardDetail(() => api(`assistant/presentations/${encodeURIComponent(identifier)}/items/${encodeURIComponent(itemId)}`));
}
async function aCardDetail(load) {
  const {dialog, form} = aDialog(at("Selection details", "Détails de la sélection"));
  dialog.classList.add("selection-detail");
  const body = element("div", at("Loading details…", "Chargement des détails…"));
  form.append(body, button(at("Close", "Fermer"), () => dialog.close()));
  try {
    const item = await load();
    if (!dialog.isConnected) return;
    if (item.presentation_type === "upload_drafts") form.querySelector("h2").textContent = at("Upload draft review", "Relecture du brouillon Upload");
    body.replaceChildren(element("h3", item.content_title || item.title));
    const header = element("div", undefined, "selection-detail-header"), info = element("div");
    info.append(element("p", item.title, "selection-release"), element("p", aCardSize(item), "muted"));
    info.append(item.presentation_type === "upload_drafts" ? aUploadSummary(item) : aCardScores(item));
    if (item.zen_assumptions) info.append(element("p", item.zen_assumptions, "muted"));
    const facts = element("dl", undefined, "selection-facts");
    for (const [name, value] of Object.entries(item.facts || {})) facts.append(element("dt", name), element("dd", String(value)));
    info.append(facts);
    if (item.note) info.append(element("p", item.note));
    header.append(aCardArtwork(item, true), info); body.append(header);
    const description = element("div", undefined, "selection-description");
    // Server returns sanitized Indexer HTML, never model-generated HTML. Keep only
    // description formatting here; artwork always uses the authenticated proxy.
    if (item.description_html) {
      const template = document.createElement("template");
      template.innerHTML = item.description_html;
      const allowed = new Set(["P", "DIV", "SPAN", "B", "STRONG", "I", "EM", "U", "S", "BR", "HR",
        "H1", "H2", "H3", "H4", "PRE", "CODE", "BLOCKQUOTE", "UL", "OL", "LI",
        "TABLE", "THEAD", "TBODY", "TR", "TD", "TH", "A"]);
      for (const node of template.content.querySelectorAll("*")) {
        if (!allowed.has(node.tagName)) { node.remove(); continue; }
        const href = node.tagName === "A" ? node.getAttribute("href") : "";
        for (const attr of [...node.attributes]) node.removeAttribute(attr.name);
        if (href && /^https?:\/\//i.test(href)) {
          node.href = href; node.target = "_blank"; node.rel = "noopener noreferrer";
        }
      }
      description.append(template.content);
    } else description.textContent = item.description || at("No description available.", "Aucune description disponible.");
    body.append(description);
    if (item.presentation_type === "upload_drafts") {
      body.append(element("p", at("Reviewing these cards does not approve or send the draft.", "Consulter ces fiches ne valide ni n'envoie le brouillon.")));
      const review = item.upload_review || {};
      for (const [title, text] of [
        ["NFO", item.nfo || ""],
        [at("Files", "Fichiers"), (item.files || []).map(file => `${file.path} · ${bytes(file.size)}`).join("\n")],
        [at("Category options", "Options de catégorie"), JSON.stringify(item.upload_form?.options || {}, null, 2)],
        [at("Refusals", "Refus"), (review.refusals || []).join("\n")],
        [at("Warnings", "Avertissements"), (review.warnings || []).join("\n")],
      ]) {
        const details = element("details"), pre = element("pre", text);
        pre.style.whiteSpace = "pre-wrap";
        details.append(element("summary", title), pre); body.append(details);
      }
    }
    if (/^https?:\/\//i.test(item.source_url || "")) {
      const link = element("a", at("Open source", "Ouvrir la source"));
      link.href = item.source_url; link.target = "_blank"; link.rel = "noopener noreferrer";
      body.append(link);
    }
  } catch (error) {
    if (dialog.isConnected) { body.textContent = error.message; body.classList.add("error"); }
  }
}
function aSelectionCards(identifier) {
  const section = element("section", undefined, "selection-presentation");
  section.setAttribute("aria-label", at("Saved selection", "Sélection enregistrée"));
  const title = element("h3", at("Loading selection…", "Chargement de la sélection…"));
  const status = element("p", "", "muted"), grid = element("div", undefined, "selection-grid");
  const footer = element("div", undefined, "selection-pagination");
  let offset = assistantPresentationOffsets.get(identifier) || 0, nextOffset = null;
  const previous = button(at("Previous", "Précédent"), () => load(Math.max(0, offset - 12)));
  const next = button(at("Next", "Suivant"), () => load(nextOffset));
  footer.append(previous, next); section.append(title, status, grid, footer);
  async function load(position) {
    offset = position; assistantPresentationOffsets.set(identifier, offset);
    previous.disabled = next.disabled = true;
    status.textContent = at("Loading…", "Chargement…");
    const key = identifier + ":" + offset;
    try {
      if (!assistantPresentationPages.has(key)) {
        const promise = api(`assistant/presentations/${encodeURIComponent(identifier)}?offset=${offset}&limit=12`);
        assistantPresentationPages.set(key, promise);
        promise.catch(() => assistantPresentationPages.delete(key));
        if (assistantPresentationPages.size > 64) assistantPresentationPages.delete(assistantPresentationPages.keys().next().value);
      }
      const page = await assistantPresentationPages.get(key);
      if (!section.isConnected || offset !== position) return;
      title.textContent = page.title;
      if (page.presentation_type === "upload_drafts") assistantPresentationPages.delete(key);
      status.textContent = `${page.items.length ? offset + 1 : 0}–${offset + page.items.length} / ${page.count} · ${page.presentation_type === "upload_drafts" ? at("saved Upload drafts", "brouillons Upload enregistrés") : at("saved revision", "révision enregistrée") + " " + (page.revision ?? "")}`;
      grid.replaceChildren();
      for (const item of page.items) {
        const card = button("", () => aPresentationItem(identifier, item.item_id), "selection-card");
        card.dataset.kind = item.kind;
        card.setAttribute("aria-label", item.content_title || item.title);
        card.append(aCardArtwork(item), element("strong", item.content_title || item.title));
        if (item.subtitle) card.append(element("span", item.subtitle, "muted"));
        card.append(element("span", aCardSize(item), "selection-size"),
          item.presentation_type === "upload_drafts" ? aUploadSummary(item) : aCardScores(item));
        if (item.note) card.append(element("span", item.note, "selection-note"));
        grid.append(card);
      }
      nextOffset = page.next_offset;
      previous.disabled = offset === 0; next.disabled = !page.has_more;
    } catch (error) {
      if (section.isConnected) { status.textContent = error.message; previous.disabled = offset === 0; }
    }
  }
  // Defer until aRunCard has attached the section to the document.
  queueMicrotask(() => load(offset));
  return section;
}
