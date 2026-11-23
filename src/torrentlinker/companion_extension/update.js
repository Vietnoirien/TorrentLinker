// The app announces its bundled companion version in the replies it already gives while
// paired. When it is newer than this extension, reload from the managed folder, once per
// announced version: a folder nobody updated must never cause a reload loop.
export function newer(announced, installed) {
  const parse = (v) => String(v).split(".").map((n) => Number.parseInt(n, 10));
  const a = parse(announced), b = parse(installed);
  if (!/^\d+(\.\d+){0,3}$/.test(String(announced))) return false;
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const x = a[i] || 0, y = b[i] || 0;
    if (x !== y) return x > y;
  }
  return false;
}
export async function reloadIfNewer(announced) {
  if (!newer(announced, chrome.runtime.getManifest().version)) return false;
  const { reloadedFor } = await chrome.storage.local.get("reloadedFor");
  if (reloadedFor === announced) return false;
  await chrome.storage.local.set({ reloadedFor: announced });
  chrome.runtime.reload();
  return true;
}
