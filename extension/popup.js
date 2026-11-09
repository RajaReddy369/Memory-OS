/**
 * MemoryOS Popup Controller
 */

import { importBrowserHistory } from "./history_importer.js";

document.addEventListener("DOMContentLoaded", async () => {
  const pauseToggle = document.getElementById("pause-toggle");
  const recordingDesc = document.getElementById("recording-desc");
  const backendStatus = document.getElementById("backend-status");
  const connectionIndicator = document.getElementById("connection-indicator");
  const eventCountEl = document.getElementById("event-count");
  const domainNameEl = document.getElementById("domain-name");
  const muteDomainBtn = document.getElementById("mute-domain-btn");
  const apiKeyInput = document.getElementById("api-key-input");
  const saveTokenBtn = document.getElementById("save-token-btn");

  const openWorldBtn = document.getElementById("open-world-btn");
  const openSidepanelBtn = document.getElementById("open-sidepanel-btn");
  const importHistoryBtn = document.getElementById("import-history-btn");
  const importRangeSelect = document.getElementById("import-range-select");
  const importProgressStatus = document.getElementById("import-progress-status");

  let currentDomain = "";
  const API_URL = "http://127.0.0.1:8000";

  // 1. Load initial settings
  const stored = await chrome.storage.local.get(["isRecordingPaused", "apiKey", "eventCounter", "userBlocklist"]);
  const isPaused = !!stored.isRecordingPaused;
  pauseToggle.checked = !isPaused;
  updateRecordingUI(!isPaused);

  if (stored.apiKey) {
    apiKeyInput.value = stored.apiKey;
  }
  eventCountEl.textContent = stored.eventCounter || 0;

  // 2. Identify active tab domain
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab && tab.url && tab.url.startsWith("http")) {
      const parsed = new URL(tab.url);
      currentDomain = parsed.hostname.toLowerCase();
      domainNameEl.textContent = currentDomain;

      const blocklist = stored.userBlocklist || [];
      if (blocklist.includes(currentDomain)) {
        muteDomainBtn.textContent = "Domain Muted";
        muteDomainBtn.disabled = true;
      } else {
        muteDomainBtn.disabled = false;
      }
    }
  } catch (e) {
    domainNameEl.textContent = "—";
  }

  // 3. Check Backend Connectivity and Live Stats
  async function checkBackend() {
    try {
      const res = await fetch(`${API_URL}/api/health`, { method: "GET" });
      if (res.ok) {
        backendStatus.textContent = "Online";
        backendStatus.className = "status-badge online";
        connectionIndicator.textContent = "Connected (127.0.0.1:8000)";

        // Fetch live database metrics
        const token = apiKeyInput.value.trim();
        const sumRes = await fetch(`${API_URL}/api/data/summary`, {
          headers: token ? { "X-MemoryOS-Key": token } : {}
        });
        if (sumRes.ok) {
          const sumData = await sumRes.json();
          eventCountEl.textContent = sumData.total_events;
        }
      } else {
        throw new Error("HTTP " + res.status);
      }
    } catch (err) {
      backendStatus.textContent = "Offline";
      backendStatus.className = "status-badge offline";
      connectionIndicator.textContent = "Backend offline (start server)";
    }
  }
  checkBackend();

  // 4. Open 3D World in Full Tab
  openWorldBtn.addEventListener("click", () => {
    chrome.tabs.create({ url: chrome.runtime.getURL("world.html") });
  });

  // 5. Open Side Panel
  openSidepanelBtn.addEventListener("click", async () => {
    if (chrome.sidePanel && chrome.sidePanel.open) {
      try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (tab && tab.id) {
          await chrome.sidePanel.open({ tabId: tab.id });
          return;
        }
      } catch (e) {
        console.warn("sidePanel.open failed, falling back to tab", e);
      }
    }
    chrome.tabs.create({ url: chrome.runtime.getURL("sidepanel.html") });
  });

  // 6. Import Browser History
  importHistoryBtn.addEventListener("click", async () => {
    const daysBack = parseInt(importRangeSelect.value, 10) || 30;
    importHistoryBtn.disabled = true;
    importProgressStatus.textContent = "Requesting permission...";

    try {
      const result = await importBrowserHistory(
        { daysBack, maxResults: 5000 },
        (p) => {
          importProgressStatus.textContent = p.message || `Processing (${p.current || 0})...`;
        }
      );
      importProgressStatus.textContent = `Done! Imported ${result.count} visits.`;
      checkBackend();
    } catch (err) {
      importProgressStatus.textContent = `Error: ${err.message}`;
    } finally {
      importHistoryBtn.disabled = false;
    }
  });

  // 7. Handle Instant Pause Toggle
  pauseToggle.addEventListener("change", async () => {
    const active = pauseToggle.checked;
    await chrome.storage.local.set({ isRecordingPaused: !active });
    updateRecordingUI(active);

    const token = apiKeyInput.value.trim();
    try {
      await fetch(`${API_URL}/api/recording/toggle?paused=${!active}`, {
        method: "POST",
        headers: token ? { "X-MemoryOS-Key": token } : {}
      });
    } catch (e) {}
  });

  function updateRecordingUI(active) {
    if (active) {
      recordingDesc.textContent = "Recording active";
      recordingDesc.style.color = "var(--success-color)";
    } else {
      recordingDesc.textContent = "Recording PAUSED";
      recordingDesc.style.color = "var(--danger-color)";
    }
  }

  // 8. Handle Mute Domain
  muteDomainBtn.addEventListener("click", async () => {
    if (!currentDomain) return;
    const data = await chrome.storage.local.get(["userBlocklist"]);
    const list = data.userBlocklist || [];
    if (!list.includes(currentDomain)) {
      list.push(currentDomain);
      await chrome.storage.local.set({ userBlocklist: list });
      muteDomainBtn.textContent = "Domain Muted";
      muteDomainBtn.disabled = true;
    }
  });

  // 9. Handle Save Token
  saveTokenBtn.addEventListener("click", async () => {
    const token = apiKeyInput.value.trim();
    await chrome.storage.local.set({ apiKey: token });
    saveTokenBtn.textContent = "Saved!";
    setTimeout(() => {
      saveTokenBtn.textContent = "Save";
    }, 1500);
    checkBackend();
  });
});
