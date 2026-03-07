"use strict";

const DEBUGGER_VERSION = "1.3";
const TAB_READY_TIMEOUT_MS = 45000;
const SEARCH_RESULTS_TIMEOUT_MS = 25000;
const PROFILE_READY_TIMEOUT_MS = 25000;
const CLICK_RETRY_TIMEOUT_MS = 15000;

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg?.type !== "run_connected_search") {
    return false;
  }

  runConnectedSearch(msg.queryName)
    .then((result) => sendResponse({ ok: true, ...result }))
    .catch((error) => {
      sendResponse({ ok: false, error: error?.message || "Connected search failed" });
    });

  return true;
});

async function runConnectedSearch(rawQueryName) {
  const queryName = String(rawQueryName || "").trim();
  if (!queryName) {
    throw new Error("Enter a candidate name to search.");
  }

  const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!activeTab?.id) {
    throw new Error("No active tab found.");
  }

  const tabId = activeTab.id;
  const searchUrl = buildLinkedInPeopleSearchUrl(queryName);
  await chrome.tabs.update(tabId, { active: true, url: searchUrl });
  await waitForTabComplete(tabId, TAB_READY_TIMEOUT_MS);
  await sleep(1200);

  const target = { tabId };
  await chrome.debugger.attach(target, DEBUGGER_VERSION);

  let profileUrl = "";
  let hasMutualConnections = false;
  try {
    await sendCdp(target, "Page.enable");
    await sendCdp(target, "Runtime.enable");
    await sendCdp(target, "DOM.enable");
    await sendCdp(target, "Overlay.enable");

    await waitForSearchResultsReady(target, SEARCH_RESULTS_TIMEOUT_MS);
    await clickFirstSearchResult(target, CLICK_RETRY_TIMEOUT_MS);
    await waitForProfileReady(target, PROFILE_READY_TIMEOUT_MS);

    profileUrl = await readCanonicalProfileUrl(target);
    if (!profileUrl) {
      throw new Error("Profile URL could not be determined after opening the first result.");
    }
    hasMutualConnections = await detectMutualConnections(target);
  } finally {
    await safeDetach(target);
  }

  const filename = buildResultFilename(queryName);
  const payload = buildResultPayload({
    queryName,
    profileUrl,
    hasMutualConnections,
  });
  const downloadId = await downloadTextFile(payload, filename);

  return {
    queryName,
    profileUrl,
    hasMutualConnections,
    filename,
    downloadId,
  };
}

function buildLinkedInPeopleSearchUrl(queryName) {
  const url = new URL("https://www.linkedin.com/search/results/people/");
  url.searchParams.set("keywords", queryName);
  url.searchParams.set("network", JSON.stringify(["F", "S"]));
  url.searchParams.set("origin", "FACETED_SEARCH");
  url.searchParams.set("sid", "f~o");
  return url.toString();
}

async function waitForSearchResultsReady(target, timeoutMs) {
  await pollForTruthy(
    async () => {
      const ready = await evalInPage(
        target,
        `
          (() => {
            const onSearchPage = location.pathname.startsWith('/search/results/people');
            if (!onSearchPage) return false;
            const links = Array.from(document.querySelectorAll('a[href*="/in/"]'));
            for (const link of links) {
              const rect = link.getBoundingClientRect();
              if (!rect || rect.width < 40 || rect.height < 14) continue;
              if (rect.bottom <= 0 || rect.right <= 0 || rect.top >= window.innerHeight || rect.left >= window.innerWidth) continue;
              const style = getComputedStyle(link);
              if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity || '1') === 0) continue;
              return true;
            }
            return false;
          })();
        `
      );
      return Boolean(ready);
    },
    { timeoutMs, intervalMs: 220 }
  );
}

async function clickFirstSearchResult(target, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let lastError = "Could not find a visible profile result";

  while (Date.now() < deadline) {
    const point = await getFirstResultClickablePoint(target);
    if (!point) {
      await sleep(200);
      continue;
    }

    try {
      await humanLikeClick(target, point);
      return;
    } catch (err) {
      lastError = err?.message || "Failed dispatching click event";
      await sleep(180);
    }
  }

  throw new Error(`Failed to click first search result. ${lastError}`);
}

async function getFirstResultClickablePoint(target) {
  return await evalInPage(
    target,
    `
      (() => {
        const candidates = Array.from(document.querySelectorAll('a[href*="/in/"]'));
        const matches = [];

        for (const anchor of candidates) {
          const href = anchor.getAttribute('href') || '';
          if (!href.includes('/in/')) continue;

          const rect = anchor.getBoundingClientRect();
          if (!rect || rect.width < 40 || rect.height < 14) continue;
          if (rect.bottom <= 0 || rect.right <= 0 || rect.top >= window.innerHeight || rect.left >= window.innerWidth) continue;

          const style = getComputedStyle(anchor);
          if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity || '1') === 0) continue;

          matches.push({
            top: rect.top,
            left: rect.left,
            x: rect.left + rect.width / 2,
            y: rect.top + rect.height / 2
          });
        }

        if (!matches.length) return null;
        matches.sort((a, b) => (a.top - b.top) || (a.left - b.left));
        return { x: matches[0].x, y: matches[0].y };
      })();
    `
  );
}

async function waitForProfileReady(target, timeoutMs) {
  await pollForTruthy(
    async () => {
      const ready = await evalInPage(
        target,
        `
          (() => {
            if (!location.pathname.startsWith('/in/')) return false;
            if (document.readyState !== 'complete' && document.readyState !== 'interactive') return false;
            const main = document.querySelector('main');
            if (!main) return false;
            const title = document.querySelector('h1');
            return Boolean(title && (title.innerText || title.textContent || '').trim());
          })();
        `
      );
      return Boolean(ready);
    },
    { timeoutMs, intervalMs: 220 }
  );
}

async function readCanonicalProfileUrl(target) {
  const raw = await evalInPage(
    target,
    `
      (() => {
        if (!location.pathname.startsWith('/in/')) return '';
        return location.origin + location.pathname;
      })();
    `
  );
  return String(raw || "").replace(/\/+$/, "");
}

async function detectMutualConnections(target) {
  const result = await evalInPage(
    target,
    `
      (() => {
        const text = (document.body?.innerText || '').replace(/\\s+/g, ' ').toLowerCase();
        const phraseMatch = text.includes('mutual connection') || text.includes('mutual connections');

        const topCandidates = Array.from(document.querySelectorAll('section, div'));
        let blockMatch = false;
        for (const node of topCandidates) {
          const rect = node.getBoundingClientRect();
          if (!rect || rect.top < -20 || rect.top > window.innerHeight * 0.7) continue;
          if (rect.width < 120 || rect.height < 24) continue;
          const snippet = (node.innerText || '').replace(/\\s+/g, ' ').trim().toLowerCase();
          if (!snippet) continue;
          const mentionsConnections = /\\b\\d+\\s+connections?\\b/.test(snippet) || snippet.includes('connection');
          const likelyTopCard = snippet.includes('contact info') || snippet.includes('message') || snippet.includes('connect');
          if (mentionsConnections && likelyTopCard) {
            blockMatch = true;
            break;
          }
        }

        return phraseMatch || blockMatch;
      })();
    `
  );
  return Boolean(result);
}

function buildResultPayload(input) {
  const lines = [
    `query_name: ${input.queryName}`,
    `profile_url: ${input.profileUrl}`,
    `has_mutual_connections: ${input.hasMutualConnections ? "true" : "false"}`,
  ];
  return lines.join("\n") + "\n";
}

function buildResultFilename(queryName) {
  const slug = queryName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "") || "candidate";

  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
  return `linkedin-connected-search-${slug}-${stamp}.txt`;
}

async function downloadTextFile(contents, filename) {
  const url = `data:text/plain;charset=utf-8,${encodeURIComponent(contents)}`;
  return await chrome.downloads.download({
    url,
    filename,
    saveAs: false,
    conflictAction: "uniquify",
  });
}

async function humanLikeClick(target, point) {
  const start = {
    x: point.x + randInt(-12, -4),
    y: point.y + randInt(-9, -3),
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
  await sleep(randInt(45, 95));
  await sendCdp(target, "Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x: point.x,
    y: point.y,
    button: "left",
    buttons: 0,
    clickCount: 1,
    pointerType: "mouse",
  });

  await sleep(randInt(120, 220));
}

function waitForTabComplete(tabId, timeoutMs) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      chrome.tabs.onUpdated.removeListener(onUpdated);
      reject(new Error("Timed out waiting for LinkedIn page to load."));
    }, timeoutMs);

    const onUpdated = (updatedTabId, info, tab) => {
      if (settled || updatedTabId !== tabId || info.status !== "complete") {
        return;
      }
      settled = true;
      clearTimeout(timer);
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
  const intervalMs = options?.intervalMs ?? 120;
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

  if (lastError) {
    throw lastError;
  }
  throw new Error("Timed out waiting for expected LinkedIn page state.");
}

async function safeDetach(target) {
  try {
    await chrome.debugger.detach(target);
  } catch {
    // Ignore detach failures for closed tabs or detached sessions.
  }
}

function randInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
