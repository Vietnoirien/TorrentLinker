"use strict";
const $ = id => document.getElementById(id);
const state = {view:"media", clientId:"default", setup:{}};
let language="en", panelRequest, environment={}, environmentVersion=0, loadedEnvironment="", pendingEnvironment="";
const say=(en,fr)=>language==="fr"?fr:en;
function element(tag,text,cls){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node}
function button(text,callback,cls){const node=element("button",text,cls);node.type="button";node.onclick=()=>guard(callback);return node}
function toast(text){$("toast").textContent=text;$("toast").hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>$("toast").hidden=true,7000)}
async function guard(fn){try{return await fn()}catch(error){toast(error.message)}}
const api=(path,body,method)=>panelRequest(path,{body,method:method||(body===undefined?"GET":"POST")});
const host=(action,values={})=>panelRequest("host",{action,values});
const navigate=()=>host("settings");
function rememberTab(){}
const mediaViewsByKind={video:["recent","continue","films","series","anime","rated","unwatched","all"],music:["albums","artists","tracks"]};
const prefs=new Map();
window.mediaHostPreferences={getItem:key=>prefs.get(key),setItem:(key,value)=>{prefs.set(key,value);if(panelRequest)guard(()=>panelRequest("preferences",{layout:value}))}};
const artCache=new Map();
const artPending=[];let artActive=0;
function mediaImage(image,row){
  // Cache and bound owner-side image requests; observers fetch only visible posters.
  image.dataset.artId=row.id;
  image.dataset.artClient=state.clientId;
  artObserver.observe(image);
}
const artObserver=new IntersectionObserver(entries=>{
  for(const entry of entries){if(!entry.isIntersecting)continue;artObserver.unobserve(entry.target);artPending.push(entry.target)}
  pumpArt();
},{rootMargin:"300px"});
function pumpArt(){
  while(artActive<4&&artPending.length){const image=artPending.shift();if(!image.isConnected)continue;
    const key=`${image.dataset.artClient}/${image.dataset.artId}`;
    artActive++;
    const request=artCache.get(key)||api(`media/items/${encodeURIComponent(image.dataset.artId)}/artwork?client_id=${encodeURIComponent(image.dataset.artClient)}`);
    artCache.set(key,request);if(artCache.size>120)artCache.delete(artCache.keys().next().value);
    Promise.resolve(request).then(result=>{if(image.isConnected)image.src=result.data_url}).catch(()=>{artCache.delete(key);image.dispatchEvent(new Event("error"))}).finally(()=>{artActive--;pumpArt()});
  }
}
function translate(){
  for(const node of document.querySelectorAll("[data-aria-en]"))node.setAttribute("aria-label",say(node.dataset.ariaEn,node.dataset.ariaFr));
  for(const node of document.querySelectorAll("[data-en][data-fr]"))node.textContent=say(node.dataset.en,node.dataset.fr);
  for(const [id,en,fr] of [["media-toolbar-refresh","Refresh library","Actualiser la médiathèque"],["media-toolbar-chat","Assistant","Assistant"],["media-center-mode","Media Center mode","Mode Media Center"]]){const node=$(id);node.title=say(en,fr);node.setAttribute("aria-label",node.title)}
  for(const node of document.querySelectorAll("[data-adult]"))node.hidden=!state.setup.adult_content;
}
window.addEventListener("media-environment",event=>{
  environment=event.detail;
  if(panelRequest)guard(applyEnvironment);
});
async function applyEnvironment(){
  const env=environment;
  language=env.language||"en";state.clientId=env.client_id||"default";state.view=env.active?"media":"";
  state.setup={adult_content:!!env.adult_content};
  document.documentElement.lang=language;document.documentElement.dataset.theme=env.theme||"dark";
  document.documentElement.style.setProperty("--media-player-clearance",`${Math.max(0,Math.min(innerHeight,Number(env.player_clearance)||0))}px`);
  const center=$("media-center-mode");
  center.setAttribute("aria-pressed",String(!!env.center_mode));
  center.title=env.center_mode?say("Return to TorrentLinker","Revenir à TorrentLinker"):say("Media Center mode","Mode Media Center");
  center.setAttribute("aria-label",center.title);
  $("media-toolbar-chat").setAttribute("aria-pressed",String(!!env.chat_open));
  mediaQueueLabel();
  if(!env.active)return;
  const key=JSON.stringify([env.client_id,env.language,env.adult_content,env.revision]);
  if(loadedEnvironment===key||pendingEnvironment===key)return;
  const version=++environmentVersion;
  pendingEnvironment=key;media.request++;
  try {
    const preferences=await panelRequest("preferences",{});
    if(version!==environmentVersion)return;
    media.layout=preferences.layout||"cinematic";
    if(mediaViewsByKind[env.kind]&&(env.kind!==media.kind||env.view)){media.kind=env.kind;media.view=mediaViewsByKind[env.kind].includes(env.view)||env.view==="adult"&&state.setup.adult_content?env.view:mediaViewsByKind[env.kind][0]}
    translate();mediaViews();$("view-media").inert=false;
    await loadMedia();
    if(version===environmentVersion)loadedEnvironment=key;
  } finally {
    if(version===environmentVersion)pendingEnvironment="";
  }
}

