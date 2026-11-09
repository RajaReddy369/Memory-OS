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

// Automatically sync security token from local backend if missing or rotated
async function autoSyncToken(apiUrl = DEFAULT_API_URL) {
  try {
    const res = await fetch(`${apiUrl}/api/auth/token`);
    if (res.ok) {
      const data = await res.json();
      if (data && data.token) {
        await chrome.storage.local.set({ apiKey: data.token });
        console.info("MemoryOS security token synced successfully from backend.");
        return data.token;
      }
    }
  } catch (err) {
    console.debug("MemoryOS backend token auto-sync offline/deferred:", err.message);
  }
  return null;
}

// Auto-sync token on service worker startup and inject content script into existing tabs
chrome.runtime.onInstalled.addListener(async () => {
  await autoSyncToken();
  try {
    const tabs = await chrome.tabs.query({ url: ["http://*/*", "https://*/*"] });
    for (const tab of tabs) {
      if (!isIncognito(tab) && tab.id) {
        chrome.scripting.executeScript({
          target: { tabId: tab.id },
          files: ["content.js"]
        }).catch(() => {});
      }
    }
  } catch (e) {
    // Ignore tab script injection warnings on protected browser tabs
  }
});

// Run token sync on initial background worker activation
autoSyncToken();

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
  let apiKey = settings.apiKey;
  if (!apiKey) {
    apiKey = await autoSyncToken(settings.apiUrl);
  }

  const toSend = [...eventQueue];
  eventQueue = [];

  try {
    const headers = {
      "Content-Type": "application/json"
    };
    if (apiKey) {
      headers["X-MemoryOS-Key"] = apiKey;
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

    if (response.status === 401) {
      // Token mismatch or expired: re-sync token immediately and re-queue events
      console.warn("MemoryOS Ingestion 401 Unauthorized: Attempting automatic token sync...");
      const refreshedToken = await autoSyncToken(settings.apiUrl);
      eventQueue = [...toSend, ...eventQueue];
      return;
    }

    if (!response.ok) {
      // Re-queue on other failure (keep up to 300 events)
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
    const payload = message.payload;
    // Attach referrer from previous active tab if not already present
    if (!payload.referrer_url && lastActiveTab.url && lastActiveTab.url !== payload.url) {
      payload.referrer_url = lastActiveTab.url;
    }
    queueEvent(payload);
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

