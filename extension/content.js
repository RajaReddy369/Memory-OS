/**
 * MemoryOS Content Script
 * Captures clean page text, debounced form typing, and highlights with strict privacy exclusions.
 */

(function () {
  // 1. HARD EXCLUSION: Never run or capture in Incognito / Private browsing windows
  if (chrome.extension && chrome.extension.inIncognitoContext) {
    return;
  }

  // 2. Client-side domain exclusions
  const hostname = window.location.hostname.toLowerCase();
  const SENSITIVE_KEYWORDS = ["bank", "chase", "paypal", "fidelity", "wellsfargo", "login.live", "accounts.google", "auth0", "1password", "bitwarden", "lastpass"];
  if (SENSITIVE_KEYWORDS.some(keyword => hostname.includes(keyword))) {
    return;
  }

  // Check user pause setting before executing
  chrome.storage.local.get(["isRecordingPaused", "userBlocklist"], (data) => {
    if (data.isRecordingPaused) {
      return;
    }

    const blocklist = data.userBlocklist || [];
    if (blocklist.some(domain => hostname.endsWith(domain.toLowerCase()))) {
      return;
    }

    initCapture();
  });

  // Client-side quick secret scrubber (matches backend rules)
  function scrubText(text) {
    if (!text) return "";
    return text
      .replace(/sk-[A-Za-z0-9_-]{20,}/gi, "[REDACTED_OPENAI_KEY]")
      .replace(/sk-ant-[A-Za-z0-9_-]{20,}/gi, "[REDACTED_ANTHROPIC_KEY]")
      .replace(/\b(AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}\b/g, "[REDACTED_AWS_KEY]")
      .replace(/\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,255}\b/g, "[REDACTED_GITHUB_TOKEN]")
      .replace(/\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g, "[REDACTED_JWT]")
      .replace(/\b(?:\d{4}[-\s]?){3}\d{4}\b|\b3[47]\d{13}\b/g, "[REDACTED_CARD_NUMBER]")
      .replace(/\b\d{3}-\d{2}-\d{4}\b/g, "[REDACTED_SSN]");
  }

  function extractCleanPageText() {
    // Clone document body to safely strip unwanted nodes
    try {
      const clone = document.body.cloneNode(true);
      const elementsToRemove = clone.querySelectorAll("script, style, noscript, svg, nav, footer, header, [aria-hidden='true'], [role='navigation']");
      elementsToRemove.forEach(el => el.remove());

      // Get readable inner text
      const rawText = clone.innerText || clone.textContent || "";
      const cleaned = rawText.replace(/\s+/g, " ").trim();
      return cleaned.slice(0, 40000); // Cap at ~40k characters to avoid memory bloating
    } catch (e) {
      return (document.body.innerText || "").slice(0, 10000);
    }
  }

  function initCapture() {
    let maxScrollDepth = 0;
    const pageStartTime = Date.now();
    const cleanText = extractCleanPageText();
    const pageTitle = document.title || "";
    const pageUrl = window.location.href;
    const referrerUrl = document.referrer || null;

    // Report initial page load event with referrer link
    chrome.runtime.sendMessage({
      type: "PAGE_VISIT",
      payload: {
        event_type: "page_visit",
        source: "browser",
        timestamp: Date.now() / 1000,
        url: pageUrl,
        domain: hostname,
        title: scrubText(pageTitle),
        text_content: scrubText(cleanText),
        scroll_depth: 0,
        referrer_url: referrerUrl
      }
    });

    // 3. Track scroll depth
    function updateScrollDepth() {
      const scrollHeight = document.documentElement.scrollHeight - window.innerHeight;
      if (scrollHeight > 0) {
        const current = Math.min(100, Math.round((window.scrollY / scrollHeight) * 100));
        if (current > maxScrollDepth) {
          maxScrollDepth = current;
        }
      }
    }
    window.addEventListener("scroll", updateScrollDepth, { passive: true });

    // Send updated duration and scroll on page unload or visibility change
    function sendPageSummary() {
      const activeSeconds = Math.round((Date.now() - pageStartTime) / 1000);
      if (activeSeconds >= 2) {
        chrome.runtime.sendMessage({
          type: "PAGE_SUMMARY",
          payload: {
            event_type: "page_summary",
            source: "browser",
            timestamp: Date.now() / 1000,
            url: pageUrl,
            domain: hostname,
            title: scrubText(pageTitle),
            duration: activeSeconds,
            scroll_depth: maxScrollDepth
          }
        });
      }
    }

    window.addEventListener("beforeunload", sendPageSummary);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") {
        sendPageSummary();
      }
    });

    // 4. Capture Text Highlights / Selections
    let selectionTimeout = null;
    document.addEventListener("mouseup", () => {
      clearTimeout(selectionTimeout);
      selectionTimeout = setTimeout(() => {
        const selection = window.getSelection() ? window.getSelection().toString().trim() : "";
        if (selection && selection.length >= 10 && selection.length <= 2000) {
          chrome.runtime.sendMessage({
            type: "TEXT_SELECT",
            payload: {
              event_type: "text_select",
              source: "browser",
              timestamp: Date.now() / 1000,
              url: pageUrl,
              domain: hostname,
              title: scrubText(pageTitle),
              selected_text: scrubText(selection)
            }
          });
        }
      }, 500);
    });

    // 5. Form & Comment Box Typing Capture (with strict privacy exclusions)
    let typingTimer = null;
    let accumulatedText = "";

    function isSafeInputElement(target) {
      if (!target) return false;
      const tag = (target.tagName || "").toLowerCase();
      const type = (target.type || "").toLowerCase();
      const name = (target.name || "").toLowerCase();
      const id = (target.id || "").toLowerCase();
      const autocomplete = (target.getAttribute("autocomplete") || "").toLowerCase();

      // HARD EXCLUSION: passwords, credit cards, pins, secrets, tokens
      if (type === "password" || type === "hidden") return false;
      const sensitivePatterns = ["pass", "pwd", "card", "cvv", "cvc", "ssn", "pin", "secret", "token", "auth", "otp"];
      if (sensitivePatterns.some(p => name.includes(p) || id.includes(p) || autocomplete.includes(p))) {
        return false;
      }

      // Allow multiline textareas, contenteditable elements, and standard text search/comment inputs
      if (tag === "textarea" || target.isContentEditable) return true;
      if (tag === "input" && ["text", "search"].includes(type)) return true;

      return false;
    }

    document.addEventListener("input", (e) => {
      const target = e.target;
      if (!isSafeInputElement(target)) {
        return;
      }

      const val = target.value || target.innerText || "";
      accumulatedText = val.trim();

      clearTimeout(typingTimer);
      typingTimer = setTimeout(() => {
        if (accumulatedText.length >= 8) {
          chrome.runtime.sendMessage({
            type: "TYPED_INPUT",
            payload: {
              event_type: "typed_input",
              source: "browser",
              timestamp: Date.now() / 1000,
              url: pageUrl,
              domain: hostname,
              title: scrubText(pageTitle),
              text_content: scrubText(accumulatedText),
              metadata: {
                tagName: target.tagName,
                elementId: target.id || null
              }
            }
          });
        }
      }, 1500); // 1.5s debounce
    }, true);
  }
})();

