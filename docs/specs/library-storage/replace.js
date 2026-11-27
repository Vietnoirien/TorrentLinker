"use strict";
// Preview "Remplacer": the Télécharger button of a better version offers to replace the old one.
// The real Médias and Torrents pages are drawn by the app; this file adds the marked change to them.
(() => {
  const BASE = LSPreview.BASE;
  const DOWNLOAD_FOLDER = { path: "/library/Téléchargements", disk: "/library", free: 12700 };
  const S = {
    fixture: null, member: false, rev: 0, runs: {},
    // The "Fin du partage" rule: time and/or ratio, "l'un ou l'autre" or "les deux".
    rule: { useTime: true, amount: 7, unit: "d", useRatio: true, ratio: 1, combine: "any" },
    replace: false, wait: true,
  };
  const num = n => String(n).replace(".", ",");
  const size = gb => `${num(gb)} Go`;
  const free = gb => gb >= 1000 ? `${num((gb / 1000).toFixed(1))} To` : `${gb} Go`;
  function ruleText() {
    const r = S.rule, parts = [];
    if (r.useTime) parts.push(`${r.amount} ${r.unit === "d" ? "j" : "h"}`);
    if (r.useRatio) parts.push(`ratio ${num(r.ratio)}`);
    if (!parts.length) return "sans attente";
    return parts.length === 2 ? parts.join(r.combine === "all" ? " et " : " ou ") : parts[0];
  }
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const mediaDoc = () => document.getElementById("media-frame")?.contentDocument;
  const torrentsDoc = () => document.getElementById("torrents-frame")?.contentDocument;
  const oldSeeds = film => !!film.old.seed;
  const fallback = film => film.free < film.upgrade.size;

  function stepsFor(run, film) {
    const list = [["send", "Envoyée au client"], ["download", "Téléchargement de la nouvelle version"],
      ["done", "Terminé : la nouvelle version joue, votre état de lecture est conservé"]];
    if (run.replace && run.wait && oldSeeds(film))
      list.push(["fin", `Ancienne version en fin de partage (règle : ${ruleText()}) : cachée de Médias, visible dans Torrents`]);
    if (run.replace) list.push(["trash", "Ancienne version retirée du client, ses fichiers à la corbeille (restaurables 7 jours)"]);
    return list;
  }

  function card(title, film, doc) {
    const run = S.runs[title], started = !!run;
    const replace = started ? run.replace : S.replace, wait = started ? run.wait : S.wait;
    const seeds = oldSeeds(film), up = film.upgrade;
    const seedText = seeds ? `en partage · ${film.old.seed.hours} h · ratio ${num(film.old.seed.ratio)}` : "ne partage plus";
    const dest = fallback(film)
      ? `<p class="rp-dest warn">Pas assez de place sur ${film.disk} (${free(film.free)} libres, ${size(up.size)} nécessaires) : la nouvelle version ira dans le Dossier de téléchargement, <b>${DOWNLOAD_FOLDER.path}</b> · ${DOWNLOAD_FOLDER.disk} · ${free(DOWNLOAD_FOLDER.free)} libres.</p>`
      : `<p class="rp-dest">La nouvelle version se télécharge à côté de l'ancienne : <b>${esc(film.folder)}</b> · ${film.disk} · ${free(film.free)} libres.</p>`;
    const toggle = (id, on, label, hint, disabled) =>
      `<div class="rp-toggle" role="switch" tabindex="0" data-toggle="${id}" aria-checked="${on}" aria-disabled="${disabled}"><span class="rp-switch"></span><span>${label}<small>${hint}</small></span></div>`;
    let html = `<header><span class="rp-badge-preview">Aperçu</span>Remplacer l'ancienne version</header>
      <div class="rp-compare">
        <div class="rp-version"><b>Dans votre médiathèque</b><span class="name">${esc(film.old.name)}</span>
          <small>${size(film.old.size)} · ReleaseScore <span class="rp-score low">${film.oldScore ?? "?"}</span></small>
          <small class="rp-seed ${seeds ? "" : "off"}"><i></i>${seedText}</small></div>
        <span class="rp-arrow">→</span>
        <div class="rp-version new"><b>Sur le tracker</b><span class="name">${esc(up.name)}</span>
          <small>${size(up.size)} · ReleaseScore <span class="rp-score">${film.newScore ?? "?"}</span></small></div>
      </div>${dest}<div class="rp-toggles">`;
    html += toggle("replace", replace, "Remplacer l'ancienne version",
      seeds ? "Quand la nouvelle est complète, l'ancienne quitte Médias puis part à la corbeille." : "Elle ne partage plus : elle part à la corbeille dès que la nouvelle est complète.", started);
    if (seeds) {
      html += toggle("wait", replace && wait, "Attendre la fin de son partage",
        `Règle : ${ruleText()} · <button type="button" class="rp-link" data-rule>Modifier</button>`, started || !replace);
    }
    html += "</div>";
    if (started) {
      const list = stepsFor(run, film);
      html += `<div class="rp-timeline">${list.map(([key, text], i) => {
        const cls = i < run.step ? "done" : i === run.step ? "now" : "";
        let extra = "";
        if (key === "download" && i === run.step) extra = `<div class="rp-bar"><i style="width:${run.progress}%"></i></div>`;
        if (key === "fin" && i === run.step) extra = ` <button type="button" class="rp-link" data-torrents>Voir dans Torrents</button>`;
        if (key === "trash" && i <= run.step) extra = run.restored
          ? " <i>Restaurée : ses fichiers sont revenus dans le dossier.</i>"
          : ` <button type="button" class="rp-link" data-restore>Restaurer</button>`;
        return `<div class="rp-step ${cls}"><b>${i < run.step ? "✓" : i === run.step ? "●" : "○"}</b><span>${text}${extra}</span></div>`;
      }).join("")}</div>`;
      if (run.step >= list.length) html += `<p class="rp-note">Terminé.</p>`;
    }
    return html;
  }

  function ruleDialog(doc) {
    const d = doc.createElement("dialog");
    d.className = "rp-dialog";
    const r = S.rule;
    d.innerHTML = `<h2>Fin du partage</h2><p>Quand l'ancienne version, remplacée, a fini son partage et peut être retirée.</p>
      <label class="rule"><input type="checkbox" id="rp-use-time" ${r.useTime ? "checked" : ""}> Partagée au moins
        <input type="number" id="rp-amount" min="1" step="1" value="${r.amount}">
        <select id="rp-unit"><option value="h" ${r.unit === "h" ? "selected" : ""}>heures</option><option value="d" ${r.unit === "d" ? "selected" : ""}>jours</option></select></label>
      <label class="rule"><input type="checkbox" id="rp-use-ratio" ${r.useRatio ? "checked" : ""}> Ratio d'au moins
        <input type="number" id="rp-ratio" min="0.1" step="0.1" value="${r.ratio}"></label>
      <div class="combine" id="rp-combine-row">Il faut <select id="rp-combine"><option value="any" ${r.combine === "any" ? "selected" : ""}>l'un ou l'autre</option><option value="all" ${r.combine === "all" ? "selected" : ""}>les deux</option></select></div>
      <p id="rp-none" hidden>Aucune condition cochée : l'ancienne version est retirée dès que la nouvelle est complète.</p>
      <div class="actions"><button type="button" id="rp-cancel">Annuler</button><button type="button" class="primary" id="rp-save">Enregistrer</button></div>`;
    const $ = id => d.querySelector("#" + id);
    const sync = () => {
      const both = $("rp-use-time").checked && $("rp-use-ratio").checked;
      $("rp-combine-row").hidden = !both;
      $("rp-none").hidden = $("rp-use-time").checked || $("rp-use-ratio").checked;
    };
    d.addEventListener("change", sync); sync();
    $("rp-cancel").onclick = () => d.close();
    $("rp-save").onclick = () => {
      S.rule = { useTime: $("rp-use-time").checked, amount: Math.max(1, +$("rp-amount").value || 1), unit: $("rp-unit").value,
        useRatio: $("rp-use-ratio").checked, ratio: Math.max(0.1, +$("rp-ratio").value || 1), combine: $("rp-combine").value };
      S.rev++; d.close();
    };
    d.addEventListener("close", () => d.remove());
    doc.body.append(d);
    d.showModal();
  }

  function start(title) {
    if (S.runs[title]) return;
    S.runs[title] = { replace: S.replace, wait: S.replace && S.wait, step: 1, progress: 0, restored: false };
    S.rev++; status();
  }
  function advance() {
    const title = S.title;
    const run = S.runs[title], film = S.fixture?.films[title];
    if (!run) { toast("Cliquez d'abord sur Télécharger."); return; }
    const list = stepsFor(run, film);
    if (run.step >= list.length) return;
    if (list[run.step][0] === "download") {
      run.progress = Math.min(100, run.progress + 34);
      if (run.progress >= 100) run.step++;
    } else run.step++;
    S.rev++; status();
  }
  function toast(text) { const s = document.querySelector("#ls-bar .ls-state"); if (s) s.textContent = text; }

  function enhanceMedia() {
    const doc = mediaDoc();
    if (!doc || !S.fixture) return;
    if (!doc.getElementById("rp-style")) {
      const link = doc.createElement("link");
      link.id = "rp-style"; link.rel = "stylesheet"; link.href = BASE + "replace.css";
      doc.head.append(link);
    }
    const content = doc.querySelector(".media-feature-content");
    if (!content) return;
    const title = content.querySelector("h2")?.textContent.trim();
    S.title = title;
    const film = S.fixture.films[title];
    const actions = content.querySelector(".media-feature-actions");
    const view = doc.getElementById("view-media");
    if (!film?.upgrade || !actions || !content.querySelector(".media-tracker-release")) { view?.style.removeProperty("--media-banner-height"); return; }
    // The scores the real hero shows: the tracker release's, and "Votre fichier obtient N".
    const pill = content.querySelector(".media-tracker-release .media-score")?.textContent;
    const own = /obtient (\d+)/.exec(content.querySelector(".media-tracker-release")?.textContent || "")?.[1];
    film.newScore = pill; film.oldScore = own;
    const key = `${title}|${S.rev}|${S.member}|${JSON.stringify(S.runs[title] || 0)}|${S.replace}${S.wait}`;
    if (!actions.dataset.rp) {
      actions.dataset.rp = "1";
      // Télécharger starts the preview flow instead of queueing a real download.
      actions.addEventListener("click", event => {
        const button = event.target.closest(".media-primary");
        if (!button) return;
        event.stopImmediatePropagation(); event.preventDefault();
        start(title);
      }, true);
    }
    const primary = actions.querySelector(".media-primary");
    if (primary && S.runs[title]) { primary.textContent = "Envoyée"; primary.disabled = true; }
    else if (primary?.disabled && primary.textContent === "Envoyée") { primary.textContent = "Télécharger"; primary.disabled = false; }
    let box = content.querySelector(".rp-card");
    if (box && box.dataset.key === key) { grow(view, box); return; }
    box?.remove();
    box = doc.createElement("div");
    box.className = "rp-card"; box.dataset.key = key;
    if (S.member) {
      box.innerHTML = `<header><span class="rp-badge-preview">Aperçu</span>Vue membre</header><p class="rp-note" style="margin:0">Le remplacement d'une version est réservé au propriétaire : un membre ne voit aucune option ici.</p>`;
    } else {
      box.innerHTML = card(title, film, doc);
      box.addEventListener("click", event => {
        if (event.target.closest("[data-rule]")) { event.stopPropagation(); return ruleDialog(doc); }
        if (event.target.closest("[data-torrents]")) return LSPreview.go("#/torrents");
        if (event.target.closest("[data-restore]")) { S.runs[title].restored = true; S.rev++; return; }
        const toggle = event.target.closest("[data-toggle]");
        if (!toggle || toggle.getAttribute("aria-disabled") === "true") return;
        if (toggle.dataset.toggle === "replace") S.replace = !S.replace; else S.wait = !S.wait;
        S.rev++;
      });
      box.addEventListener("keydown", event => {
        if ((event.key === " " || event.key === "Enter") && event.target.closest("[data-toggle]")) { event.preventDefault(); event.target.click(); }
      });
    }
    actions.after(box);
    grow(view, box);
  }
  // The banner is a fixed 380 px; the preview card makes it as tall as it needs.
  function grow(view, box) { view?.style.setProperty("--media-banner-height", `${380 + Math.ceil(box.getBoundingClientRect().height) + 16}px`); }

  function enhanceTorrents() {
    const doc = torrentsDoc();
    if (!doc || !S.fixture) return;
    if (!doc.getElementById("rp-style")) {
      const link = doc.createElement("link");
      link.id = "rp-style"; link.rel = "stylesheet"; link.href = BASE + "replace.css";
      doc.head.append(link);
    }
    for (const [title, run] of Object.entries(S.runs)) {
      const film = S.fixture.films[title];
      const list = stepsFor(run, film), now = list[run.step]?.[0];
      const removed = run.replace && (now === "trash" || run.step >= list.length);
      const waiting = now === "fin";
      for (const row of doc.querySelectorAll("tbody tr")) {
        const link = row.querySelector("button.link");
        if (!link || link.textContent.trim() !== film.old.name) continue;
        row.style.display = removed ? "none" : "";
        let badge = row.querySelector(".rp-fin-badge");
        if (!waiting) { badge?.remove(); continue; }
        const text = `en fin de partage · règle : ${ruleText()}`;
        if (!badge) {
          badge = doc.createElement("span"); badge.className = "rp-fin-badge";
          row.querySelector(".name small")?.append(badge);
        }
        if (badge.textContent !== text) badge.textContent = text;
      }
    }
  }

  function status() {
    const el = document.querySelector("#ls-bar .ls-state");
    if (!el) return;
    const title = S.title, run = S.runs[title], film = S.fixture?.films[title];
    el.textContent = !film?.upgrade ? "Ouvrez une affiche de « Meilleures versions sur le tracker »"
      : !run ? `${title} : pas encore envoyée` : `${title} : ${stepsFor(run, film)[run.step]?.[1] || "terminé"}`;
  }

  async function select(title) {
    S.member = false; S.rev++;
    if (!/^#\/media/.test(location.hash)) LSPreview.go("#/media");
    for (let i = 0; i < 60; i++) {
      const doc = mediaDoc();
      const rows = doc ? [...doc.querySelectorAll(".media-home-row")] : [];
      const row = rows.find(r => /Meilleures versions/.test(r.textContent));
      const cardNode = row && [...row.querySelectorAll(".media-row-card")].find(c => c.textContent.includes(title));
      if (cardNode) { cardNode.scrollIntoView({ block: "nearest", inline: "center" }); cardNode.click(); break; }
      await new Promise(r => setTimeout(r, 250));
    }
  }

  let timer = 0;
  LSPreview.register({
    id: "replace", label: "Remplacer",
    controls(box) {
      const add = (label, on) => { const b = document.createElement("button"); b.type = "button"; b.textContent = label; b.onclick = () => on(b); box.append(b); return b; };
      const sep = () => { const s = document.createElement("span"); s.className = "ls-sep"; box.append(s); };
      add("En partage", () => select("The Truman Show"));
      add("Sans partage", () => select("Kung Fu Jungle"));
      add("Disque presque plein", () => select("Prédestination"));
      const member = add("Vue membre", b => { S.member = !S.member; S.rev++; b.classList.toggle("on", S.member); });
      sep();
      add("Avancer ▸", advance);
      add("Recommencer", () => { S.runs = {}; S.rev++; status(); });
      sep();
      add("Médias", () => LSPreview.go("#/media"));
      add("Torrents", () => LSPreview.go("#/torrents"));
      const state = document.createElement("span"); state.className = "ls-state"; box.append(state);
      status();
    },
    activate() {
      fetch(BASE + "fixture.json").then(r => r.json()).then(f => { S.fixture = f; });
      timer = setInterval(() => { try { enhanceMedia(); enhanceTorrents(); status(); } catch (e) { console.error(e); } }, 400);
    },
    deactivate() { clearInterval(timer); },
  });
})();
