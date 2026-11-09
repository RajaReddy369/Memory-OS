/**
 * MemoryOS Background Service Worker (Manifest V3)
 * Manages event buffering, transmission, tab lifecycle, and security headers.
 */

const DEFAULT_API_URL = "http://127.0.0.1:8000";
let eventQueue = [];
let isFlushing = false;

// 1. Skip all incognito tabs and windows
function isIncognito(tab) {
  return tab && tab.incognito === true;
}

// 2. Fetch or initialize settings
async function getSettings() {
  const data = await chrome.storage.local.get(["apiUrl", "apiKey", "isRecordingPaused", "eventCounter"]);
  return {
    apiUrl: data.apiUrl || DEFAULT_API_URL,
    apiKey: data.apiKey || "",
    isRecordingPaused: !!data.isRecordingPaused,
    eventCounter: data.eventCounter || 0
  };
}

// 3. Queue and flush events to MemoryOS local API
async function queueEvent(eventData) {
  const settings = await getSettings();
  if (settings.isRecordingPaused) {
    return;
  }

  eventQueue.push(eventData);

  // Update session event counter for popup UI
  chrome.storage.local.set({ eventCounter: settings.eventCounter + 1 });

  flushQueue();
}

async function flushQueue() {
  if (isFlushing || eventQueue.length === 0) return;
  isFlushing = true;

  const settings = await getSettings();
  const toSend = [...eventQueue];
  eventQueue = [];

  try {
    const headers = {
      "Content-Type": "application/json"
    };
    if (settings.apiKey) {
      headers["X-MemoryOS-Key"] = settings.apiKey;
    }

    // Send single or batch depending on count
    const endpoint = toSend.length === 1 
      ? `${settings.apiUrl}/api/events/ingest`
      : `${settings.apiUrl}/api/events/batch`;

    const body = toSend.length === 1
      ? JSON.stringify(toSend[0])
      : JSON.stringify({ events: toSend });

    const response = await fetch(endpoint, {
      method: "POST",
      headers: headers,
      body: body
    });

    if (!response.ok) {
      // Re-queue on failure (keep up to 300 events)
      eventQueue = [...toSend.slice(-200), ...eventQueue];
      console.warn("MemoryOS Ingestion returned status:", response.status);
    }
  } catch (err) {
    // Backend offline: restore unsent events to queue
    eventQueue = [...toSend.slice(-200), ...eventQueue];
    console.debug("MemoryOS backend currently unreachable, buffered in queue.");
  } finally {
    isFlushing = false;
  }
}

// Flush queue periodically
setInterval(flushQueue, 5000);

// 4. Listen for runtime messages from content script or popup
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (sender.tab && isIncognito(sender.tab)) {
    sendResponse({ status: "ignored_incognito" });
    return true;
  }

  if (message.type === "CHECK_HEALTH") {
    getSettings().then(settings => {
      fetch(`${settings.apiUrl}/api/health`)
        .then(res => res.json())
        .then(data => sendResponse({ status: "ok", data }))
        .catch(err => sendResponse({ status: "error", error: err.message }));
    });
    return true;
  }

  if (message.payload) {
    queueEvent(message.payload);
    sendResponse({ status: "queued" });
    return true;
  }
});

// 5. Track Tab Activation (Time & Context Switches)
let lastActiveTab = { id: null, url: null, title: null, startTime: Date.now() };

chrome.tabs.onActivated.addListener(async (activeInfo) => {
  try {
    const tab = await chrome.tabs.get(activeInfo.tabId);
    if (!tab || isIncognito(tab)) return;

    const now = Date.now();
    // Record duration on previous tab
    if (lastActiveTab.url && lastActiveTab.id !== tab.id) {
      const duration = Math.round((now - lastActiveTab.startTime) / 1000);
      if (duration >= 3) {
        queueEvent({
          event_type: "tab_switch",
          source: "browser",
          timestamp: now / 1000,
          url: lastActiveTab.url,
          title: lastActiveTab.title,
          duration: duration
        });
      }
    }

    lastActiveTab = {
      id: tab.id,
      url: tab.url,
      title: tab.title,
      startTime: now
    };
  } catch (e) {
    // Tab might have been closed immediately
  }
});
