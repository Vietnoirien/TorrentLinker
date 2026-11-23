// The Trackers the companion can pair (ADR-0025). Each one has its own origin, tabs,
// connection and endpoint allowlist; a tab of one never answers for the other.
export const TRACKERS = {
  c411: { id: "c411", name: "c411", origin: "https://c411.org" },
  tr4ker: { id: "tr4ker", name: "tr4ker", origin: "https://tr4ker.net" },
};
export const tabPattern = (tracker) => TRACKERS[tracker].origin + "/*";
export const ownsUrl = (tracker, url) =>
  typeof url === "string" && url.startsWith(TRACKERS[tracker].origin + "/");
