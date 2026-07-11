/**
 * popup.js — ARIA Clipper (Manifest V3).
 *
 * Captures the active tab's URL + the user's current text selection (via
 * chrome.scripting) and POSTs them to the ARIA backend clipper endpoint.
 * The session cookie for aria-ai.fly.dev is sent with `credentials: 'include'`
 * (host_permissions grants access), so the backend authenticates the user with
 * the same signed session as the web app.
 */

const API_BASE = "https://aria-ai.fly.dev";
const CAPTURE_URL = `${API_BASE}/api/v1/clipper/capture`;

const $ = (id) => document.getElementById(id);

/** Read the selected text inside the page context. */
function getSelectionText() {
  return (window.getSelection && window.getSelection().toString()) || "";
}

async function loadActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab) return { url: "", title: "", selection: "" };

  let selection = "";
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: getSelectionText,
    });
    selection = (results && results[0] && results[0].result) || "";
  } catch (e) {
    // Some pages (chrome://, web store) disallow scripting — degrade gracefully.
    selection = "";
  }
  return { url: tab.url || "", title: tab.title || "", selection };
}

let current = { url: "", title: "", selection: "" };

async function init() {
  current = await loadActiveTab();
  $("url").textContent = current.url || "(no URL)";
  $("selection").textContent =
    current.selection || "(nothing selected — highlight text on the page first)";
}

async function send() {
  const btn = $("send");
  const status = $("status");
  btn.disabled = true;
  status.className = "status";
  status.textContent = "Sending…";
  try {
    const res = await fetch(CAPTURE_URL, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: current.url,
        title: current.title,
        selection: current.selection,
        clipped_at: new Date().toISOString(),
      }),
    });
    if (res.status === 401) {
      status.className = "status err";
      status.innerHTML =
        'Please <a class="lnk" href="' + API_BASE + '/login" target="_blank">sign in to ARIA</a> first.';
      return;
    }
    if (!res.ok) throw new Error("HTTP " + res.status);
    status.className = "status ok";
    status.textContent = "✓ Clipped to ARIA";
    setTimeout(() => window.close(), 900);
  } catch (e) {
    status.className = "status err";
    status.textContent = "Couldn't reach ARIA. Try again.";
  } finally {
    btn.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", init);
$("send").addEventListener("click", send);
