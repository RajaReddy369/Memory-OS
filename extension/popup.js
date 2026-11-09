/**
 * MemoryOS Popup Controller
 */

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

  // 3. Check Backend Connectivity
  async function checkBackend() {
    try {
      const res = await fetch(`${API_URL}/api/health`, { method: "GET" });
      if (res.ok) {
        backendStatus.textContent = "Online";
        backendStatus.className = "status-badge online";
        connectionIndicator.textContent = "Connected (127.0.0.1:8000)";
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

  // 4. Handle Instant Pause Toggle
  pauseToggle.addEventListener("change", async () => {
    const active = pauseToggle.checked;
    await chrome.storage.local.set({ isRecordingPaused: !active });
    updateRecordingUI(active);

    // Sync with backend if online
    const token = apiKeyInput.value.trim();
    try {
      await fetch(`${API_URL}/api/recording/toggle?paused=${!active}`, {
        method: "POST",
        headers: token ? { "X-MemoryOS-Key": token } : {}
      });
    } catch (e) {
      // Backend may be offline, local setting persists regardless
    }
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

  // 5. Handle Mute Domain
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

  // 6. Handle Save Token
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

