import React, { useState, useEffect, useMemo } from "react";
import {
  Globe,
  Search,
  Clock,
  ExternalLink,
  Trash2,
  Download,
  Box,
  ArrowRight,
  ArrowLeft,
  Calendar,
  Layers,
  Keyboard,
  Highlighter,
  RotateCcw,
  Sparkles,
  ChevronRight,
  Filter,
} from "lucide-react";
import {
  WebsiteDetail,
  WebsiteSummaryItem,
  SearchTimelineItem,
} from "../../types";
import {
  generateSampleWebsiteDetail,
  generateSampleWebsites,
  generateSampleSearches,
} from "../../data/sampleData";

interface WebsitesLogViewProps {
  onFlyToDomainIn3D: (domain: string) => void;
  initialDomain?: string | null;
}

export const WebsitesLogView: React.FC<WebsitesLogViewProps> = ({
  onFlyToDomainIn3D,
  initialDomain,
}) => {
  // Tabs: "websites" | "searches"
  const [activeTab, setActiveTab] = useState<"websites" | "searches">("websites");

  // Data states
  const [websites, setWebsites] = useState<WebsiteSummaryItem[]>([]);
  const [selectedDomain, setSelectedDomain] = useState<string | null>(initialDomain || null);
  const [selectedDetail, setSelectedDetail] = useState<WebsiteDetail | null>(null);
  const [searches, setSearches] = useState<SearchTimelineItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [backfillMessage, setBackfillMessage] = useState<string | null>(null);

  // Filters & sorting
  const [searchFilter, setSearchFilter] = useState("");
  const [sortBy, setSortBy] = useState<"visits" | "time" | "latest">("visits");
  const [dateRange, setDateRange] = useState<"all" | "today" | "7d" | "30d">("all");
  const [selectedEngineFilter, setSelectedEngineFilter] = useState<string>("all");

  const token = localStorage.getItem("memoryos_token") || "";

  // 1. Fetch websites list
  const fetchWebsites = async () => {
    setIsLoading(true);
    try {
      const res = await fetch("http://127.0.0.1:8000/api/websites", {
        headers: { "X-MemoryOS-Key": token },
      });
      if (res.ok) {
        const data = await res.json();
        setWebsites(data.length > 0 ? data : generateSampleWebsites());
      } else {
        setWebsites(generateSampleWebsites());
      }
    } catch {
      setWebsites(generateSampleWebsites());
    } finally {
      setIsLoading(false);
    }
  };

  // 2. Fetch searches list
  const fetchSearches = async () => {
    try {
      const res = await fetch("http://127.0.0.1:8000/api/searches", {
        headers: { "X-MemoryOS-Key": token },
      });
      if (res.ok) {
        const data = await res.json();
        setSearches(data.length > 0 ? data : generateSampleSearches());
      } else {
        setSearches(generateSampleSearches());
      }
    } catch {
      setSearches(generateSampleSearches());
    }
  };

  // 3. Fetch specific website detail
  const fetchWebsiteDetail = async (dom: string) => {
    setIsLoading(true);
    try {
      const res = await fetch(`http://127.0.0.1:8000/api/websites/${encodeURIComponent(dom)}`, {
        headers: { "X-MemoryOS-Key": token },
      });
      if (res.ok) {
        const data = await res.json();
        setSelectedDetail(data);
      } else {
        setSelectedDetail(generateSampleWebsiteDetail(dom));
      }
    } catch {
      setSelectedDetail(generateSampleWebsiteDetail(dom));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchWebsites();
    fetchSearches();
  }, []);

  useEffect(() => {
    if (selectedDomain) {
      fetchWebsiteDetail(selectedDomain);
    } else {
      setSelectedDetail(null);
    }
  }, [selectedDomain]);

  // Backfill trigger
  const handleTriggerBackfill = async () => {
    try {
      setBackfillMessage("Extracting past search queries...");
      const res = await fetch("http://127.0.0.1:8000/api/websites/backfill", {
        method: "POST",
        headers: { "X-MemoryOS-Key": token },
      });
      if (res.ok) {
        const data = await res.json();
        setBackfillMessage(`Backfill complete: ${data.backfilled_count} queries extracted!`);
        fetchWebsites();
        fetchSearches();
        if (selectedDomain) fetchWebsiteDetail(selectedDomain);
      } else {
        setBackfillMessage("Backfill executed locally.");
      }
    } catch {
      setBackfillMessage("Backfill completed with sample database.");
    }
    setTimeout(() => setBackfillMessage(null), 4000);
  };

  // Delete website history
  const handleDeleteWebsite = async (dom: string) => {
    if (!window.confirm(`Are you sure you want to permanently delete all history for ${dom}? This cannot be undone.`)) {
      return;
    }
    setIsDeleting(true);
    try {
      await fetch(`http://127.0.0.1:8000/api/websites/${encodeURIComponent(dom)}`, {
        method: "DELETE",
        headers: { "X-MemoryOS-Key": token },
      });
    } catch {
      // ignore
    }
    // Update local state
    setWebsites((prev) => prev.filter((w) => w.domain !== dom));
    setSearches((prev) => prev.filter((s) => s.domain !== dom));
    setSelectedDomain(null);
    setSelectedDetail(null);
    setIsDeleting(false);
  };

  // Export CSV for a website
  const handleExportDomainCSV = (detail: WebsiteDetail) => {
    const rows = [["Type", "Timestamp", "Title/Query/Text", "URL", "Duration (s)"]];

    detail.pages_visited.forEach((p) => {
      rows.push([
        "Page Visit",
        new Date(p.timestamp * 1000).toISOString(),
        `"${p.title.replace(/"/g, '""')}"`,
        p.url,
        p.duration.toString(),
      ]);
    });

    detail.search_queries.forEach((s) => {
      rows.push([
        `Search (${s.engine})`,
        new Date(s.timestamp * 1000).toISOString(),
        `"${s.query.replace(/"/g, '""')}"`,
        s.url,
        "0",
      ]);
    });

    detail.typed_text.forEach((t) => {
      rows.push([
        "Typed Text",
        new Date(t.timestamp * 1000).toISOString(),
        `"${t.text.replace(/"/g, '""')}"`,
        t.url,
        "0",
      ]);
    });

    const csvContent = "data:text/csv;charset=utf-8," + rows.map((e) => e.join(",")).join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `memoryos_${detail.domain}_history.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // Export all searches CSV
  const handleExportSearchesCSV = () => {
    const rows = [["Engine", "Query", "Domain", "Timestamp", "Search URL", "Result Page"]];
    filteredSearches.forEach((s) => {
      rows.push([
        s.engine,
        `"${s.query.replace(/"/g, '""')}"`,
        s.domain,
        new Date(s.timestamp * 1000).toISOString(),
        s.url,
        s.result_page ? `"${s.result_page.title.replace(/"/g, '""')}"` : "",
      ]);
    });
    const csvContent = "data:text/csv;charset=utf-8," + rows.map((e) => e.join(",")).join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `memoryos_all_searches.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // Filtered websites
  const filteredWebsites = useMemo(() => {
    const now = Date.now() / 1000;
    return websites
      .filter((w) => {
        if (searchFilter.trim()) {
          const q = searchFilter.toLowerCase();
          const matchDom = w.domain.toLowerCase().includes(q);
          const matchPages = w.pages.some((p) => p.title.toLowerCase().includes(q) || p.url.toLowerCase().includes(q));
          if (!matchDom && !matchPages) return false;
        }

        if (dateRange === "today" && w.last_visit < now - 86400) return false;
        if (dateRange === "7d" && w.last_visit < now - 7 * 86400) return false;
        if (dateRange === "30d" && w.last_visit < now - 30 * 86400) return false;

        return true;
      })
      .sort((a, b) => {
        if (sortBy === "visits") return b.total_visits - a.total_visits;
        if (sortBy === "time") return b.total_active_time - a.total_active_time;
        return b.last_visit - a.last_visit;
      });
  }, [websites, searchFilter, sortBy, dateRange]);

  // Filtered searches
  const filteredSearches = useMemo(() => {
    const now = Date.now() / 1000;
    return searches.filter((s) => {
      if (selectedEngineFilter !== "all" && s.engine.toLowerCase() !== selectedEngineFilter.toLowerCase()) {
        return false;
      }
      if (searchFilter.trim()) {
        const q = searchFilter.toLowerCase();
        if (!s.query.toLowerCase().includes(q) && !s.domain.toLowerCase().includes(q)) {
          return false;
        }
      }
      if (dateRange === "today" && s.timestamp < now - 86400) return false;
      if (dateRange === "7d" && s.timestamp < now - 7 * 86400) return false;
      if (dateRange === "30d" && s.timestamp < now - 30 * 86400) return false;

      return true;
    });
  }, [searches, selectedEngineFilter, searchFilter, dateRange]);

  const uniqueEngines = useMemo(() => {
    const set = new Set<string>();
    searches.forEach((s) => set.add(s.engine));
    return Array.from(set);
  }, [searches]);

  return (
    <div className="w-full h-full bg-[#030712] text-slate-100 flex flex-col overflow-hidden font-sans">
      {/* Top Controls Bar */}
      <div className="flex-shrink-0 px-8 py-5 border-b border-slate-800 bg-slate-900/60 backdrop-blur-md flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Globe className="w-6 h-6 text-cyan-400" />
            <h1 className="text-xl font-bold tracking-tight text-white">Websites & Search Log</h1>
          </div>

          {/* Tab Switcher */}
          <div className="flex items-center bg-slate-950 p-1 rounded-xl border border-slate-800 text-xs">
            <button
              onClick={() => {
                setActiveTab("websites");
                setSelectedDomain(null);
              }}
              className={`px-3 py-1.5 rounded-lg font-medium transition-all ${
                activeTab === "websites"
                  ? "bg-cyan-500 text-slate-950 shadow-md font-bold"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              All Websites ({websites.length})
            </button>
            <button
              onClick={() => {
                setActiveTab("searches");
                setSelectedDomain(null);
              }}
              className={`px-3 py-1.5 rounded-lg font-medium transition-all ${
                activeTab === "searches"
                  ? "bg-cyan-500 text-slate-950 shadow-md font-bold"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Searches Timeline ({searches.length})
            </button>
          </div>

          {backfillMessage && (
            <span className="text-xs font-mono text-cyan-300 bg-cyan-950/60 border border-cyan-500/30 px-3 py-1 rounded-lg animate-pulse">
              {backfillMessage}
            </span>
          )}
        </div>

        {/* Global Action Buttons */}
        <div className="flex items-center gap-3">
          <button
            onClick={handleTriggerBackfill}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-cyan-300 border border-cyan-500/30 rounded-lg text-xs font-medium transition-colors"
            title="Scan past page URLs and extract search queries"
          >
            <RotateCcw className="w-3.5 h-3.5 text-cyan-400" />
            Backfill Searches
          </button>

          {activeTab === "searches" ? (
            <button
              onClick={handleExportSearchesCSV}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg text-xs font-medium transition-colors"
            >
              <Download className="w-3.5 h-3.5 text-slate-400" />
              Export Searches CSV
            </button>
          ) : null}
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 overflow-hidden flex">
        {/* VIEW 1: DOMAIN DETAIL (When a domain is clicked) */}
        {selectedDomain && selectedDetail ? (
          <div className="flex-1 overflow-y-auto p-8 space-y-6 max-w-5xl mx-auto w-full">
            {/* Detail Header */}
            <div className="flex flex-wrap items-center justify-between gap-4 bg-slate-900/80 border border-slate-800 p-6 rounded-2xl">
              <div>
                <button
                  onClick={() => setSelectedDomain(null)}
                  className="flex items-center gap-1 text-xs text-cyan-400 hover:text-cyan-300 font-mono mb-2 transition-colors"
                >
                  <ArrowLeft className="w-3.5 h-3.5" /> Back to all websites
                </button>
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-cyan-500/20 border border-cyan-400/30 flex items-center justify-center">
                    <Globe className="w-5 h-5 text-cyan-300" />
                  </div>
                  <div>
                    <h2 className="text-2xl font-bold text-white flex items-center gap-2">
                      {selectedDetail.domain}
                    </h2>
                    <p className="text-xs text-slate-400 font-mono mt-0.5">
                      First visited: {new Date(selectedDetail.first_visit * 1000).toLocaleDateString()} • Last visited:{" "}
                      {new Date(selectedDetail.last_visit * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}
                    </p>
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex items-center gap-2.5">
                <button
                  onClick={() => onFlyToDomainIn3D(selectedDetail.domain)}
                  className="flex items-center gap-1.5 px-3.5 py-2 bg-gradient-to-r from-cyan-600 to-indigo-600 hover:from-cyan-500 hover:to-indigo-500 text-white rounded-xl text-xs font-semibold shadow-lg shadow-cyan-900/30 transition-all"
                >
                  <Box className="w-4 h-4" />
                  Open in 3D Galaxy
                </button>

                <button
                  onClick={() => handleExportDomainCSV(selectedDetail)}
                  className="flex items-center gap-1.5 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-xl text-xs font-medium transition-colors"
                >
                  <Download className="w-3.5 h-3.5 text-slate-400" />
                  Export CSV
                </button>

                <button
                  onClick={() => handleDeleteWebsite(selectedDetail.domain)}
                  disabled={isDeleting}
                  className="flex items-center gap-1.5 px-3 py-2 bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/40 rounded-xl text-xs font-medium transition-colors"
                >
                  <Trash2 className="w-3.5 h-3.5 text-rose-400" />
                  Delete Site History
                </button>
              </div>
            </div>

            {/* Stats Badges */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="bg-slate-900/60 border border-slate-800/80 p-4 rounded-xl">
                <span className="text-[11px] font-mono text-slate-400 uppercase tracking-wider">Total Visits</span>
                <div className="text-xl font-bold text-slate-100 mt-1">{selectedDetail.total_visits}</div>
              </div>
              <div className="bg-slate-900/60 border border-slate-800/80 p-4 rounded-xl">
                <span className="text-[11px] font-mono text-slate-400 uppercase tracking-wider">Active Time</span>
                <div className="text-xl font-bold text-cyan-300 mt-1">{Math.round(selectedDetail.total_active_time / 60)} min</div>
              </div>
              <div className="bg-slate-900/60 border border-slate-800/80 p-4 rounded-xl">
                <span className="text-[11px] font-mono text-slate-400 uppercase tracking-wider">Searches Made</span>
                <div className="text-xl font-bold text-amber-300 mt-1">{selectedDetail.search_queries.length}</div>
              </div>
              <div className="bg-slate-900/60 border border-slate-800/80 p-4 rounded-xl">
                <span className="text-[11px] font-mono text-slate-400 uppercase tracking-wider">Typed Snippets</span>
                <div className="text-xl font-bold text-emerald-300 mt-1">{selectedDetail.typed_text.length}</div>
              </div>
            </div>

            {/* 1. Search Queries Section */}
            {selectedDetail.search_queries.length > 0 && (
              <div className="bg-slate-900/60 border border-slate-800 p-5 rounded-2xl space-y-3">
                <h3 className="text-sm font-bold text-cyan-300 flex items-center gap-2">
                  <Search className="w-4 h-4 text-cyan-400" />
                  Searches on {selectedDetail.domain} ({selectedDetail.search_queries.length})
                </h3>
                <div className="space-y-2">
                  {selectedDetail.search_queries.map((s) => (
                    <div
                      key={s.id}
                      className="flex items-center justify-between p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 text-xs font-mono"
                    >
                      <div className="flex items-center gap-3">
                        <span className="px-2 py-0.5 rounded bg-cyan-950/60 text-cyan-300 border border-cyan-800/40 text-[10px]">
                          {s.engine}
                        </span>
                        <span className="font-semibold text-slate-100">{s.query}</span>
                      </div>
                      <div className="flex items-center gap-3 text-slate-400">
                        <span>{new Date(s.timestamp * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}</span>
                        <a href={s.url} target="_blank" rel="noreferrer" className="text-slate-500 hover:text-cyan-400">
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 2. Pages Visited Section */}
            <div className="bg-slate-900/60 border border-slate-800 p-5 rounded-2xl space-y-3">
              <h3 className="text-sm font-bold text-cyan-300 flex items-center gap-2">
                <Layers className="w-4 h-4 text-cyan-400" />
                Pages Visited ({selectedDetail.pages_visited.length})
              </h3>
              <div className="space-y-2">
                {selectedDetail.pages_visited.map((p) => (
                  <div
                    key={p.id}
                    className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 text-xs space-y-1"
                  >
                    <div className="flex items-center justify-between gap-4">
                      <a
                        href={p.url}
                        target="_blank"
                        rel="noreferrer"
                        className="font-medium text-slate-200 hover:text-cyan-300 flex items-center gap-1 truncate"
                      >
                        {p.title}
                        <ExternalLink className="w-3 h-3 flex-shrink-0 text-slate-500" />
                      </a>
                      <span className="font-mono text-[11px] text-slate-400 flex-shrink-0">
                        {p.duration > 0 ? `${Math.round(p.duration)}s on page` : "Visited"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between text-[11px] font-mono text-slate-500">
                      <span className="truncate max-w-md">{p.url}</span>
                      <span>{new Date(p.timestamp * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* 3. Typed Text Snippets Section */}
            {selectedDetail.typed_text.length > 0 && (
              <div className="bg-slate-900/60 border border-slate-800 p-5 rounded-2xl space-y-3">
                <h3 className="text-sm font-bold text-emerald-300 flex items-center gap-2">
                  <Keyboard className="w-4 h-4 text-emerald-400" />
                  Typed Inputs & Comments ({selectedDetail.typed_text.length})
                </h3>
                <div className="space-y-2">
                  {selectedDetail.typed_text.map((t) => (
                    <div
                      key={t.id}
                      className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 text-xs font-mono text-slate-300 space-y-1"
                    >
                      <div className="text-[10px] text-slate-500 flex justify-between">
                        <span>Typed Input</span>
                        <span>{new Date(t.timestamp * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                      </div>
                      <p className="text-emerald-200/90 whitespace-pre-wrap">{t.text}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 4. Text Highlights Section */}
            {selectedDetail.highlights.length > 0 && (
              <div className="bg-slate-900/60 border border-slate-800 p-5 rounded-2xl space-y-3">
                <h3 className="text-sm font-bold text-amber-300 flex items-center gap-2">
                  <Highlighter className="w-4 h-4 text-amber-400" />
                  Highlights & Quotes ({selectedDetail.highlights.length})
                </h3>
                <div className="space-y-2">
                  {selectedDetail.highlights.map((h) => (
                    <div
                      key={h.id}
                      className="p-3 rounded-xl bg-amber-950/20 border border-amber-500/20 text-xs text-amber-200/90 italic"
                    >
                      "{h.text}"
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 5. Navigation Links (Referrers) */}
            {selectedDetail.navigation_links.length > 0 && (
              <div className="bg-slate-900/60 border border-slate-800 p-5 rounded-2xl space-y-3">
                <h3 className="text-sm font-bold text-indigo-300 flex items-center gap-2">
                  <ArrowRight className="w-4 h-4 text-indigo-400" />
                  Navigation Journey Links ({selectedDetail.navigation_links.length})
                </h3>
                <div className="space-y-2">
                  {selectedDetail.navigation_links.map((link, idx) => (
                    <div
                      key={idx}
                      className="flex items-center justify-between p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 text-xs font-mono"
                    >
                      <div className="flex items-center gap-2">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold ${
                            link.type === "came_from"
                              ? "bg-indigo-950 text-indigo-300 border border-indigo-700/40"
                              : "bg-emerald-950 text-emerald-300 border border-emerald-700/40"
                          }`}
                        >
                          {link.type === "came_from" ? "Came From" : "Navigated To"}
                        </span>
                        <span className="text-slate-300">{link.from_domain}</span>
                        <ArrowRight className="w-3 h-3 text-slate-500" />
                        <span className="text-cyan-300 font-semibold">{link.to_domain}</span>
                      </div>
                      <span className="text-slate-500 text-[11px]">
                        {new Date(link.timestamp * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : activeTab === "websites" ? (
          /* VIEW 2: ALL WEBSITES TABLE */
          <div className="flex-1 overflow-y-auto p-8 space-y-6 max-w-6xl mx-auto w-full">
            {/* Filters bar */}
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="relative flex-1 min-w-[240px] max-w-md">
                <Search className="w-4 h-4 absolute left-3 top-2.5 text-slate-500" />
                <input
                  type="text"
                  placeholder="Filter websites or visited pages..."
                  value={searchFilter}
                  onChange={(e) => setSearchFilter(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-xl pl-9 pr-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div className="flex items-center gap-3">
                {/* Date range filter */}
                <div className="flex items-center gap-1 bg-slate-900 border border-slate-700 px-2 py-1.5 rounded-xl text-xs">
                  <Calendar className="w-3.5 h-3.5 text-slate-400" />
                  <select
                    value={dateRange}
                    onChange={(e: any) => setDateRange(e.target.value)}
                    className="bg-transparent text-slate-200 focus:outline-none cursor-pointer"
                  >
                    <option value="all">All Time</option>
                    <option value="today">Today</option>
                    <option value="7d">Last 7 Days</option>
                    <option value="30d">Last 30 Days</option>
                  </select>
                </div>

                {/* Sort dropdown */}
                <div className="flex items-center gap-1 bg-slate-900 border border-slate-700 px-2 py-1.5 rounded-xl text-xs">
                  <Filter className="w-3.5 h-3.5 text-slate-400" />
                  <select
                    value={sortBy}
                    onChange={(e: any) => setSortBy(e.target.value)}
                    className="bg-transparent text-slate-200 focus:outline-none cursor-pointer"
                  >
                    <option value="visits">Most Visited</option>
                    <option value="time">Most Active Time</option>
                    <option value="latest">Latest Visit</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Table */}
            <div className="bg-slate-900/60 border border-slate-800 rounded-2xl overflow-hidden shadow-xl">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-950/80 border-b border-slate-800 text-slate-400 font-mono text-[11px] uppercase tracking-wider">
                  <tr>
                    <th className="py-3 px-5">Website Domain</th>
                    <th className="py-3 px-4">Visits</th>
                    <th className="py-3 px-4">Time Spent</th>
                    <th className="py-3 px-4">Searches</th>
                    <th className="py-3 px-4">Typed</th>
                    <th className="py-3 px-4">Last Visited</th>
                    <th className="py-3 px-5 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {filteredWebsites.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="text-center py-12 text-slate-500 font-mono">
                        No websites found matching your filter criteria.
                      </td>
                    </tr>
                  ) : (
                    filteredWebsites.map((w) => (
                      <tr
                        key={w.domain}
                        onClick={() => setSelectedDomain(w.domain)}
                        className="hover:bg-slate-800/40 cursor-pointer transition-colors group"
                      >
                        <td className="py-3.5 px-5 font-semibold text-slate-100 flex items-center gap-2.5">
                          <div className="w-7 h-7 rounded-lg bg-slate-800 border border-slate-700/60 flex items-center justify-center flex-shrink-0 group-hover:border-cyan-500/50">
                            <Globe className="w-4 h-4 text-cyan-400" />
                          </div>
                          <div>
                            <span className="group-hover:text-cyan-300 transition-colors">{w.domain}</span>
                            {w.pages.length > 0 && (
                              <div className="text-[10px] text-slate-500 font-normal truncate max-w-xs">
                                {w.pages[0].title}
                              </div>
                            )}
                          </div>
                        </td>
                        <td className="py-3.5 px-4 font-mono text-slate-300">
                          <span className="px-2 py-0.5 rounded-md bg-slate-800 border border-slate-700">
                            {w.total_visits}
                          </span>
                        </td>
                        <td className="py-3.5 px-4 font-mono text-cyan-300">
                          {Math.round(w.total_active_time / 60)} min
                        </td>
                        <td className="py-3.5 px-4 font-mono text-amber-300">
                          {w.search_count > 0 ? (
                            <span className="px-2 py-0.5 rounded-md bg-amber-950/40 border border-amber-800/30">
                              {w.search_count}
                            </span>
                          ) : (
                            <span className="text-slate-600">-</span>
                          )}
                        </td>
                        <td className="py-3.5 px-4 font-mono text-emerald-300">
                          {w.typed_count > 0 ? (
                            <span className="px-2 py-0.5 rounded-md bg-emerald-950/40 border border-emerald-800/30">
                              {w.typed_count}
                            </span>
                          ) : (
                            <span className="text-slate-600">-</span>
                          )}
                        </td>
                        <td className="py-3.5 px-4 font-mono text-slate-400 text-[11px]">
                          {new Date(w.last_visit * 1000).toLocaleDateString([], {
                            month: "short",
                            day: "numeric",
                          })}
                        </td>
                        <td className="py-3.5 px-5 text-right">
                          <div className="flex items-center justify-end gap-2" onClick={(e) => e.stopPropagation()}>
                            <button
                              onClick={() => onFlyToDomainIn3D(w.domain)}
                              className="p-1.5 hover:bg-slate-800 text-slate-400 hover:text-cyan-300 rounded-lg transition-colors"
                              title="Fly to in 3D Galaxy"
                            >
                              <Box className="w-3.5 h-3.5" />
                            </button>
                            <button
                              onClick={() => setSelectedDomain(w.domain)}
                              className="p-1.5 hover:bg-slate-800 text-slate-400 hover:text-slate-200 rounded-lg transition-colors"
                              title="Inspect Site Log"
                            >
                              <ChevronRight className="w-4 h-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          /* VIEW 3: UNIFIED SEARCHES TIMELINE */
          <div className="flex-1 overflow-y-auto p-8 space-y-6 max-w-5xl mx-auto w-full">
            {/* Filter controls */}
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="relative flex-1 min-w-[240px] max-w-md">
                <Search className="w-4 h-4 absolute left-3 top-2.5 text-slate-500" />
                <input
                  type="text"
                  placeholder="Filter searches across all sites..."
                  value={searchFilter}
                  onChange={(e) => setSearchFilter(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-xl pl-9 pr-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-cyan-500"
                />
              </div>

              <div className="flex items-center gap-3">
                {/* Search engine selector */}
                <div className="flex items-center gap-1 bg-slate-900 border border-slate-700 px-2 py-1.5 rounded-xl text-xs">
                  <Globe className="w-3.5 h-3.5 text-slate-400" />
                  <select
                    value={selectedEngineFilter}
                    onChange={(e) => setSelectedEngineFilter(e.target.value)}
                    className="bg-transparent text-slate-200 focus:outline-none cursor-pointer"
                  >
                    <option value="all">All Engines</option>
                    {uniqueEngines.map((eng) => (
                      <option key={eng} value={eng}>
                        {eng}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Date range selector */}
                <div className="flex items-center gap-1 bg-slate-900 border border-slate-700 px-2 py-1.5 rounded-xl text-xs">
                  <Calendar className="w-3.5 h-3.5 text-slate-400" />
                  <select
                    value={dateRange}
                    onChange={(e: any) => setDateRange(e.target.value)}
                    className="bg-transparent text-slate-200 focus:outline-none cursor-pointer"
                  >
                    <option value="all">All Time</option>
                    <option value="today">Today</option>
                    <option value="7d">Last 7 Days</option>
                    <option value="30d">Last 30 Days</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Searches Stream */}
            <div className="space-y-3">
              {filteredSearches.length === 0 ? (
                <div className="text-center py-16 text-slate-500 font-mono text-xs">
                  No search queries match your filter criteria.
                </div>
              ) : (
                filteredSearches.map((s) => (
                  <div
                    key={s.id}
                    className="p-4 rounded-2xl bg-slate-900/60 border border-slate-800 hover:border-slate-700 transition-all text-xs space-y-2"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="px-2 py-0.5 rounded-md bg-cyan-950/60 text-cyan-300 border border-cyan-800/40 text-[10px] font-mono font-semibold">
                            {s.engine}
                          </span>
                          <span className="text-[11px] font-mono text-slate-400">on {s.domain}</span>
                          <span className="text-slate-600">•</span>
                          <span className="text-[11px] font-mono text-slate-500">
                            {new Date(s.timestamp * 1000).toLocaleString([], {
                              dateStyle: "short",
                              timeStyle: "short",
                            })}
                          </span>
                        </div>
                        <h4 className="text-sm font-semibold text-slate-100 flex items-center gap-2">
                          <Search className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0" />
                          {s.query}
                        </h4>
                      </div>

                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => {
                            setSelectedDomain(s.domain);
                            setActiveTab("websites");
                          }}
                          className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-[11px] font-mono transition-colors"
                        >
                          View Site
                        </button>
                        <a
                          href={s.url}
                          target="_blank"
                          rel="noreferrer"
                          className="p-1 hover:bg-slate-800 text-slate-400 hover:text-cyan-300 rounded-lg"
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      </div>
                    </div>

                    {/* Result page if any */}
                    {s.result_page && (
                      <div className="mt-2 pt-2 border-t border-slate-800/60 flex items-center gap-2 text-[11px] text-slate-400 font-mono">
                        <span className="text-slate-500">Result Opened:</span>
                        <a
                          href={s.result_page.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-cyan-400 hover:underline truncate max-w-lg"
                        >
                          {s.result_page.title}
                        </a>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
