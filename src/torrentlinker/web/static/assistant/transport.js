"use strict";
const $ = id => document.getElementById(id);
let state = {view: "assistant", language: "en", setup: {clients:[], client_id:""}};
const say = (en, fr) => state.language === "fr" ? fr : en;
let panelRequest;
function element(tag, text, cls) { const node=document.createElement(tag); if(text!==undefined)node.textContent=text; if(cls)node.className=cls; return node; }
function button(text, callback, cls) { const node=element("button",text,cls);node.type="button";node.onclick=()=>guard(callback);return node; }
function toast(text) { $("toast").textContent=text;$("toast").hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$("toast").hidden=true,7000); }
async function guard(fn) { try { return await fn(); } catch(error) { toast(error.message); } }
const api = (path, body, method) => panelRequest(path,{body, method:method || (body === undefined ? "GET" : "POST")});
const navigate = () => panelRequest("connections",{});
const fmt = bytes => new Intl.NumberFormat(state.language,{maximumFractionDigits:1}).format(bytes/1024**3)+" GiB";
let lastEnvironment = "", lastRevision=-1;
window.addEventListener("assistant-environment", async event => {
  const env=event.detail;
  state.mode=env.mode;
  state.view=env.active ? "assistant" : "";
  const changed=lastEnvironment !== `${env.language}/${env.theme}`;
  state.language=env.language || "en";
  document.documentElement.lang=state.language;
  document.documentElement.dataset.theme=env.theme || "dark";
  if(!panelRequest || !env.active)return;
  if(env.error) {
    const notice=element("p",env.error,"error"); notice.setAttribute("role","alert");
    $("view-assistant").replaceChildren(notice);
    lastEnvironment="";
    return;
  }
  await guard(async()=>{
    if(changed || env.revision !== lastRevision || !assistantSnapshot) {
      state.setup=await api("setup");
      const prefs=await panelRequest("preferences",{});
      document.documentElement.style.setProperty("--assistant-width",`${prefs.sidebar_width || 240}px`);
      lastEnvironment=`${env.language}/${env.theme}`;
      lastRevision=env.revision;
      await loadAssistant();
    }
  });
});
TLPanel.connect("assistant",{asynchronous:true}).then(request=>{panelRequest=request;window.assistantReady();});

async function loadPanelImage(image, source) {
  image.removeAttribute("src");
  try {
    if(source?.startsWith("data:image/")) { image.src=source;return; }
    if(!source?.startsWith("api/assistant/image?"))throw Error("Invalid image source");
    const result=await api(source.slice(4));
    image.src=result.data_url;
  } catch { image.dispatchEvent(new Event("error")); }
}

document.addEventListener("click",event=>{
  const link=event.target.closest("a");
  if(!link || state.mode!=="desktop")return;
  event.preventDefault();
  guard(()=>panelRequest("open-link",{url:link.getAttribute("href")}));
});
let sidebarObserver;
function rememberSidebar(side) {
  sidebarObserver?.disconnect();
  let timer;
  sidebarObserver=new ResizeObserver(()=>{
    if(innerWidth<=1050 || !side.isConnected || !side.getClientRects().length)return;
    const width=Math.round(side.getBoundingClientRect().width);
    document.documentElement.style.setProperty("--assistant-width",`${width}px`);
    clearTimeout(timer);
    timer=setTimeout(()=>guard(()=>panelRequest("preferences",{sidebar_width:width})),250);
  });
  sidebarObserver.observe(side);
}
