/* Category IDs and parent links come from Indexer capabilities, never from slashes in names. */
function categoryRows(categories) {
  const rows = [], seen = new Set();
  function visit(id, trail = []) {
    if (seen.has(id)) return;
    seen.add(id);
    const category = categories[id];
    const path = [...trail, category.name];
    rows.push({id, name: category.name, depth: trail.length, path: path.join(" › ")});
    for (const child of Object.keys(categories).filter(key => String(categories[key].parent) === id)) visit(child, path);
  }
  for (const id of Object.keys(categories).filter(key => !categories[String(categories[key].parent)])) visit(id);
  // Malformed parent links must not hide usable categories.
  for (const id of Object.keys(categories)) visit(id);
  return rows;
}

const categoryPickerUpdates = new WeakMap();
function categoryPicker(select, categories) {
  const previousUpdate = categoryPickerUpdates.get(select);
  if (previousUpdate) select.removeEventListener("change", previousUpdate);
  const picker = element("details", undefined, "category-picker");
  const summary = element("summary"), list = element("div", undefined, "category-branches");
  list.setAttribute("role", "group");
  list.setAttribute("aria-label", say("Categories and subcategories", "Catégories et sous-catégories"));
  const rows = [{id: "", name: say("Default", "Par défaut"), depth: 0, path: say("Default", "Par défaut")}, ...categoryRows(categories)];
  const current = select.value;
  select.replaceChildren(...rows.map(row => new Option(row.path, row.id)));
  select.value = current;
  if (select.selectedIndex < 0) select.value = "";
  function update() {
    summary.textContent = rows.find(row => row.id === select.value)?.path || rows[0].name;
    for (const item of list.children) item.setAttribute("aria-pressed", String(item.dataset.category === select.value));
  }
  for (const row of rows) {
    const item = button(row.depth ? `└─ ${row.name}` : row.name, () => {
      select.value = row.id;
      select.dispatchEvent(new Event("change", {bubbles:true}));
      picker.open = false;
      summary.focus();
    });
    item.dataset.category = row.id;
    item.style.paddingInlineStart = `${12 + row.depth * 20}px`;
    item.classList.toggle("category-parent", row.depth === 0);
    item.setAttribute("aria-label", row.path);
    item.title = row.path;
    list.append(item);
  }
  select.addEventListener("change", update);
  categoryPickerUpdates.set(select, update);
  picker.addEventListener("keydown", event => {
    if (event.key === "Escape") {picker.open = false; summary.focus(); event.stopPropagation();}
  });
  picker.addEventListener("focusout", event => {
    if (!picker.contains(event.relatedTarget)) picker.open = false;
  });
  select.hidden = true;
  picker.append(summary, list);
  update();
  return picker;
}
