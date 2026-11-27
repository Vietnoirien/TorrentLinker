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
  window.LSPreview = {
    BASE,
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
