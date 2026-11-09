/**
 * MemoryOS MV3 Side Panel Controller
 * Fast, docked AI Copilot with live citations and recent activity feed.
 */

document.addEventListener("DOMContentLoaded", async () => {
  const API_URL = "http://127.0.0.1:8000";
  const backendIndicator = document.getElementById("backend-indicator");
  const openWorldBtn = document.getElementById("open-world-btn");

  const tabChat = document.getElementById("tab-chat");
  const tabActivity = document.getElementById("tab-activity");
  const chatSection = document.getElementById("chat-section");
  const activitySection = document.getElementById("activity-section");

  const chatHistory = document.getElementById("chat-history");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const activityList = document.getElementById("activity-list");
  const refreshActivityBtn = document.getElementById("refresh-activity-btn");

  let apiKey = "";
  const stored = await chrome.storage.local.get(["apiKey"]);
  if (stored.apiKey) {
    apiKey = stored.apiKey;
  } else {
    try {
      const authRes = await fetch(`${API_URL}/api/auth/token`);
      if (authRes.ok) {
        const authData = await authRes.json();
        if (authData.token) {
          apiKey = authData.token;
          await chrome.storage.local.set({ apiKey });
        }
      }
    } catch {}
  }

  // 1. Check Backend Connectivity
  async function checkBackend() {
    try {
      const res = await fetch(`${API_URL}/api/health`);
      if (res.ok) {
        backendIndicator.textContent = "Online";
        backendIndicator.className = "status-pill online";
      } else {
        throw new Error();
      }
    } catch {
      backendIndicator.textContent = "Offline";
      backendIndicator.className = "status-pill offline";
    }
  }
  checkBackend();

  // 2. Tab Navigation
  tabChat.addEventListener("click", () => {
    tabChat.classList.add("active");
    tabActivity.classList.remove("active");
    chatSection.classList.add("active");
    activitySection.classList.remove("active");
  });

  tabActivity.addEventListener("click", () => {
    tabActivity.classList.add("active");
    tabChat.classList.remove("active");
    activitySection.classList.add("active");
    chatSection.classList.remove("active");
    loadRecentActivity();
  });

  // 3. Open 3D World in Full Tab
  openWorldBtn.addEventListener("click", () => {
    chrome.tabs.create({ url: chrome.runtime.getURL("world.html") });
  });

  // 4. Memory Chat
  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = chatInput.value.trim();
    if (!query) return;

    appendBubble("user", query);
    chatInput.value = "";

    const loadingBubble = appendBubble("ai", "Searching memory & synthesizing citations...");

    try {
      const res = await fetch(`${API_URL}/api/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(apiKey ? { "X-MemoryOS-Key": apiKey } : {})
        },
        body: JSON.stringify({ message: query, stream: false })
      });

      if (!res.ok) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();
      loadingBubble.remove();
      appendBubble("ai", data.answer, data.citations);

      // Light up first cited node in 3D world
      if (data.citations && data.citations.length > 0) {
        highlightNodeIn3D(data.citations[0].event_id);
      }
    } catch (err) {
      loadingBubble.innerHTML = `<p style="color:#f87171;">⚠️ MemoryOS query failed: ${err.message || "Backend unreachable"}. Make sure backend is running at 127.0.0.1:8000.</p>`;
    }
  });

  function appendBubble(sender, text, citations = []) {
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${sender}`;

    const textEl = document.createElement("p");
    textEl.textContent = text;
    bubble.appendChild(textEl);

    if (citations && citations.length > 0) {
      const citBox = document.createElement("div");
      citBox.className = "citations-box";

      citations.slice(0, 4).forEach((cit) => {
        const pill = document.createElement("div");
        pill.className = "citation-pill";
        pill.innerHTML = `
          <strong>[#${cit.event_id}] ${escapeHtml(cit.title || cit.domain || "Activity")}</strong>
          <div class="citation-meta">${cit.time_str || ""} • ${escapeHtml(cit.snippet?.slice(0, 75) || "")}...</div>
        `;

        pill.addEventListener("click", () => {
          highlightNodeIn3D(cit.event_id);
          if (cit.url) {
            chrome.tabs.create({ url: cit.url });
          }
        });

        citBox.appendChild(pill);
      });

      bubble.appendChild(citBox);
    }

    chatHistory.appendChild(bubble);
    chatHistory.scrollTop = chatHistory.scrollHeight;
    return bubble;
  }

  function highlightNodeIn3D(eventId) {
    try {
      chrome.runtime.sendMessage({
        type: "HIGHLIGHT_NODE",
        nodeId: `event_${eventId}`
      });
    } catch {}
  }

  // 5. Recent Activity Feed
  async function loadRecentActivity() {
    activityList.innerHTML = '<div class="empty-state">Loading recent events...</div>';
    try {
      const res = await fetch(`${API_URL}/api/events/recent?limit=30`, {
        headers: apiKey ? { "X-MemoryOS-Key": apiKey } : {}
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      const events = await res.json();
      if (!events || events.length === 0) {
        activityList.innerHTML = '<div class="empty-state">No activity events recorded yet.</div>';
        return;
      }

      activityList.innerHTML = "";
      events.forEach((ev) => {
        const item = document.createElement("div");
        item.className = "activity-item";

        const title = ev.title || ev.domain || ev.app_name || `Event ${ev.id}`;
        const timeStr = new Date(ev.timestamp * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        const sourceStr = ev.source || "local";

        item.innerHTML = `
          <div class="activity-title" title="${escapeHtml(title)}">${escapeHtml(title)}</div>
          <div class="activity-sub">
            <span>${escapeHtml(ev.domain || ev.app_name || sourceStr)}</span>
            <span>${timeStr}</span>
          </div>
        `;

        item.addEventListener("click", () => {
          highlightNodeIn3D(ev.id);
          if (ev.url) {
            chrome.tabs.create({ url: ev.url });
          }
        });

        activityList.appendChild(item);
      });
    } catch (e) {
      activityList.innerHTML = '<div class="empty-state" style="color:#f87171;">Could not load recent activity from backend.</div>';
    }
  }

  refreshActivityBtn.addEventListener("click", loadRecentActivity);

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }
});

