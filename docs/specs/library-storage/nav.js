"use strict";
// Navigation change shared by the new screens: "File de téléchargement" leaves the sidebar and becomes a tab of Recherche
// (the real queue page, hosted by the real Recherche panel); a new "Fichiers" entry takes its place and opens a new panel page.
// Everything else on screen is the real app; this file only edits what the real shell frames draw.
(() => {
  const BASE = LSPreview.BASE;
  const $ = id => document.getElementById(id);
  let started = 0, filesActive = false, pendingTab = "explorer";
  const doc = id => { try { return $(id)?.contentDocument || null; } catch { return null; } };
  function addCss(d, id) {
    if (!d || d.getElementById(id) || !d.head) return;
    const l = d.createElement("link"); l.id = id; l.rel = "stylesheet"; l.href = BASE + "preview.css"; d.head.append(l);
  }
  function createView() {
    if ($("view-ls-files")) return;
    const s = document.createElement("section");
    s.id = "view-ls-files"; s.className = "view"; s.hidden = true;
    const f = document.createElement("iframe");
    f.id = "ls-files-frame"; f.title = "Fichiers"; f.src = BASE + "fichiers.html";
    s.append(f);
    $("view-jobs").after(s);
    new MutationObserver(() => { if (s.hidden) filesActive = false; }).observe(s, { attributes: true, attributeFilter: ["hidden"] });
  }
  const viewState = () => (typeof state !== "undefined" ? state.view : "");
  function tick() {
    // Sidebar
    const nav = doc("shell-navigation-frame"), pages = nav?.getElementById("pages");
    if (pages?.children.length) {
      addCss(nav, "ls-css");
      const queue = pages.querySelector('[data-view="queue"]');
      if (queue) queue.style.display = "none";
      let files = pages.querySelector('[data-ls="files"]');
      if (!files) {
        files = nav.createElement("button");
        files.type = "button"; files.dataset.ls = "files";
        files.innerHTML = 'Fichiers <span class="ls-mini">Aperçu</span>';
        files.onclick = () => parent.LSNav.openFiles("explorer");
        (queue || pages.lastElementChild)?.before(files);
      }
      const current = filesActive ? files : pages.querySelector(`[data-view="${viewState() === "queue" ? "search" : viewState()}"]`);
      for (const b of pages.children) { if (b === current) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current"); }
    }
    // Header title
    const head = doc("shell-header-frame"), title = head?.getElementById("page-title");
    if (title) {
      const desc = head.getElementById("page-description");
      if (filesActive) { title.textContent = "Fichiers"; desc.textContent = "Parcourez, déplacez et rangez vos fichiers sur tous vos disques, en gardant vos partages."; }
      else if (viewState() === "queue" && title.textContent !== "Recherche") { title.textContent = "Recherche"; desc.textContent = "Recherchez des torrents et ajoutez vos choix à la file de téléchargement."; }
    }
    // Recherche tabs
    const sd = doc("search-frame");
    if (sd?.getElementById("queue") && !sd.getElementById("ls-search-tabs")) {
      addCss(sd, "ls-css");
      const bar = sd.createElement("nav");
      bar.id = "ls-search-tabs"; bar.className = "ls-tabs";
      bar.innerHTML = '<button type="button" data-t="search">Recherche</button><button type="button" data-t="queue">File de téléchargement</button><span class="ls-mini">Aperçu</span>';
      bar.onclick = e => {
        const b = e.target.closest("button[data-t]");
        if (!b) return;
        const queue = !sd.getElementById("queue").hidden;
        if (b.dataset.t === "queue" && !queue) sd.getElementById("search-queue-link")?.click();
        if (b.dataset.t === "search" && queue) sd.getElementById("back-results")?.click();
      };
      sd.querySelector("main").prepend(bar);
    }
    const bar = sd?.getElementById("ls-search-tabs");
    if (bar) {
      const queue = !sd.getElementById("queue").hidden;
      bar.hidden = !!sd.getElementById("detail-pages") && !sd.getElementById("detail-pages").hidden;
      bar.querySelector('[data-t="search"]').classList.toggle("selected", !queue);
      bar.querySelector('[data-t="queue"]').classList.toggle("selected", queue);
    }
    // Fichiers theme
    const fd = doc("ls-files-frame");
    if (fd?.documentElement) fd.documentElement.dataset.theme = document.documentElement.dataset.theme || "dark";
  }
  window.LSNav = {
    ensure() { if (started) return; started = setInterval(() => { try { tick(); } catch (e) { console.error(e); } }, 250); createView(); tick(); },
    files() { try { return $("ls-files-frame")?.contentWindow?.FX || null; } catch { return null; } },
    async call(name, ...args) {
      for (let i = 0; i < 80; i++) { const fx = this.files(); if (fx?.api && fx.S?.data) return fx.api[name]?.(...args); await new Promise(r => setTimeout(r, 150)); }
    },
    async openFiles(tab = "explorer") {
      this.ensure(); createView();
      pendingTab = tab;
      if (!filesActive) {
        if (viewState() !== "jobs") { try { await navigate("jobs"); } catch (e) { console.error(e); } }
        document.querySelectorAll(".view").forEach(el => { el.hidden = el.id !== "view-ls-files"; });
        filesActive = true;
      }
      await this.call("show", tab);
      tick();
    },
    async openSearchQueue() {
      this.ensure();
      if (viewState() !== "queue") location.hash = "#/queue";
      tick();
    },
    // A screen of the bar that opens a Fichiers tab; "build" adds its own buttons.
    screen({ id, label, tab, build }) {
      LSPreview.register({
        id, label,
        controls(box) {
          const add = (text, on, toggle) => { const b = document.createElement("button"); b.type = "button"; b.textContent = text; b.onclick = () => on(b); box.append(b); return b; };
          const sep = () => { const s = document.createElement("span"); s.className = "ls-sep"; box.append(s); };
          build?.({ add, sep, box, call: (...a) => LSNav.call(...a), files: () => LSNav.files() });
        },
        activate() { LSNav.openFiles(tab); },
      });
    },
  };
  // Recherche with its new queue tab.
  LSPreview.register({
    id: "nav", label: "Navigation",
    controls(box) {
      const add = (text, on) => { const b = document.createElement("button"); b.type = "button"; b.textContent = text; b.onclick = on; box.append(b); };
      add("Recherche", () => { LSNav.ensure(); location.hash = "#/search"; });
      add("File de téléchargement", () => LSNav.openSearchQueue());
      add("Fichiers", () => LSNav.openFiles("explorer"));
      const s = document.createElement("span"); s.className = "ls-state"; s.textContent = "La file de téléchargement n'est plus dans la barre latérale : c'est un onglet de Recherche."; box.append(s);
    },
    activate() { LSNav.ensure(); location.hash = "#/search"; },
  });
})();
