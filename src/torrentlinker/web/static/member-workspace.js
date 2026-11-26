"use strict";
async function loadMemberWorkspace(view) {
  const root = $(`view-${view}`), kind = view.replace("member-", "");
  root.replaceChildren(requestNode("h2", kind === "queue" ? say("My queue", "Ma file") : say("My downloads", "Mes téléchargements")));
  const results = requestNode("div", undefined, "request-list");
  async function show() {
    const {rows} = await api(`member-workspace/${kind}`);
    results.replaceChildren();
    for (const row of rows) {
      const card = requestNode("section", undefined, "card");
      card.append(requestNode("strong", row.title || row.name), requestNode("p", `${requestBytes(row.size)} · ${requestState(row.state)}`));
      if (row.progress != null) { const progress = requestNode("progress"); progress.max = 1; progress.value = row.progress; progress.setAttribute("aria-label", say("Download progress", "Progression du téléchargement")); card.append(progress); }
      results.append(card);
    }
    if (!rows.length) results.append(requestNode("p", say("No matching items within your Permissions.", "Aucun élément correspondant à vos permissions.")));
  }
  await show();
  root.append(results);
}
