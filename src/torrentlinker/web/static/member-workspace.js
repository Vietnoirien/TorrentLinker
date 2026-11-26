"use strict";
async function loadMemberWorkspace(view) {
  const root = $(`view-${view}`), kind = view.replace("member-", "");
  root.replaceChildren(requestNode("h2", kind === "search" ? say("Tracker search · read only", "Recherche c411 · consultation") : kind === "queue" ? say("My queue", "Ma file") : say("My downloads", "Mes téléchargements")));
  const results = requestNode("div", undefined, "request-list");
  async function show(query = "") {
    const {rows} = await api(`member-workspace/${kind}${kind === "search" ? `?q=${encodeURIComponent(query)}` : ""}`);
    results.replaceChildren();
    for (const row of rows) {
      const card = requestNode("section", undefined, "card");
      card.append(requestNode("strong", row.title || row.name), requestNode("p", kind === "search" ? [row.year, row.genre].filter(Boolean).join(" · ") : `${requestBytes(row.size)} · ${requestState(row.state)}`));
      if (row.progress != null) { const progress = requestNode("progress"); progress.max = 1; progress.value = row.progress; progress.setAttribute("aria-label", say("Download progress", "Progression du téléchargement")); card.append(progress); }
      if (kind === "search" && state.actor?.permissions?.includes("request")) {
        const request = requestNode("button", say("Request", "Demander"));
        request.onclick = async () => {request.disabled = true; try {await api("requests", {film: row.film}); request.textContent = say("Requested", "Demandée");} catch (error) {request.disabled = false; toast(error.message, "bad");} };
        card.append(request);
      }
      results.append(card);
    }
    if (!rows.length) results.append(requestNode("p", say("No matching items within your Permissions.", "Aucun élément correspondant à vos permissions.")));
  }
  if (kind === "search") {
    const form = requestNode("form", undefined, "toolbar"), input = requestNode("input"); input.type = "search"; input.maxLength = 200; input.required = true; input.setAttribute("aria-label", say("Film title", "Titre du film"));
    const search = requestNode("button", say("Search", "Rechercher")); search.type = "submit";
    form.onsubmit = async event => {event.preventDefault(); search.disabled = true; try {await show(input.value);} catch (error) {toast(error.message, "bad");} finally {search.disabled = false;} };
    form.append(input, search); root.append(form);
  } else await show();
  root.append(results);
}
