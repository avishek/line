"use strict";

const profileUrlEl = document.getElementById("profileUrl");
const downloadBtnEl = document.getElementById("downloadBtn");
const statusEl = document.getElementById("status");

init();

async function init() {
  try {
    const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const tabUrl = activeTab?.url || "";
    if (isLinkedInProfileUrl(tabUrl)) {
      profileUrlEl.value = tabUrl;
    }

    const stored = await chrome.storage.local.get(["lastLinkedInProfileUrl"]);
    if (!profileUrlEl.value && isLinkedInProfileUrl(stored.lastLinkedInProfileUrl || "")) {
      profileUrlEl.value = stored.lastLinkedInProfileUrl;
    }
  } catch {
    // Keep UI usable even if prefill fails.
  }

  downloadBtnEl.addEventListener("click", onDownloadClick);
}

async function onDownloadClick() {
  const profileUrl = (profileUrlEl.value || "").trim();
  if (!isLinkedInProfileUrl(profileUrl)) {
    setStatus("Use a valid LinkedIn profile URL: https://www.linkedin.com/in/...", "err");
    return;
  }

  downloadBtnEl.disabled = true;
  setStatus("Starting CDP automation...", "muted");

  try {
    await chrome.storage.local.set({ lastLinkedInProfileUrl: profileUrl });

    const response = await chrome.runtime.sendMessage({
      type: "download_resume_pdf",
      url: profileUrl,
    });

    if (!response?.ok) {
      throw new Error(response?.error || "Resume download failed");
    }

    const label = response.filename
      ? `Download started/completed: ${response.filename}`
      : `Download event captured (id: ${response.downloadId ?? "n/a"})`;
    setStatus(label, "ok");
  } catch (err) {
    setStatus(err?.message || "Resume download failed", "err");
  } finally {
    downloadBtnEl.disabled = false;
  }
}

function setStatus(message, kind) {
  statusEl.className = kind;
  statusEl.textContent = message;
}

function isLinkedInProfileUrl(raw) {
  try {
    const url = new URL(raw);
    return url.hostname === "www.linkedin.com" && url.pathname.startsWith("/in/");
  } catch {
    return false;
  }
}
