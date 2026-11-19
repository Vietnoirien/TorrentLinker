"use strict";
let planRequest;
let planEnvironment = {
  mode: "desktop",
  language: "en",
  theme: "dark",
  active: false,
  state: {},
};
window.addEventListener("plan-environment", (event) => {
  planEnvironment = event.detail;
  if (planRequest) planApplyEnvironment(event.detail);
});
window.addEventListener("DOMContentLoaded", async () => {
  planInit();
  const request = await TLPanel.connect("plan");
  planRequest = (action, body = {}) =>
    request(action, { ...body, _client: planEnvironment.state?.client_id });
  window.planReady();
});
