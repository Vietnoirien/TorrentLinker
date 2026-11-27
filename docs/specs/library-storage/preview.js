"use strict";
// Library-storage previews: a bar at the bottom switches screens. Each screen is a file
// (replace.js, ...) that calls LSPreview.register({id, label, controls(box), activate(), deactivate()}).
// To add one: put its file in this folder and add its id to SCREENS.
(() => {
  // Loaded in this order (nav.js before the screens that use LSNav); the first one registered opens.
  const SCREENS = ["replace", "nav", "explorer", "tasks", "disks", "trash", "organisation", "links"];
  const BASE = "/library-storage-preview/";
  const registry = new Map();
  let current = "";
  const bar = document.createElement("div");
  bar.id = "ls-bar";
  bar.innerHTML = '<b class="ls-title">Aperçu</b><span class="ls-tabs"></span><span class="ls-controls"></span>';
  const tabs = bar.querySelector(".ls-tabs"), controls = bar.querySelector(".ls-controls");
  function show(id) {
    if (current && registry.get(current)?.deactivate) registry.get(current).deactivate();
    current = id;
    for (const b of tabs.children) b.classList.toggle("on", b.dataset.id === id);
    controls.replaceChildren();
    const screen = registry.get(id);
    if (screen) { screen.controls?.(controls); screen.activate?.(); }
  }
  // ⓘ info box for pages inside the app's iframes (the Fichiers page has its own copy in fichiers-storage.js).
  // Same behaviour: hover with a close delay, click, Enter/Esc, phone. tipHTML(text) makes the button; tipInstall(doc) wires one document once.
  const escA = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const tipHTML = (text, label = "Plus d'informations") => `<button type="button" class="ls-info" data-tip="${escA(text)}" aria-label="${escA(label)}" aria-expanded="false">i</button>`;
  function tipInstall(doc) {
    if (doc.getElementById("ls-tip-style")) return;
    const st = doc.createElement("style"); st.id = "ls-tip-style";
    st.textContent = `.ls-info{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;padding:0;border-radius:50%;font:italic 700 12px/1 Georgia,serif;color:#80bdb6;background:#80bdb626;border:1px solid #ffffff33;cursor:pointer;flex:none;vertical-align:middle}
      .ls-info[aria-expanded=true]{border-color:#80bdb6}
      #ls-tip{position:fixed;z-index:2147483000;max-width:min(320px,calc(100vw - 16px));padding:10px 12px;background:#202932;color:#e2e9ed;border:1px solid #80bdb6;border-radius:9px;box-shadow:0 12px 40px #0006;font:13px/1.4 system-ui,sans-serif;white-space:pre-line}
      #ls-tip[hidden]{display:none}`;
    doc.head.append(st);
    const win = doc.defaultView;
    let el = null, cur = null, timer = 0;
    const hide = () => { if (el) el.hidden = true; cur?.setAttribute("aria-expanded", "false"); cur = null; };
    const show = btn => {
      if (!el) { el = doc.createElement("div"); el.id = "ls-tip"; el.setAttribute("role", "tooltip"); el.hidden = true; doc.body.append(el); }
      cur?.setAttribute("aria-expanded", "false");
      (btn.closest("dialog") || doc.body).append(el);
      cur = btn; btn.setAttribute("aria-expanded", "true");
      el.textContent = btn.dataset.tip; el.hidden = false;
      const r = btn.getBoundingClientRect(), w = el.offsetWidth, h = el.offsetHeight;
      el.style.left = Math.max(8, Math.min(win.innerWidth - w - 8, r.left + r.width / 2 - w / 2)) + "px";
      el.style.top = (r.bottom + 6 + h > win.innerHeight - 8 && r.top - h - 6 > 8 ? r.top - h - 6 : r.bottom + 6) + "px";
    };
    doc.addEventListener("click", e => {
      const b = e.target.closest?.(".ls-info");
      if (b) { e.preventDefault(); e.stopPropagation(); cur === b ? hide() : show(b); }
      else if (!e.target.closest?.("#ls-tip")) hide();
    }, true);
    doc.addEventListener("keydown", e => { if (e.key === "Escape") hide(); });
    const hover = () => win.matchMedia("(hover:hover)").matches;
    doc.addEventListener("mouseover", e => {
      if (!hover()) return;
      const b = e.target.closest?.(".ls-info");
      if (b || e.target.closest?.("#ls-tip")) clearTimeout(timer);
      if (b && cur !== b) show(b);
    });
    doc.addEventListener("mouseout", e => {
      if (!hover() || !(e.target.closest?.(".ls-info") || e.target.closest?.("#ls-tip"))) return;
      const to = e.relatedTarget;
      if (to?.closest?.("#ls-tip") || (cur && to?.closest?.(".ls-info") === cur)) return;
      clearTimeout(timer); timer = setTimeout(hide, 300);
    });
    win.addEventListener("scroll", hide, true);
  }
  window.LSPreview = {
    BASE, tipHTML, tipInstall,
    register(screen) {
      registry.set(screen.id, screen);
      const b = document.createElement("button");
      b.type = "button"; b.dataset.id = screen.id; b.textContent = screen.label;
      b.onclick = () => show(screen.id);
      tabs.append(b);
      if (!current) show(screen.id);
    },
    go(hash) { location.hash = hash; },
  };
  addEventListener("DOMContentLoaded", () => {
    document.body.append(bar);
    for (const id of SCREENS) {
      const script = document.createElement("script");
      script.src = `${BASE}${id}.js`;
      script.async = false; // keeps the order of SCREENS
      document.head.append(script);
    }
  });
})();
