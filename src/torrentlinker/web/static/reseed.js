"use strict";
document.querySelector("#view-library > p").hidden = true;
const reseedUI = { root: "", job: null, tab: "reseed" };
const reseedFrame = document.createElement("iframe");
reseedFrame.id = "reseed-frame";
reseedFrame.title = "Bibliothèque";
reseedFrame.src = "static/reseed/view.html";
reseedFrame.style.cssText =
  "width:100%;height:calc(100vh - 200px);min-height:240px;border:0;display:block";
$("library-reseed").replaceChildren(reseedFrame);
const reseedEnvironment = () => {
  if (!$("library-reseed").hidden)
    reseedFrame.style.height = `${Math.max(240, innerHeight - reseedFrame.getBoundingClientRect().top - 40)}px`;
  reseedFrame.contentWindow?.postMessage(
    {
      type: "reseed-environment",
      value: {
        mode: "web",
        tab: reseedUI.tab,
        language,
        theme: ["light", "dark"].includes(
          document.documentElement.dataset.theme,
        )
          ? document.documentElement.dataset.theme
          : matchMedia("(prefers-color-scheme: dark)").matches
            ? "dark"
            : "light",
        client: state.clientId,
        active: !$("library-reseed").hidden && !$("workspace").hidden,
        clear: $("workspace").hidden,
      },
    },
    location.origin,
  );
};
async function loadReseed() {
  reseedEnvironment();
}
async function waitReseedJob(body) {
  const client=state.clientId;
  const created=await api("jobs",{...body,client_id:client});
  for (;;) {
    if(client!==state.clientId)throw new Error("The target client changed. Reopen the Library.");
    const result=await api(`jobs/${created.id}`);
    if(result.status==="completed")return result.result;
    if(!["queued","running"].includes(result.status))throw new Error(result.error || "Operation cancelled.");
    await new Promise(resolve=>setTimeout(resolve,500));
  }
}
async function reseedRequest(action, body) {
  if (body._client !== state.clientId)
    throw new Error("The target client changed. Reopen the Library.");
  body = { ...body };
  delete body._client;
  if (action === "state") {
    const client = state.clientId;
    const [data, setup, jobs] = await Promise.all([
      api("reseed-workspace"),
      api("setup"),
      api("jobs"),
    ]);
    const current = jobs.find(
      (j) =>
        j.kind === "reseed-workspace" &&
        j.client_id === client &&
        ["running", "queued"].includes(j.status),
    );
    reseedUI.job = current?.id || null;
    reseedUI.root = data.link_root;
    reseedUI.rows = data.rows;
    const latest =
      current ||
      jobs.find((j) => j.kind === "reseed-workspace" && j.client_id === client);
    const progress = { ...current?.progress, paused_paths: data.paused_paths };
    const error = [
      latest?.error,
      ...(latest?.progress?.errors || []).map((e) => e.message),
    ]
      .filter(Boolean)
      .join("\n");
    return {
      error,
      activity: jobs.filter(j => j.client_id === client && /^(scan|check|reseed|search-library|library-|unpack|find-compatible|combine-library|.*repair)/.test(j.kind)).map(j => ({at: j.created || 0, kind: j.kind, status: j.status, message: j.error || ""})),
      rows: data.rows,
      folder_errors: data.folder_errors,
      setup,
      running: !!current,
      paused: !!progress.paused,
      progress,
      scanning:
        Object.hasOwn(progress.active || {}, "") ||
        jobs.some(
          (j) =>
            j.kind === "scan" &&
            j.client_id === client &&
            ["running", "queued"].includes(j.status),
        ),
    };
  }
  if (action === "inspect") return waitReseedJob({kind:"candidate-inspector",path:body.path,inspector_action:body.action,candidate_key:body.key || "",torrent_data:body.torrent_data || ""});
  if (action === "combine") return waitReseedJob({kind:"combine-library",paths:body.paths,selection_name:body.name});
  if (action === "selection") return {};
  if (action === "tab") { reseedUI.tab = body.tab; return {}; }
  if (action === "preview-folder") return api("setup/preview-folder", body);
  if (action === "remove-folder") return api("setup/remove-folder", body);
  if (action === "run")
    return api("jobs", {
      kind: "reseed-workspace",
      paths: body.paths,
      reseed_action: "all",
      link_root: reseedUI.root,
      candidate_key: body.key || "",
    });
  if (action === "pause-item" || action === "enqueue")
    return api(
      `reseed-workspace/control?client_id=${encodeURIComponent(state.clientId)}`,
      { ...body, action },
    );
  if (action === "pause")
    return api(`jobs/${reseedUI.job}/pause-reseed?paused=${!!body.paused}`, {});
  if (action === "stop") return api(`jobs/${reseedUI.job}/cancel`, {});
  if (action === "scan") {
    if (reseedUI.job)
      return api(
        `reseed-workspace/control?client_id=${encodeURIComponent(state.clientId)}`,
        { action: "scan", folders: body.folders },
      );
    return job({ kind: "scan", paths: body.folders || [] }, loadReseed);
  }
  if (action === "browse")
    return api(`folders?path=${encodeURIComponent(body.path || "")}`);
  if (action === "save-root") return api("setup/reseed-folder", body);
  if (action === "add-folder") return api("setup/folder", body);
  if (action === "add-client") {
    const result = await api("clients", body);
    state.clientId = result.client_id;
    await refreshSetup();
    await navigate("library", "reseed");
    return result;
  }
  if (action === "manage-folders") {
    await libraryTab("folders");
    return {};
  }
  if (action === "settings") {
    await openReseedSettings();
    return {};
  }
  if (action === "repair-history") {
    const client=state.clientId;
    const rows=await waitReseedJob({kind:"candidate-inspector",inspector_action:"repairs"});
    if(client!==state.clientId)return {};
    const content=$("dialog-content");content.replaceChildren(element("h2",say("Repair history","Historique des réparations")));
    for(const row of rows)renderRepair(content,row);
    if(!rows.length)content.append(element("p",say("No repairs recorded.","Aucune réparation enregistrée.")));
    content.append(button(say("Close","Fermer"),()=>$("dialog").close()));
    $("dialog").showModal();return {};
  }
  if (action === "archive") {
    libraryUI.item={path:body.path};libraryUI.candidate={key:body.key};libraryUI.generation++;
    return previewArchive(libraryUI.candidate);
  }
  if (action === "repair") {
    const client=state.clientId;
    return job({kind:"diagnose-repair",path:body.path,candidate_key:body.key}, result=>{
      if(client!==state.clientId)return;
      const content=$("dialog-content");content.replaceChildren();
      renderRepair(content,result);
      content.append(button(say("Close","Fermer"),()=>$("dialog").close()));
      $("dialog").showModal();
    });
  }
  throw new Error("Unknown reseed operation.");
}
window.addEventListener("message", async (event) => {
  if (
    event.source !== reseedFrame.contentWindow ||
    event.origin !== location.origin
  )
    return;
  const message = event.data;
  if (message?.type === "reseed-ready") {
    reseedEnvironment();
    return;
  }
  if (message?.type !== "reseed-request") return;
  try {
    if ($("workspace").hidden)
      throw new Error("Open your signed-in workspace first.");
    const value = await reseedRequest(message.path, message.body || {});
    reseedFrame.contentWindow?.postMessage(
      { type: "reseed-response", id: message.id, value },
      location.origin,
    );
  } catch (error) {
    reseedFrame.contentWindow?.postMessage(
      { type: "reseed-response", id: message.id, error: error.message },
      location.origin,
    );
  }
});
window.addEventListener("resize", reseedEnvironment);
document.addEventListener("tl-language-changed", reseedEnvironment);
for (const node of [
  $("library-reseed"),
  $("workspace"),
  document.documentElement,
])
  new MutationObserver(reseedEnvironment).observe(node, {
    attributes: true,
    attributeFilter: ["hidden", "data-theme"],
  });
$("reseed-browse").onclick = () =>
  guard(() => browseLibraryFolder("", "reseed-root"));

async function openReseedSettings() {
  await navigate("setup", "connections");
  $("reseed-folder-settings").open = true;
  $("reseed-root").focus();
}

$("reseed-folder-form").onsubmit = (event) => {
  event.preventDefault();
  guard(async () => {
    const client = state.clientId;
    const result = await api("setup/reseed-folder", {
      path: $("reseed-root").value.trim(),
    });
    localStorage.removeItem(`reseed-root:${client}`);
    if (client !== state.clientId) return;
    state.setup.reseed_link_root = result.reseed_link_root;
    reseedUI.root = result.reseed_link_root;
    $("reseed-root").value = result.reseed_link_root;
    toast(
      say(
        "Link folder saved for this client.",
        "Dossier de liens enregistré pour ce client.",
      ),
    );
  });
};
