"use strict";
// Candidate inspection lives in the bundled Reseed panel. This host retains
// server folder browsing and download settings.
const libraryUI={item:null,candidate:null,generation:0,client:null};
function resetLibraryReview(){
  if(libraryUI.client===state.clientId)return;
  libraryUI.client=state.clientId;libraryUI.item=null;libraryUI.candidate=null;libraryUI.generation++;
}
async function loadLibrary(){resetLibraryReview();await loadReseed();}
async function libraryTab(tab){
  resetLibraryReview();
  tab=["folders","activity"].includes(tab)?tab:"reseed";
  rememberTab("library",tab);$("library-reseed").hidden=false;
  reseedUI.tab=tab;await loadReseed();
}
async function browseLibraryFolder(path="",target="library-folder-path") {
  const result=await api(`folders?path=${encodeURIComponent(path)}`);
  const host=$("dialog-content");host.replaceChildren(element("h2",say("Folders on the TorrentLinker server","Dossiers du serveur TorrentLinker")),element("p",result.path || say("Mounted roots","Racines montées")));
  if(result.path) {
    host.append(button(say("Use this folder","Utiliser ce dossier"),()=>{$(target).value=result.path;$("dialog").close();},"primary"));
    host.append(button("↑",()=>browseLibraryFolder(result.parent,target)));
  }
  for(const folder of result.folders) host.append(button(folder,()=>browseLibraryFolder(folder,target),"directory-button"));
  if(!result.path && !result.folders.length) host.append(element("p",say("No mounted roots. Set TL_STORAGE_ROOTS on the TorrentLinker server.","Aucune racine montée. Configurez TL_STORAGE_ROOTS sur le serveur.")));
  if(!$("dialog").open) $("dialog").showModal();
}
$("settings-library-folders").onclick=()=>guard(()=>navigate("library", "folders"));

function renderLibraryDownloads() {
  const folders=state.setup.download_folders || {default:"",by_category:{},effective:{}};
  const categories=state.setup.indexer_categories || {};
  const select=$("library-download-category"), current=select.value;
  select.replaceChildren(new Option(say("Default","Par défaut"),""));
  for(const row of categoryRows(categories)) select.add(new Option(row.path,row.id));
  select.value=current;
  select.parentElement.querySelector(".category-picker")?.remove();
  select.after(categoryPicker(select,categories));
  const sequential=$("library-sequential-video");sequential.checked=!!state.setup.sequential_video;
  sequential.onchange=()=>guard(async()=>{await api("setup/sequential-video",{enabled:sequential.checked});await refreshSetup();});
  const adult=$("library-adult-content");adult.checked=!!state.setup.adult_content;
  adult.onchange=()=>guard(async()=>{await api("setup/adult-content",{enabled:adult.checked});await refreshSetup();});
  const host=$("library-download-destinations");host.replaceChildren();
  for(const [id,path] of [["",folders.default],...Object.entries(folders.by_category)]) {
    const row=element("div",undefined,"library-folder-row");
    row.append(element("span",`${id?(categoryRows(categories).find(row=>row.id===id)?.path || id):say("Default","Par défaut")} · ${path || say("Not set","Non configuré")}`));
    row.append(button(say("Edit","Modifier"),()=>{select.value=id;select.dispatchEvent(new Event("change"));$("library-download-path").value=path;}));
    if(path) row.append(button(id?say("Use inherited destination","Utiliser la destination héritée"):say("Clear default","Retirer le dossier par défaut"),async()=>{
      await api("setup/remove-folder",{purpose:"download",local:path,category:id?Number(id):null});await refreshSetup();
    }));
    host.append(row);
  }
  select.onchange=()=>{
    $("library-download-path").value=select.value?folders.by_category[select.value] || "":folders.default;
    $("library-download-feedback").textContent=say("Effective destination: ","Destination effective : ")+(select.value?folders.effective[select.value]:folders.default || "—");
  };
}
$("library-download-form").onsubmit=e=>{e.preventDefault();guard(async()=>{
  const category=$("library-download-category").value;
  await job({kind:"configure-download-folder",path:$("library-download-path").value.trim(),category:category?Number(category):null},async()=>{
    await refreshSetup();$("library-download-feedback").textContent=say("Destination verified and saved.","Destination vérifiée et enregistrée.");
  });
});};
