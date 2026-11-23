"use strict";
// PREVIEW STUB of panel/transport.js: the real file talks to the Web shell (postMessage) or the
// Qt bridge. Here every request is answered by preview/backend.js, with state kept in memory.
window.TLPanel.connect = (name) =>
  new Promise((resolve) => {
    window[`${name}Ready`] = () => window.previewBackend.environment(name);
    resolve((path, body) => window.previewBackend.request(name, path, body));
  });
