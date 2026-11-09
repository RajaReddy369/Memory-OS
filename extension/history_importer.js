/**
 * MemoryOS Edge & Chrome Browser History Importer
 * Safely imports past browsing history, strips secrets, extracts search queries,
 * and feeds events to MemoryOS local backend.
 */

const DEFAULT_BLOCKED_DOMAINS = [
  "accounts.google.com",
  "login.microsoftonline.com",
  "login.live.com",
  "auth0.com",
  "okta.com",
  "chase.com",
  "bankofamerica.com",
  "wellsfargo.com",
  "paypal.com",
  "1password.com",
  "bitwarden.com",
  "lastpass.com",
  "dashlane.com"
];

function extractDomain(urlStr) {
  try {
    const parsed = new URL(urlStr);
    return parsed.hostname.toLowerCase();
  } catch {
    return "";
  }
}

function isDomainBlocked(domain, userBlocklist = []) {
  if (!domain) return true;
  const dom = domain.toLowerCase();
  for (const b of DEFAULT_BLOCKED_DOMAINS) {
    if (dom === b || dom.endsWith("." + b)) return true;
  }
  for (const b of userBlocklist) {
    if (dom === b || dom.endsWith("." + b)) return true;
  }
  return false;
}

function scrubUrl(rawUrl) {
  try {
    const parsed = new URL(rawUrl);
    const params = new URLSearchParams(parsed.search);
    const SENSITIVE_KEYS = ["token", "access_token", "auth", "key", "secret", "password", "session_id", "apikey", "code", "jwt"];
    for (const key of Array.from(params.keys())) {
      if (SENSITIVE_KEYS.some(sk => key.toLowerCase().includes(sk))) {
        params.set(key, "[REDACTED]");
      }
    }
    parsed.search = params.toString();
    return parsed.toString();
  } catch {
    return rawUrl;
  }
}

function extractSearchQuery(rawUrl) {
  try {
    const parsed = new URL(rawUrl);
    const domain = parsed.hostname.toLowerCase();
    const params = parsed.searchParams;

    if (domain.includes("google.")) {
      const q = params.get("q");
      if (q) return { query: q, engine: "Google" };
    }
    if (domain.includes("bing.")) {
      const q = params.get("q");
      if (q) return { query: q, engine: "Bing" };
    }
    if (domain.includes("duckduckgo.")) {
      const q = params.get("q");
      if (q) return { query: q, engine: "DuckDuckGo" };
    }
    if (domain.includes("youtube.")) {
      const q = params.get("search_query") || params.get("q");
      if (q) return { query: q, engine: "YouTube" };
    }
    if (domain.includes("github.")) {
      const q = params.get("q");
      if (q) return { query: q, engine: "GitHub" };
    }
    if (domain.includes("reddit.")) {
      const q = params.get("q");
      if (q) return { query: q, engine: "Reddit" };
    }
    if (domain.includes("wikipedia.")) {
      const q = params.get("search");
      if (q) return { query: q, engine: "Wikipedia" };
    }

    // Generic fallback query parameters
    for (const p of ["q", "query", "search", "s", "k"]) {
      const val = params.get(p);
      if (val && val.trim().length > 1) {
        return { query: val.trim(), engine: "Search" };
      }
    }
  } catch {}
  return null;
}

export async function requestHistoryPermission() {
  if (typeof chrome === "undefined" || !chrome.permissions) {
    throw new Error("Permissions API unavailable in this context.");
  }
  return await chrome.permissions.request({ permissions: ["history"] });
}

export async function importBrowserHistory(options = {}, onProgress = () => {}) {
  const granted = await requestHistoryPermission();
  if (!granted) {
    throw new Error("History permission was not granted by user.");
  }

  const daysBack = options.daysBack || 30;
  const maxResults = options.maxResults || 5000;
  const startTime = options.startTime || (Date.now() - daysBack * 86400 * 1000);
  const endTime = options.endTime || Date.now();

  onProgress({ phase: "searching", message: "Scanning browser history entries..." });

  const items = await chrome.history.search({
    text: "",
    startTime,
    endTime,
    maxResults
  });

  const stored = await chrome.storage.local.get(["apiKey", "userBlocklist"]);
  const apiKey = stored.apiKey || "";
  const userBlocklist = stored.userBlocklist || [];

  const validItems = [];
  for (const item of items) {
    if (!item.url || !item.url.startsWith("http")) continue;
    const dom = extractDomain(item.url);
    if (isDomainBlocked(dom, userBlocklist)) continue;
    validItems.push(item);
  }

  onProgress({ phase: "processing", total: validItems.length, current: 0, message: `Found ${validItems.length} valid history entries to import...` });

  let totalImported = 0;
  const batchSize = 100;

  for (let i = 0; i < validItems.length; i += batchSize) {
    const chunk = validItems.slice(i, i + batchSize);
    const batchEvents = [];

    for (const item of chunk) {
      const scrubbed = scrubUrl(item.url);
      const domain = extractDomain(item.url);
      const searchExtracted = extractSearchQuery(item.url);
      const ts = (item.lastVisitTime || Date.now()) / 1000.0;

      // Primary page visit event
      const pageEvent = {
        event_type: "page_visit",
        source: "edge_history",
        timestamp: ts,
        url: scrubbed,
        domain: domain,
        title: item.title || domain,
        app_name: "Edge",
        duration: 0.0,
        text_content: "",
        metadata_json: JSON.stringify({
          metadata_only: true,
          visit_count: item.visitCount || 1,
          typed_count: item.typedCount || 0
        })
      };
      batchEvents.push(pageEvent);

      // If URL contains search query, store linked search_query event
      if (searchExtracted) {
        batchEvents.push({
          event_type: "search_query",
          source: "edge_history",
          timestamp: ts + 0.001,
          url: scrubbed,
          domain: domain,
          title: `${searchExtracted.engine} Search: ${searchExtracted.query}`,
          app_name: "Edge",
          duration: 0.0,
          text_content: searchExtracted.query,
          metadata_json: JSON.stringify({
            query: searchExtracted.query,
            engine: searchExtracted.engine,
            extracted_from_url: true,
            source: "edge_history"
          })
        });
      }
    }

    if (batchEvents.length > 0) {
      const res = await fetch("http://127.0.0.1:8000/api/events/batch", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(apiKey ? { "X-MemoryOS-Key": apiKey } : {})
        },
        body: JSON.stringify(batchEvents)
      });

      if (!res.ok) {
        throw new Error(`Backend ingestion returned HTTP ${res.status}`);
      }
      totalImported += batchEvents.length;
    }

    onProgress({
      phase: "importing",
      total: validItems.length,
      current: Math.min(i + batchSize, validItems.length),
      importedCount: totalImported,
      message: `Imported ${totalImported} events (${Math.min(i + batchSize, validItems.length)}/${validItems.length} pages)...`
    });
  }

  // Notify any open 3D World or Side Panel tabs
  try {
    chrome.runtime.sendMessage({ type: "DATA_UPDATED", count: totalImported });
  } catch {}

  onProgress({ phase: "done", importedCount: totalImported, message: `Import complete! Saved ${totalImported} events.` });
  return { success: true, count: totalImported };
}
