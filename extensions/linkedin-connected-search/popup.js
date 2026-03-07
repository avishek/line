"use strict";

const STORAGE_FIRST_SEARCHED_NAME = "firstLinkedInSearchName";

const queryNameEl = document.getElementById("queryName");
const runBtnEl = document.getElementById("runBtn");
const statusEl = document.getElementById("status");
const resultEl = document.getElementById("result");

init();

async function init() {
  try {
    const stored = await chrome.storage.local.get([STORAGE_FIRST_SEARCHED_NAME]);
    const firstName = String(stored?.[STORAGE_FIRST_SEARCHED_NAME] || "").trim();
    if (firstName) {
      queryNameEl.value = firstName;
    }
  } catch {
    // Keep popup usable if storage prefill fails.
  }

  runBtnEl.addEventListener("click", onRunClick);
}

async function onRunClick() {
  const queryName = String(queryNameEl.value || "").trim();
  if (!queryName) {
    setStatus("Enter a name to search on LinkedIn.", "err");
    setResult("");
    return;
  }

  setBusy(true);
  setStatus("Running LinkedIn connected search via CDP...", "muted");
  setResult("");

  try {
    await persistFirstSearchedName(queryName);

    const response = await chrome.runtime.sendMessage({
      type: "run_connected_search",
      queryName,
    });

    if (!response?.ok) {
      throw new Error(response?.error || "Connected search failed");
    }

    setStatus(`Completed. Result file: ${response.filename}`, "ok");
    setResult(
      [
        `Profile URL: ${response.profileUrl}`,
        `Has mutual connections: ${response.hasMutualConnections ? "Yes" : "No"}`,
      ].join("\n")
    );
  } catch (err) {
    setStatus(err?.message || "Connected search failed", "err");
  } finally {
    setBusy(false);
  }
}

async function persistFirstSearchedName(queryName) {
  const stored = await chrome.storage.local.get([STORAGE_FIRST_SEARCHED_NAME]);
  const existingFirst = String(stored?.[STORAGE_FIRST_SEARCHED_NAME] || "").trim();
  if (!existingFirst) {
    await chrome.storage.local.set({ [STORAGE_FIRST_SEARCHED_NAME]: queryName });
  }
}

function setBusy(busy) {
  runBtnEl.disabled = busy;
}

function setStatus(message, kind) {
  statusEl.className = kind || "muted";
  statusEl.textContent = message;
}

function setResult(message) {
  resultEl.textContent = message;
}
