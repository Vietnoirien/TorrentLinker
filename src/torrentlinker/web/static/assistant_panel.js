"use strict";
// Settings and the compact Media chat retain their existing host until #111/#112.
// The full Discussion/History workspace uses the bundled desktop/Web panel.
const assistantFrame = document.createElement("iframe");
assistantFrame.id="assistant-frame";
assistantFrame.title="Assistant";
assistantFrame.src="static/assistant/view.html";
assistantFrame.style.cssText="width:100%;height:100%;min-height:240px;border:0;display:block;flex:1";
let assistantRevision=0;
async function loadAssistant() {
  if (assistantRoot().closest("#media-chat-content")) return loadLegacyAssistant();
  if (!assistantFrame.isConnected) assistantRoot().replaceChildren(assistantFrame);
  assistantRevision++;
  assistantEnvironment();
}
function assistantEnvironment() {
  const active=state.view==="assistant" && !$("workspace").hidden && assistantFrame.isConnected;
  if(active) assistantFrame.style.height=`${Math.max(240,innerHeight-assistantFrame.getBoundingClientRect().top-20)}px`;
  assistantFrame.contentWindow?.postMessage({type:"assistant-environment",value:{mode:"web",active,revision:assistantRevision,language,theme:document.documentElement.dataset.theme||"dark"}},location.origin);
}
window.addEventListener("message",async event=>{
  if(event.source!==assistantFrame.contentWindow || event.origin!==location.origin)return;
  const message=event.data;
  if(message?.type==="assistant-ready") {assistantEnvironment();return;}
  if(message?.type!=="assistant-request")return;
  try {
    if($("workspace").hidden)throw Error("Sign in first.");
    let value;
    if(message.path==="connections") {
      await navigate("setup","assistant");
      value=null;
    } else if(message.path==="preferences") {
      if(message.body.sidebar_width) localStorage.setItem("tl-assistant-sidebar-width",String(Math.max(180,Math.min(420,message.body.sidebar_width))));
      value={sidebar_width:Number(localStorage.getItem("tl-assistant-sidebar-width"))||240};
    } else if(message.path.startsWith("assistant/image?")) {
      const response=await fetch(new URL("api/"+message.path,document.baseURI),{credentials:"same-origin"});
      if(!response.ok)throw Error("Image unavailable");
      const blob=await response.blob();
      value={data_url:await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(blob);})};
    } else {
      if(!/^(setup(?:\/assistant(?:\/|$)|$)|assistant\/|agents\/proposals\/|jobs\/)/.test(message.path))throw Error("Unknown Assistant panel operation");
      value=await api(message.path,message.body.body,message.body.method);
    }
    assistantFrame.contentWindow?.postMessage({type:"assistant-response",id:message.id,value},location.origin);
  } catch(error) {
    assistantFrame.contentWindow?.postMessage({type:"assistant-response",id:message.id,error:error.message},location.origin);
  }
});
window.addEventListener("resize",assistantEnvironment);
document.addEventListener("tl-language-changed",assistantEnvironment);
new MutationObserver(assistantEnvironment).observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
new MutationObserver(assistantEnvironment).observe(assistantRoot(),{attributes:true,attributeFilter:["hidden"]});

if(state.view === "assistant" && !$("workspace").hidden) loadAssistant();
