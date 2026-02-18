"use strict";

const DEBUGGER_VERSION = "1.3";
const TAB_READY_TIMEOUT_MS = 45000;
const ELEMENT_WAIT_TIMEOUT_MS = 18000;
const DOWNLOAD_WAIT_TIMEOUT_MS = 45000;
const FILENAME_CORRELATION_WINDOW_MS = 90000;
const DEFAULT_PDF_FILENAME = "linkedin-profile.pdf";

let pendingFilenameOverride = null;
let activeBatchRun = false;

if (!chrome.downloads.onDeterminingFilename.hasListener(handleDeterminingFilename)) {
  chrome.downloads.onDeterminingFilename.addListener(handleDeterminingFilename);
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type === "download_resume_pdf") {
    runResumeDownload(msg.url)
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((error) => {
        sendResponse({ ok: false, error: error?.message || "Resume download failed" });
      });
    return true;
  }

  if (msg?.type === "start_batch_resume_download") {
    runBatchResumeDownload(msg.urls || [])
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((error) => {
        sendResponse({ ok: false, error: error?.message || "Batch resume download failed" });
      });
    return true;
  }

  return false;
});

async function runBatchResumeDownload(rawUrls, progressCallback) {
  const urls = sanitizeUrlList(rawUrls);
  if (!urls.length) {
    throw new Error("No URLs provided. Upload a file with one LinkedIn profile URL per line.");
  }

  if (activeBatchRun) {
    throw new Error("Another batch run is already in progress. Wait for it to finish.");
  }

  activeBatchRun = true;
  const results = [];
  try {
    for (let index = 0; index < urls.length; index += 1) {
      const url = urls[index];
      progressCallback?.({
        type: "progress",
        current: index + 1,
        total: urls.length,
        url,
      });

      try {
        const item = await runResumeDownload(url);
        const result = {
          index,
          url,
          ok: true,
          filename: item.filename || "",
          downloadId: item.downloadId ?? null,
          state: item.state || "complete",
        };
        results.push(result);
        progressCallback?.({ type: "item_result", item: result });
      } catch (err) {
        const result = {
          index,
          url,
          ok: false,
          error: err?.message || "Resume download failed",
        };
        results.push(result);
        progressCallback?.({ type: "item_result", item: result });
      }
    }
  } finally {
    activeBatchRun = false;
  }

  const successCount = results.filter((row) => row.ok).length;
  const failureCount = results.length - successCount;
  return {
    total: urls.length,
    successCount,
    failureCount,
    results,
  };
}

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== "batch_resume_download") {
    return;
  }

  let disconnected = false;
  port.onDisconnect.addListener(() => {
    disconnected = true;
  });

  port.onMessage.addListener(async (msg) => {
    if (msg?.type !== "start_batch_resume_download") {
      return;
    }

    try {
      const result = await runBatchResumeDownload(msg.urls || [], (event) => {
        if (!disconnected) {
          port.postMessage(event);
        }
      });
      if (!disconnected) {
        port.postMessage({ type: "done", ok: true, ...result });
      }
    } catch (error) {
      if (!disconnected) {
        port.postMessage({
          type: "done",
          ok: false,
          error: error?.message || "Batch resume download failed",
        });
      }
    }
  });
});

async function runResumeDownload(rawUrl) {
  const profileUrl = validateLinkedInProfileUrl(rawUrl);
  if (!profileUrl) {
    throw new Error("Invalid LinkedIn profile URL. Use https://www.linkedin.com/in/...");
  }
  const desiredFilename = buildDesiredPdfFilename(profileUrl);

  const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!activeTab?.id) {
    throw new Error("No active tab found.");
  }

  const tabId = activeTab.id;
  await chrome.tabs.update(tabId, { active: true });

  const activeUrl = validateLinkedInProfileUrl(activeTab.url || "");
  const sameTarget = activeUrl && normalizeProfileUrl(activeUrl) === normalizeProfileUrl(profileUrl);
  if (!sameTarget) {
    await chrome.tabs.update(tabId, { url: profileUrl });
    await waitForTabComplete(tabId, TAB_READY_TIMEOUT_MS);
  }
  await sleep(1200);

  const target = { tabId };
  await chrome.debugger.attach(target, DEBUGGER_VERSION);

  let result;
  try {
    result = await runCdpMenuFlow(target, { desiredFilename });
  } finally {
    await safeDetach(target);
  }

  return result;
}

async function runCdpMenuFlow(target, options) {
  await sendCdp(target, "Page.enable");
  await sendCdp(target, "Runtime.enable");
  await sendCdp(target, "DOM.enable");
  await sendCdp(target, "Overlay.enable");

  await waitForProfileHeaderReady(target, ELEMENT_WAIT_TIMEOUT_MS);

  await clickElementByTextWithRetry(target, "More", {
    timeoutMs: ELEMENT_WAIT_TIMEOUT_MS,
    menuCheck: true,
  });

  await waitForMenuItemVisible(target, "Save to PDF", ELEMENT_WAIT_TIMEOUT_MS);

  const issuedAtMs = Date.now();
  const desiredFilename = options?.desiredFilename || DEFAULT_PDF_FILENAME;
  setPendingFilenameOverride({
    desiredFilename,
    issuedAtMs,
  });

  const tracker = createPdfDownloadTracker({
    issuedAtMs,
    timeoutMs: DOWNLOAD_WAIT_TIMEOUT_MS,
    fallbackFilename: desiredFilename,
  });

  try {
    await clickElementByTextWithRetry(target, "Save to PDF", {
      timeoutMs: ELEMENT_WAIT_TIMEOUT_MS,
      menuCheck: false,
    });
    return await tracker.promise;
  } finally {
    tracker.cleanup();
    clearPendingFilenameOverride();
  }
}

async function clickElementByTextWithRetry(target, label, options) {
  const timeoutMs = options?.timeoutMs || ELEMENT_WAIT_TIMEOUT_MS;
  const deadline = Date.now() + timeoutMs;
  let lastError = "Unknown click failure";

  while (Date.now() < deadline) {
    const point = await findClickablePointByText(target, label);
    if (point) {
      try {
        await humanLikeClick(target, point);
        if (options?.menuCheck) {
          await pollForTruthy(
            () => isMenuItemVisible(target, "Save to PDF"),
            { timeoutMs: 4500, intervalMs: 180 }
          );
        }
        return;
      } catch (err) {
        lastError = err?.message || "Click dispatch failed";
      }
    } else {
      lastError = `Could not locate visible "${label}" control`;
    }

    await sleep(randInt(150, 320));
  }

  throw new Error(`Failed to click "${label}". ${lastError}`);
}

async function humanLikeClick(target, point) {
  const start = {
    x: point.x + randInt(-14, -4),
    y: point.y + randInt(-10, -3),
  };

  const steps = randInt(3, 5);
  for (let i = 1; i <= steps; i += 1) {
    const t = i / steps;
    const x = start.x + (point.x - start.x) * t;
    const y = start.y + (point.y - start.y) * t;
    await sendCdp(target, "Input.dispatchMouseEvent", {
      type: "mouseMoved",
      x,
      y,
      button: "none",
      pointerType: "mouse",
    });
    await sleep(randInt(20, 55));
  }

  await sendCdp(target, "Input.dispatchMouseEvent", {
    type: "mousePressed",
    x: point.x,
    y: point.y,
    button: "left",
    buttons: 1,
    clickCount: 1,
    pointerType: "mouse",
  });
  await sleep(randInt(45, 110));
  await sendCdp(target, "Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x: point.x,
    y: point.y,
    button: "left",
    buttons: 0,
    clickCount: 1,
    pointerType: "mouse",
  });

  await sleep(randInt(130, 260));
}

async function waitForProfileHeaderReady(target, timeoutMs) {
  await pollForTruthy(
    async () => {
      const result = await evalInPage(
        target,
        `
          (() => {
            if (!location.pathname.startsWith('/in/')) return false;
            if (document.readyState !== 'complete' && document.readyState !== 'interactive') return false;
            const candidate = Array.from(document.querySelectorAll('button, a'))
              .find((el) => {
                if (!el || typeof el.getBoundingClientRect !== 'function') return false;
                const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                if (text !== 'More') return false;
                const rect = el.getBoundingClientRect();
                if (!rect || rect.width < 30 || rect.height < 20) return false;
                return rect.bottom > 0 && rect.right > 0 && rect.top < window.innerHeight && rect.left < window.innerWidth;
              });
            return Boolean(candidate);
          })();
        `
      );
      return Boolean(result);
    },
    { timeoutMs, intervalMs: 220 }
  );
}

async function waitForMenuItemVisible(target, label, timeoutMs) {
  await pollForTruthy(() => isMenuItemVisible(target, label), {
    timeoutMs,
    intervalMs: 180,
  });
}

async function isMenuItemVisible(target, label) {
  const normalized = escapeForJs(label);
  const visible = await evalInPage(
    target,
    `
      (() => {
        const wanted = "${normalized}".toLowerCase();
        const nodes = Array.from(document.querySelectorAll('li, button, a, div[role="menuitem"], span'));
        for (const node of nodes) {
          const text = (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
          if (text !== wanted) continue;
          const rect = node.getBoundingClientRect();
          if (!rect || rect.width < 40 || rect.height < 15) continue;
          if (rect.bottom <= 0 || rect.right <= 0 || rect.top >= window.innerHeight || rect.left >= window.innerWidth) continue;
          return true;
        }
        return false;
      })();
    `
  );
  return Boolean(visible);
}

async function findClickablePointByText(target, label) {
  const normalized = escapeForJs(label);
  return await evalInPage(
    target,
    `
      (() => {
        const wanted = "${normalized}".toLowerCase();
        const all = Array.from(document.querySelectorAll('button, a, li, div[role="menuitem"], span'));
        const matches = [];
        for (const node of all) {
          const text = (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
          if (text !== wanted) continue;

          let clickable = node;
          while (clickable && clickable !== document.body) {
            const tag = (clickable.tagName || '').toLowerCase();
            const role = (clickable.getAttribute && clickable.getAttribute('role')) || '';
            if (tag === 'button' || tag === 'a' || role === 'menuitem' || tag === 'li' || clickable.onclick) {
              break;
            }
            clickable = clickable.parentElement;
          }
          if (!clickable) continue;

          const rect = clickable.getBoundingClientRect();
          if (!rect || rect.width < 20 || rect.height < 14) continue;
          if (rect.bottom <= 0 || rect.right <= 0 || rect.top >= window.innerHeight || rect.left >= window.innerWidth) continue;

          const style = getComputedStyle(clickable);
          if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity || '1') === 0) continue;

          matches.push({
            x: rect.left + rect.width / 2,
            y: rect.top + rect.height / 2,
            top: rect.top
          });
        }

        if (!matches.length) return null;
        matches.sort((a, b) => a.top - b.top);
        return { x: matches[0].x, y: matches[0].y };
      })();
    `
  );
}

function createPdfDownloadTracker(options) {
  const issuedAtMs = options?.issuedAtMs || Date.now();
  const timeoutMs = options?.timeoutMs || DOWNLOAD_WAIT_TIMEOUT_MS;
  const fallbackFilename = options?.fallbackFilename || DEFAULT_PDF_FILENAME;
  let isClosed = false;
  let trackedId = null;
  let timer = null;
  let resolvePromise;
  let rejectPromise;

  const promise = new Promise((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });

  const finish = (error, payload) => {
    if (isClosed) return;
    isClosed = true;
    cleanup();
    if (error) {
      rejectPromise(error);
    } else {
      resolvePromise(payload);
    }
  };

  const isAfterIssuedAt = (downloadItem) => {
    const startMs = downloadItem?.startTime ? Date.parse(downloadItem.startTime) : 0;
    if (Number.isNaN(startMs)) return false;
    return startMs >= issuedAtMs - 1000;
  };

  const onCreated = async (downloadItem) => {
    if (!isAfterIssuedAt(downloadItem)) return;
    if (!looksLikePdf(downloadItem)) return;

    trackedId = downloadItem.id;
    if (downloadItem.state === "complete") {
      finish(null, toDownloadResult(downloadItem));
      return;
    }

    tryResolveFromSearch();
  };

  const onChanged = async (delta) => {
    if (trackedId == null || delta.id !== trackedId) return;
    if (delta.state?.current === "interrupted") {
      finish(new Error("PDF download was interrupted by the browser."));
      return;
    }
    if (delta.state?.current === "complete") {
      const item = await getDownloadById(trackedId);
      if (item) {
        finish(null, toDownloadResult(item));
      } else {
        finish(null, { downloadId: trackedId, filename: fallbackFilename, state: "complete" });
      }
    }
  };

  const tryResolveFromSearch = async () => {
    if (trackedId == null || isClosed) return;
    const item = await getDownloadById(trackedId);
    if (item?.state === "complete") {
      finish(null, toDownloadResult(item));
    }
  };

  timer = setTimeout(async () => {
    if (trackedId != null) {
      const item = await getDownloadById(trackedId);
      if (item?.state === "in_progress") {
        finish(
          new Error(
            "PDF download started but did not complete in time. Check Chrome downloads for pending confirmation."
          )
        );
        return;
      }
      if (item?.state === "complete") {
        finish(null, toDownloadResult(item));
        return;
      }
    }
    finish(new Error("No PDF download detected after clicking Save to PDF."));
  }, timeoutMs);

  chrome.downloads.onCreated.addListener(onCreated);
  chrome.downloads.onChanged.addListener(onChanged);

  const cleanup = () => {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    chrome.downloads.onCreated.removeListener(onCreated);
    chrome.downloads.onChanged.removeListener(onChanged);
  };

  return { promise, cleanup };
}

function waitForTabComplete(tabId, timeoutMs) {
  return new Promise((resolve, reject) => {
    let done = false;
    const timeout = setTimeout(() => {
      if (done) return;
      done = true;
      chrome.tabs.onUpdated.removeListener(onUpdated);
      reject(new Error("Timed out waiting for LinkedIn profile page to load."));
    }, timeoutMs);

    const onUpdated = (updatedTabId, info, tab) => {
      if (done || updatedTabId !== tabId || info.status !== "complete") return;
      done = true;
      clearTimeout(timeout);
      chrome.tabs.onUpdated.removeListener(onUpdated);
      resolve(tab);
    };

    chrome.tabs.onUpdated.addListener(onUpdated);
  });
}

async function sendCdp(target, method, params) {
  return chrome.debugger.sendCommand(target, method, params || {});
}

async function evalInPage(target, expression) {
  const result = await sendCdp(target, "Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  return result?.result?.value;
}

async function pollForTruthy(checkFn, options) {
  const timeoutMs = options?.timeoutMs ?? 5000;
  const intervalMs = options?.intervalMs ?? 100;
  const deadline = Date.now() + timeoutMs;
  let lastError = null;

  while (Date.now() < deadline) {
    try {
      const ok = await checkFn();
      if (ok) return true;
    } catch (err) {
      lastError = err;
    }
    await sleep(intervalMs);
  }
  if (lastError) throw lastError;
  throw new Error("Timed out waiting for expected page state.");
}

async function safeDetach(target) {
  try {
    await chrome.debugger.detach(target);
  } catch {
    // Ignore detach failures for closed tabs or detached sessions.
  }
}

function sanitizeUrlList(rawUrls) {
  if (!Array.isArray(rawUrls)) return [];
  return rawUrls.map((url) => String(url || "").trim()).filter(Boolean);
}

function validateLinkedInProfileUrl(raw) {
  try {
    const url = new URL(raw);
    if (url.hostname !== "www.linkedin.com") return null;
    if (!url.pathname.startsWith("/in/")) return null;
    return `https://www.linkedin.com${url.pathname}`;
  } catch {
    return null;
  }
}

function buildDesiredPdfFilename(profileUrl) {
  const slug = extractProfileSlugFromUrl(profileUrl);
  return `${slug || "linkedin-profile"}.pdf`;
}

function extractProfileSlugFromUrl(url) {
  try {
    const parsed = new URL(url);
    const parts = parsed.pathname.split("/").filter(Boolean);
    if (parts[0] !== "in" || !parts[1]) return "";
    return parts[1]
      .toLowerCase()
      .replace(/[^a-z0-9-]+/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "");
  } catch {
    return "";
  }
}

function normalizeProfileUrl(url) {
  try {
    const parsed = new URL(url);
    const cleanPath = parsed.pathname.replace(/\/+$/, "").toLowerCase();
    return parsed.origin + cleanPath;
  } catch {
    return url;
  }
}

function fileNameFromPath(path) {
  if (!path) return "";
  const idx = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return idx >= 0 ? path.slice(idx + 1) : path;
}

async function getDownloadById(downloadId) {
  const rows = await chrome.downloads.search({ id: downloadId });
  return rows?.[0] || null;
}

function looksLikePdf(item) {
  const filename = (item?.filename || "").toLowerCase();
  const mime = (item?.mime || "").toLowerCase();
  const finalUrl = (item?.finalUrl || item?.url || "").toLowerCase();
  return filename.endsWith(".pdf") || mime.includes("pdf") || finalUrl.includes(".pdf");
}

function toDownloadResult(item) {
  return {
    downloadId: item.id,
    filename: fileNameFromPath(item.filename || ""),
    state: item.state || "complete",
  };
}

function setPendingFilenameOverride(value) {
  pendingFilenameOverride = value;
}

function clearPendingFilenameOverride() {
  pendingFilenameOverride = null;
}

function handleDeterminingFilename(downloadItem, suggest) {
  try {
    const pending = pendingFilenameOverride;
    if (!pending || !looksLikePdf(downloadItem)) {
      suggest();
      return;
    }
    const startMs = downloadItem?.startTime ? Date.parse(downloadItem.startTime) : Date.now();
    if (Number.isNaN(startMs)) {
      suggest();
      return;
    }
    const ageMs = Math.abs(startMs - pending.issuedAtMs);
    if (ageMs > FILENAME_CORRELATION_WINDOW_MS) {
      suggest();
      return;
    }
    suggest({
      filename: pending.desiredFilename || DEFAULT_PDF_FILENAME,
      conflictAction: "uniquify",
    });
  } catch {
    suggest();
  }
}

function escapeForJs(value) {
  return String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function randInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
