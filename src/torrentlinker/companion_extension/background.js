// No background reads, timers, cookies API or persistent storage.
chrome.action.onClicked.addListener((tab) => {
  chrome.tabs.create({
    url: chrome.runtime.getURL(`companion.html?source=${tab.id}`),
  });
});
