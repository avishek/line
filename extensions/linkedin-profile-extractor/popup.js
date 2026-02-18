const fileInputEl = document.getElementById("urlFile");
const startBtnEl = document.getElementById("startBtn");
const statusEl = document.getElementById("status");
const progressEl = document.getElementById("progress");
const resultsEl = document.getElementById("results");

const RESULT_LINE_LIMIT = 300;

setStatus("Select a .txt file to begin.");
setProgress("");
setResults([]);

startBtnEl.addEventListener("click", onStartBatchClick);

function setStatus(msg, kind = "") {
  statusEl.textContent = msg;
  statusEl.className = kind;
}

function setProgress(msg) {
  progressEl.textContent = msg;
}

function setResults(lines) {
  const limited = lines.slice(-RESULT_LINE_LIMIT);
  resultsEl.textContent = limited.join("\n");
}

function setBusy(busy) {
  fileInputEl.disabled = busy;
  startBtnEl.disabled = busy;
  startBtnEl.textContent = busy ? "Running..." : "Start Batch Download";
}

async function onStartBatchClick() {
  const file = fileInputEl.files?.[0];
  if (!file) {
    setStatus("Choose a text file with one LinkedIn profile URL per line.", "error");
    return;
  }

  setBusy(true);
  setStatus("Reading URL file...");
  setProgress("");
  setResults([]);

  try {
    const text = await file.text();
    const urls = parseUrlFile(text);
    if (!urls.length) {
      throw new Error("No URLs found in file. Add one LinkedIn profile URL per line.");
    }

    const lines = [`Loaded ${urls.length} URL(s).`];
    setResults(lines);
    setStatus("Starting batch resume download...");
    setProgress(`0 / ${urls.length}`);

    const response = await runBatchViaPort(urls, (event) => {
      if (event?.type === "progress") {
        setStatus(`Processing ${event.current}/${event.total}...`);
        setProgress(`${event.current} / ${event.total}`);
      }
      if (event?.type === "item_result") {
        const item = event.item || {};
        const currentLines = resultsEl.textContent ? resultsEl.textContent.split("\n") : [];
        const lineNumber = Number.isFinite(item.index) ? item.index + 1 : "?";
        if (item.ok) {
          currentLines.push(`${lineNumber}. OK  ${item.url} -> ${item.filename || "downloaded"}`);
        } else {
          currentLines.push(`${lineNumber}. ERR ${item.url || "unknown"} -> ${item.error || "failed"}`);
        }
        setResults(currentLines);
      }
    });

    const results = Array.isArray(response.results) ? response.results : [];
    const total = response.total ?? results.length;
    const successCount = response.successCount ?? results.filter((r) => r?.ok).length;
    const failureCount = response.failureCount ?? Math.max(0, total - successCount);

    setProgress(`${total} / ${total}`);

    const resultLines = [
      `Completed ${total} URL(s): ${successCount} success, ${failureCount} failed.`,
      "",
    ];
    for (const item of results) {
      const index = Number.isFinite(item?.index) ? item.index + 1 : "?";
      if (item?.ok) {
        resultLines.push(`${index}. OK  ${item.url} -> ${item.filename || "downloaded"}`);
      } else {
        resultLines.push(`${index}. ERR ${item?.url || "unknown"} -> ${item?.error || "failed"}`);
      }
    }
    setResults(resultLines);

    if (failureCount > 0) {
      setStatus(`Batch finished with ${failureCount} failure(s).`, "error");
    } else {
      setStatus("Batch completed successfully.", "ok");
    }
  } catch (err) {
    setStatus(err?.message || "Batch run failed", "error");
  } finally {
    setBusy(false);
  }
}

function parseUrlFile(text) {
  return String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function runBatchViaPort(urls, onEvent) {
  return new Promise((resolve, reject) => {
    const port = chrome.runtime.connect({ name: "batch_resume_download" });
    let settled = false;

    const finish = (error, result) => {
      if (settled) return;
      settled = true;
      try {
        port.disconnect();
      } catch {
        // Ignore disconnect failures.
      }
      if (error) {
        reject(error);
      } else {
        resolve(result);
      }
    };

    port.onMessage.addListener((message) => {
      onEvent?.(message);
      if (message?.type !== "done") {
        return;
      }
      if (!message.ok) {
        finish(new Error(message.error || "Batch run failed"));
        return;
      }
      finish(null, message);
    });

    port.onDisconnect.addListener(() => {
      if (!settled) {
        finish(new Error("Batch process disconnected unexpectedly."));
      }
    });

    port.postMessage({
      type: "start_batch_resume_download",
      urls,
    });
  });
}
