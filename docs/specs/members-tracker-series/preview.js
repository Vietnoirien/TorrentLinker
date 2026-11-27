"use strict";
/* Tracker Series preview, on the real page. A bar at the bottom switches the role (Propriétaire, Membre,
   Membre avec limite d'âge) and jumps to each screen; the screens themselves are the real ones.
   series.js (inside the Médias frame) adds the series; this file adds the bar and the Approver's series
   inspector on the real Demandes page. */
(() => {
  const API = "/api/tracker-series-preview";
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const frame = () => document.getElementById("media-frame");
  const ROLES = [["owner", "Propriétaire"], ["member", "Membre"], ["limited", "Membre avec limite d'âge (−12)"]];
  let role = "owner";

  async function media(work) {
    if (!location.hash.startsWith("#/media")) await navigate("media");
    for (let i = 0; i < 80; i++) {
      const w = frame()?.contentWindow;
      if (w?.TSPreview?.series.length && !frame().contentDocument.getElementById("view-media")?.inert) return work(w.TSPreview, w);
      await sleep(150);
    }
    throw Error("Médias n'a pas fini de charger");
  }
  const roleName = () => ROLES.find(r => r[0] === role)[1];
  async function setRole(next) {
    role = next;
    for (const b of document.querySelectorAll("#ts-bar [data-role]")) b.classList.toggle("on", b.dataset.role === role);
    await media(ts => ts.setRole(role));
  }
  const bar = document.createElement("div");
  bar.id = "ts-bar";
  const group = (...nodes) => { const g = document.createElement("span"); g.className = "ts-group"; g.append(...nodes); return g; };
  const label = text => { const s = document.createElement("span"); s.textContent = text; s.style.opacity = ".7"; return s; };
  const btn = (text, run, extra = {}) => {
    const b = document.createElement("button"); b.type = "button"; b.textContent = text;
    Object.assign(b.dataset, extra);
    b.onclick = async () => { b.disabled = true; try { await run(); } catch (e) { console.error(e); alert(e.message); } finally { b.disabled = false; } };
    return b;
  };
  const SEVERANCE = "tv-95396", BEAR = "tv-136315", LAST = "tv-100088", BREAKING = "tv-1396";
  const body = document.createElement("span");
  body.className = "ts-body ts-group";
  body.append(
    label("Rôle"), group(...ROLES.map(([id, text]) => btn(text, () => setRole(id), {role: id}))),
    label("·"), label("Écrans"),
    group(
      btn("Séries", () => media(ts => ts.go("series"))),
      btn("Animés", () => media(ts => ts.go("anime"))),
      btn("Tout voir", () => media(ts => ts.seeAll("series"))),
      btn("Grille Drame", () => media(ts => ts.grid("Drame"))),
      btn("Fiche", () => media(async ts => { await ts.panel(SEVERANCE); await ts.seasons(1); })),
      btn("Fiche partielle", () => media(async ts => { await ts.panel(BEAR); })),
      btn("Épisodes", () => media(async ts => { await ts.panel(SEVERANCE); await ts.seasons(1); await ts.seasons(2); })),
      btn("Demander", () => media(async ts => { await ts.panel(role === "owner" ? BEAR : LAST); ts.sheet(); })),
      btn("Demandes (approbateur)", async () => { await navigate("requests"); }),
      btn("Réglages · membres", async () => {
        await navigate("setup", "users");
        for (let i = 0; i < 40; i++) {
          const doc = document.querySelector('iframe[src*="settings/view.html"]')?.contentDocument;
          const buttons = [...(doc?.querySelectorAll("button") || [])];
          const users = buttons.find(b => b.textContent.trim() === "Utilisateurs");
          if (users && !doc.querySelector(".member-card")) users.click();
          const edit = buttons.find(b => b.textContent.trim() === "Modifier");
          if (edit) { edit.click(); await sleep(400); [...doc.querySelectorAll("label")].find(l => /^Films (et séries|and series)/.test(l.textContent.trim()))?.scrollIntoView({block: "center"}); return; }
          await sleep(250);
        }
      }),
      btn("Réinitialiser", async () => { await fetch(`${API}/reset`, {method: "POST", body: "{}"}); await setRole(role); }),
    ),
  );
  const title = document.createElement("b"); title.className = "ts-title"; title.textContent = "Aperçu";
  title.style.cursor = "pointer"; title.onclick = () => bar.classList.toggle("min");
  bar.append(title, body);
  addEventListener("DOMContentLoaded", () => { document.body.append(bar); bar.querySelector(`[data-role="owner"]`).classList.add("on"); });

  // The list's small line says what a series Request asks, in place of the film wording.
  const originalRender = renderRequests;
  renderRequests = function () {
    originalRender();
    for (const row of document.querySelectorAll("#view-requests .request-row")) {
      const found = requestReview.rows.find(r => r.series && `${r.title} ${r.year}` === row.querySelector("strong")?.textContent);
      if (found) row.querySelector("span").textContent = row.querySelector("span").textContent.replace(" · ReleaseScore ?", "");
      if (found) row.querySelector("small").textContent = `Série · ${found.series.asked.length === found.series.seasons ? "toute la série" : `saison${found.series.asked.length > 1 ? "s" : ""} ${found.series.asked.map(a => a.n).join(", ")}`} · vous choisissez les packs`;
    }
  };

  // ---- the Approver's inspector for a series Request, on the real Demandes page -----------------
  const originalInspector = requestInspector;
  requestInspector = function (panel, row) {
    if (!row.series) return originalInspector(panel, row);
    const s = row.series, pending = row.state === "pending", integ = s.integrale;
    const ranges = list => {
      const out = [];
      for (const n of [...list].sort((a, b) => a - b)) out.length && out[out.length - 1][1] === n - 1 ? out[out.length - 1][1] = n : out.push([n, n]);
      return out.map(([a, b]) => a === b ? String(a) : `${a}–${b}`).join(", ");
    };
    const title = requestNode("h3", `${row.title} ${row.year}`); title.append(requestNode("span", "Aperçu", "ts-preview"));
    panel.append(title, requestNode("p", `${row.requester} · ${requestState(row.state)}`));
    const cover = requestNode("img", undefined, "request-cover"); cover.alt = ""; cover.src = s.poster; cover.onerror = () => cover.remove();
    panel.append(cover);
    const asked = s.asked.map(a => a.n);
    panel.append(requestNode("p", `${say("Asked", "Demandé")} : ${asked.length === s.seasons ? "toute la série" : `saison${asked.length > 1 ? "s" : ""} ${ranges(asked)}`}${s.follow ? " · suit la série (chaque nouvelle saison complète crée une demande)" : ""}`));
    const onlyIntegrale = s.asked.some(a => a.state === "integ");
    const covers = integ && asked.every(n => integ.seasons.includes(n));
    let useIntegrale = pending ? s.pre.length === 1 && !!integ && s.pre[0] === integ.release.hash : false;
    const picks = new Map(), radios = [];
    for (const a of s.asked) picks.set(a.n, a.releases.find(r => s.pre.includes(r.hash))?.hash || [...a.releases].sort((x, y) => y.score - x.score)[0]?.hash || "");
    const margin = requestNode("div"), warn = requestNode("p", "", "field-error");
    const chosen = () => useIntegrale ? [integ.release.hash] : s.asked.map(a => picks.get(a.n)).filter(Boolean);
    const sizeOf = hash => (integ && integ.release.hash === hash ? integ.release : s.asked.flatMap(a => a.releases).find(r => r.hash === hash))?.size || 0;
    const total = () => chosen().reduce((a, h) => a + sizeOf(h), 0);
    const update = () => {
      margin.replaceChildren(requestMargin(total(), row.size || 0));
      const cap = row.approval_limits || {};
      warn.textContent = cap.bytes_left != null && total() > cap.bytes_left ? say("Accepting exceeds this Member's weekly quota. The override will be recorded.", "Cette acceptation dépasse le quota hebdomadaire du membre. Le dépassement sera consigné.") : "";
      for (const r of radios) r.disabled = !pending || useIntegrale;
      for (const f of panel.querySelectorAll(".ts-pick")) f.classList.toggle("off", useIntegrale);
    };
    if (pending) {
      const note = requestNode("p", `Pré-sélection : ${useIntegrale ? `l'Intégrale (saisons ${ranges(integ.seasons)}), meilleure que les packs` : "le meilleur pack de chaque saison"}. Vous pouvez changer.`, "request-description");
      panel.append(note);
      if (integ && covers) {
        const toggle = requestNode("label", undefined, "ts-integ-toggle"), box = requestNode("input"); box.type = "checkbox"; box.checked = useIntegrale; box.disabled = onlyIntegrale;
        toggle.append(box, requestNode("span", `Utiliser l'Intégrale (saisons ${ranges(integ.seasons)}) : ${requestBytes(integ.release.size)} · ReleaseScore ${integ.release.score}${onlyIntegrale ? " · seule source de certaines saisons demandées" : ""}`));
        box.onchange = () => { useIntegrale = box.checked; update(); };
        panel.append(toggle);
      }
    }
    for (const a of s.asked) {
      const set = requestNode("fieldset", undefined, "ts-pick");
      set.append(requestNode("legend", `Saison ${a.n} · ${a.count} épisodes`));
      if (a.state === "integ") set.append(requestNode("p", "Seulement dans l'Intégrale.", "request-description"));
      for (const r of a.releases) {
        const l = requestNode("label"), i = requestNode("input"); i.type = "radio"; i.name = `${row.id}-${a.n}`; i.checked = picks.get(a.n) === r.hash; radios.push(i);
        i.onchange = () => { picks.set(a.n, r.hash); update(); };
        l.append(i, requestNode("span", `${r.name} · ${r.tracker} · ${requestBytes(r.size)} · ${r.seeders} ${say("seeders", "sources")} · ReleaseScore ${r.score}${s.pre.includes(r.hash) ? " · pré-sélection" : ""}`));
        set.append(l);
      }
      if (a.state === "integ" || a.releases.length) panel.append(set);
    }
    panel.append(requestNode("p", `${say("Quoted to the Members", "Annoncé aux membres")} : ${requestBytes(row.quoted)}`), warn);
    update(); panel.append(margin);
    const quota = row.quota;
    panel.append(requestNode("p", `${say("Weekly quota remaining", "Quota hebdomadaire restant")} : ${quota.requests_left ?? "∞"} · ${quota.bytes_left == null ? "∞" : requestBytes(quota.bytes_left)}`));
    const timeline = requestNode("ol"); for (const event of row.events) timeline.append(requestNode("li", `${new Date(event.at * 1000).toLocaleString()} · ${requestState(event.state)}${event.note ? ` · ${event.note}` : ""}`)); panel.append(timeline);
    const note = requestNode("textarea"); note.maxLength = 500; note.placeholder = say("Note for the Member", "Note pour le membre"); note.setAttribute("aria-label", note.placeholder);
    const error = requestNode("p", "", "field-error"); error.setAttribute("role", "alert");
    const actions = requestNode("div", undefined, "toolbar");
    const act = (text, path) => {
      const button = requestNode("button", text);
      button.onclick = async () => {
        for (const c of actions.children) c.disabled = true;
        try { await api(`requests/${row.id}/${path}`, {infohash: "", infohashes: path === "accept" ? chosen() : [], note: note.value}); await loadRequests(); }
        catch (failure) { error.textContent = failure.message; for (const c of actions.children) c.disabled = false; }
      };
      actions.append(button);
    };
    if (pending) { act(say("Accept", "Accepter"), "accept"); act(say("Refuse", "Refuser"), "refuse"); }
    panel.append(note, error, actions);
  };
})();
