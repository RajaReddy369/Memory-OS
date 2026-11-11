import React, { useState, useMemo, useEffect, useRef } from "react";
import {
  CityDayTower,
  GalaxyEdge,
  GalaxyNode,
  PageNode,
  Project,
  SessionNode,
  ViewMode,
  ZoomLevel,
  DataSummary,
  Graph3DResponse,
} from "./types";
import { SpaceScene } from "./components/3d/SpaceScene";
import { Navbar } from "./components/ui/Navbar";
import { InspectorPanel } from "./components/ui/InspectorPanel";
import { DockedChatPanel } from "./components/ui/DockedChatPanel";
import { ReplayController } from "./components/ui/ReplayController";
import { TwoDTimelineFallback } from "./components/ui/TwoDTimelineFallback";
import { WebsitesLogView } from "./components/ui/WebsitesLogView";
import { AppsGraphView } from "./components/ui/AppsGraphView";
import {
  AlertTriangle,
  Compass,
  Database,
  Globe,
  Laptop,
  RefreshCw,
  Sparkles,
  Upload,
  CheckCircle2,
  X,
} from "lucide-react";

export const App: React.FC = () => {
  // 1. Live Data State (zero sample data)
  const [summary, setSummary] = useState<DataSummary | null>(null);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);
  const [isLoadingData, setIsLoadingData] = useState<boolean>(true);
  const [projects, setProjects] = useState<Project[]>([]);
  const [sessions, setSessions] = useState<SessionNode[]>([]);
  const [galaxyNodes, setGalaxyNodes] = useState<GalaxyNode[]>([]);
  const [galaxyEdges, setGalaxyEdges] = useState<GalaxyEdge[]>([]);
  const [cityTowers, setCityTowers] = useState<CityDayTower[]>([]);

  // 2. View and Zoom state
  const [viewMode, setViewMode] = useState<ViewMode>("JOURNEY");
  const [zoomLevel, setZoomLevel] = useState<ZoomLevel>("SESSION");
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  // 3. Selection & Inspection
  const [selectedSession, setSelectedSession] = useState<SessionNode | null>(null);
  const [selectedPage, setSelectedPage] = useState<PageNode | null>(null);
  const [selectedGalaxyNode, setSelectedGalaxyNode] = useState<GalaxyNode | null>(null);
  const [selectedCityDay, setSelectedCityDay] = useState<CityDayTower | null>(null);
  const [highlightedId, setHighlightedId] = useState<string | null>(null);
  const [websitesInitialDomain, setWebsitesInitialDomain] = useState<string | null>(null);

  // 4. Camera target position
  const [cameraTargetPos, setCameraTargetPos] = useState<[number, number, number] | null>(null);

  // 5. Replay state
  const [isReplaying, setIsReplaying] = useState(false);
  const [replayProgress, setReplayProgress] = useState(0.0);
  const [replaySpeed, setReplaySpeed] = useState(1);

  // 6. Hover tooltip info
  const [hoverInfo, setHoverInfo] = useState<{
    title: string;
    subtitle: string;
    x: number;
    y: number;
  } | null>(null);

  // 7. History import modal state
  const [isImportModalOpen, setIsImportModalOpen] = useState(false);
  const [importStatus, setImportStatus] = useState<string | null>(null);
  const [importCount, setImportCount] = useState<number | null>(null);
  const [isImporting, setIsImporting] = useState(false);

  const [token, setToken] = useState<string>(() => localStorage.getItem("memoryos_token") || "");

  const getAuthToken = async (): Promise<string> => {
    let t = token || localStorage.getItem("memoryos_token") || "";
    if (t) return t;

    try {
      if (typeof chrome !== "undefined" && chrome?.storage?.local) {
        const stored = await chrome.storage.local.get(["apiKey"]);
        if (stored?.apiKey) {
          localStorage.setItem("memoryos_token", stored.apiKey);
          setToken(stored.apiKey);
          return stored.apiKey;
        }
      }
    } catch {}

    try {
      const authRes = await fetch("http://127.0.0.1:8000/api/auth/token");
      if (authRes.ok) {
        const authData = await authRes.json();
        if (authData.token) {
          localStorage.setItem("memoryos_token", authData.token);
          setToken(authData.token);
          if (typeof chrome !== "undefined" && chrome?.storage?.local) {
            chrome.storage.local.set({ apiKey: authData.token });
          }
          return authData.token;
        }
      }
    } catch {}

    return "";
  };

  // 8. Fetch real database events & topology
  const fetchRealData = async () => {
    setIsLoadingData(true);
    const activeToken = await getAuthToken();
    const headers: Record<string, string> = activeToken ? { "X-MemoryOS-Key": activeToken } : {};

    // Check backend health
    try {
      const healthRes = await fetch("http://127.0.0.1:8000/api/health");
      if (!healthRes.ok) throw new Error("Offline");
      setBackendOnline(true);
    } catch {
      setBackendOnline(false);
      setIsLoadingData(false);
      return;
    }

    // Fetch live summary
    try {
      const sumRes = await fetch("http://127.0.0.1:8000/api/data/summary", { headers });
      if (sumRes.ok) {
        const sumData: DataSummary = await sumRes.json();
        setSummary(sumData);
      }
    } catch (e) {
      console.error("Failed to load summary", e);
    }

    // Fetch projects
    try {
      const projRes = await fetch("http://127.0.0.1:8000/api/projects", { headers });
      if (projRes.ok) {
        const projData = await projRes.json();
        const mappedProjects: Project[] = (projData || []).map((p: any, idx: number) => ({
          id: p.name || `proj_${idx}`,
          name: p.name || "Default Project",
          color: p.color || "#06b6d4",
          glowColor: p.glowColor || "rgba(6, 182, 212, 0.4)",
          description: p.description || "",
          totalHours: Math.round((p.event_count || 1) * 0.1),
        }));
        setProjects(mappedProjects);
      }
    } catch (e) {
      console.error("Failed to load projects", e);
    }

    // Fetch 3D Graph layout
    try {
      const gRes = await fetch("http://127.0.0.1:8000/api/graph3d", { headers });
      if (gRes.ok) {
        const gData: Graph3DResponse = await gRes.json();
        const gNodes: GalaxyNode[] = (gData.nodes || []).map((n) => {
          let nodeType: "project" | "domain" | "topic" | "file" = "domain";
          if (n.type === "region") nodeType = "project";
          else if (n.type === "building") {
            nodeType = n.subType?.startsWith("file_") ? "file" : "topic";
          }
          return {
            id: n.id,
            name: n.name,
            type: nodeType,
            size: n.type === "region" ? 14 : n.type === "city" ? 9 : 4,
            color: n.type === "region" ? "#38bdf8" : n.type === "city" ? "#a855f7" : "#10b981",
            glow: n.type === "region" || n.type === "city",
            position: n.position,
            connections: [],
            details: `${n.subType || n.type} • ${n.city || ""} • ${n.source || "local"}`,
          };
        });

        const gEdges: GalaxyEdge[] = (gData.edges || []).map((e) => ({
          id: e.id,
          source: e.source,
          target: e.target,
          weight: e.weight,
          color: e.type === "referrer" ? "#38bdf8" : "#6366f1",
        }));

        setGalaxyNodes(gNodes);
        setGalaxyEdges(gEdges);
      }
    } catch (e) {
      console.error("Failed to load graph3d", e);
    }

    // Fetch real sessions
    try {
      const sessRes = await fetch("http://127.0.0.1:8000/api/sessions", { headers });
      if (sessRes.ok) {
        const sessData = await sessRes.json();
        const rawList = Array.isArray(sessData) ? sessData : (sessData?.sessions || []);
        if (rawList.length > 0) {
          const realSessions: SessionNode[] = rawList.map((s: any, idx: number) => {
            const startTime = s.start_time || Date.now() / 1000;
            const endTime = s.end_time || startTime;
            const durMin = Math.round((s.duration || 0) / 60) || 1;
            const d = new Date(startTime * 1000);
            const dateStr = d.toISOString().split("T")[0];
            const timeStr = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

            // Smooth curved layout for session milestones
            const angle = idx * 0.35;
            const radius = 25 + Math.sin(idx * 0.5) * 8;
            const x = Math.cos(angle) * radius;
            const z = Math.sin(angle) * radius + idx * 4;
            const y = Math.sin(idx * 0.8) * 3;

            return {
              id: String(s.id),
              title: s.title || `Session ${s.id}`,
              summary: s.summary || "",
              projectId: s.project_label || "default",
              projectName: s.project_label || "General",
              projectColor: "#06b6d4",
              startTime,
              endTime,
              durationMinutes: durMin,
              timeStr,
              dateStr,
              primaryApp: s.primary_app || "Browser",
              primaryDomain: s.primary_domain || "",
              eventCount: s.event_count || 1,
              position3D: [x, y, z],
              pages: [],
              filesTouched: [],
              typedChunks: [],
            };
          });
          setSessions(realSessions);

          // Group real sessions into CityDayTowers
          const byDate: Record<string, { totalHours: number; count: number; apps: Record<string, number> }> = {};
          realSessions.forEach((s) => {
            if (!byDate[s.dateStr]) {
              byDate[s.dateStr] = { totalHours: 0, count: 0, apps: {} };
            }
            const hrs = s.durationMinutes / 60.0;
            byDate[s.dateStr].totalHours += hrs;
            byDate[s.dateStr].count += 1;
            const app = s.primaryApp || s.primaryDomain || "Other";
            byDate[s.dateStr].apps[app] = (byDate[s.dateStr].apps[app] || 0) + hrs;
          });

          const dayKeys = Object.keys(byDate).sort();
          const towers: CityDayTower[] = dayKeys.map((dayStr, idx) => {
            const entry = byDate[dayStr];
            const tx = (idx % 6) * 12 - 30;
            const tz = Math.floor(idx / 6) * 12 - 20;
            const segments = Object.entries(entry.apps).map(([appName, hrs], sIdx) => ({
              name: appName,
              type: "app" as const,
              color: sIdx % 2 === 0 ? "#06b6d4" : "#8b5cf6",
              hours: Math.round(hrs * 10) / 10,
              height: Math.max(1.0, Math.min(18.0, hrs * 2.5)),
            }));
            return {
              id: `day_${dayStr}`,
              dateStr: dayStr,
              timestamp: new Date(dayStr).getTime() / 1000,
              totalActiveHours: Math.round(entry.totalHours * 10) / 10,
              sessionsCount: entry.count,
              position: [tx, 0, tz],
              segments,
            };
          });
          setCityTowers(towers);
        } else {
          setSessions([]);
          setCityTowers([]);
          setViewMode((prev) => (prev === "JOURNEY" ? "GALAXY" : prev));
        }
      }
    } catch (e) {
      console.error("Failed to load sessions", e);
    } finally {
      setIsLoadingData(false);
    }
  };

  useEffect(() => {
    fetchRealData();
  }, []);

  // Listen for messages from extension side panel or popup
  useEffect(() => {
    if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.onMessage) {
      const listener = (msg: any) => {
        if (msg?.type === "HIGHLIGHT_NODE") {
          handleChatHighlight(msg.nodeId, msg.position);
        } else if (msg?.type === "DATA_UPDATED") {
          fetchRealData();
        }
      };
      chrome.runtime.onMessage.addListener(listener);
      return () => chrome.runtime.onMessage.removeListener(listener);
    }
  }, [sessions]);

  // Filtered sessions based on project filter and search
  const filteredSessions = useMemo(() => {
    return sessions.filter((s) => {
      if (selectedProjectId && s.projectId !== selectedProjectId) return false;
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchTitle = s.title.toLowerCase().includes(q);
        const matchSummary = s.summary.toLowerCase().includes(q);
        const matchApp = s.primaryApp.toLowerCase().includes(q);
        const matchDomain = s.primaryDomain.toLowerCase().includes(q);
        if (!matchTitle && !matchSummary && !matchApp && !matchDomain) return false;
      }
      return true;
    });
  }, [sessions, selectedProjectId, searchQuery]);

  // When search matches a session, automatically fly camera to it
  useEffect(() => {
    if (searchQuery.trim().length >= 3 && filteredSessions.length > 0) {
      const first = filteredSessions[0];
      setCameraTargetPos(first.position3D);
      setSelectedSession(first);
    }
  }, [searchQuery, filteredSessions]);

  // Replay animation loop
  const replayRef = useRef<number | null>(null);
  useEffect(() => {
    if (!isReplaying) {
      if (replayRef.current) cancelAnimationFrame(replayRef.current);
      return;
    }

    let lastTime = performance.now();
    const animate = (now: number) => {
      const dt = (now - lastTime) / 1000;
      lastTime = now;

      setReplayProgress((prev) => {
        const next = prev + dt * 0.03 * replaySpeed;
        if (next >= 1.0) {
          setIsReplaying(false);
          return 1.0;
        }
        return next;
      });

      replayRef.current = requestAnimationFrame(animate);
    };

    replayRef.current = requestAnimationFrame(animate);

    return () => {
      if (replayRef.current) cancelAnimationFrame(replayRef.current);
    };
  }, [isReplaying, replaySpeed]);

  // Sync selected session with replay progression
  useEffect(() => {
    if (!isReplaying || sessions.length === 0) return;
    const idx = Math.min(
      Math.floor(replayProgress * sessions.length),
      sessions.length - 1
    );
    const curr = sessions[idx];
    setSelectedSession(curr);
    setCameraTargetPos(curr.position3D);
  }, [isReplaying, replayProgress, sessions]);

  // Handle node selection
  const handleSelectSession = (session: SessionNode) => {
    setSelectedSession(session);
    setSelectedPage(session.pages[0] || null);
    setCameraTargetPos(session.position3D);
    setZoomLevel("PAGE");
  };

  const handleSelectPage = (page: PageNode) => {
    setSelectedPage(page);
    setZoomLevel("ACTION");
  };

  const handleSelectGalaxyNode = (node: GalaxyNode) => {
    setSelectedGalaxyNode(node);
    setSelectedSession(null);
    setSelectedPage(null);
    setCameraTargetPos(node.position);
    setHighlightedId(node.id);
  };

  const handleFlyToDomainIn3D = (domain: string) => {
    setViewMode("GALAXY");
    const clean = domain.toLowerCase().replace("www.", "");
    const found = galaxyNodes.find(
      (n) => n.name.toLowerCase().includes(clean) || clean.includes(n.name.toLowerCase().replace("www.", ""))
    );
    if (found) {
      setSelectedGalaxyNode(found);
      setSelectedSession(null);
      setCameraTargetPos(found.position);
      setHighlightedId(found.id);
    } else {
      const sess = sessions.find((s) => s.primaryDomain.toLowerCase().includes(clean));
      if (sess) {
        setViewMode("JOURNEY");
        setSelectedSession(sess);
        setCameraTargetPos(sess.position3D);
      }
    }
  };

  const handleSelectCityDay = (tower: CityDayTower) => {
    setSelectedCityDay(tower);
    setCameraTargetPos(tower.position);
    const match = sessions.find((s) => s.dateStr === tower.dateStr);
    if (match) {
      setSelectedSession(match);
    }
  };

  const handleResetCamera = () => {
    setCameraTargetPos([0, 20, 45]);
    setSelectedSession(null);
    setSelectedPage(null);
    setHighlightedId(null);
    setZoomLevel("DAY");
  };

  const handleChatHighlight = (
    nodeId: string,
    pos?: [number, number, number]
  ) => {
    setHighlightedId(nodeId);
    if (pos) {
      setCameraTargetPos(pos);
    } else {
      const found = sessions.find((s) => s.id === nodeId);
      if (found) {
        setSelectedSession(found);
        setCameraTargetPos(found.position3D);
      }
    }
  };

  const handleSwitchTo2D = (sessionId: string) => {
    setViewMode("2D_TIMELINE");
    const found = sessions.find((s) => s.id === sessionId);
    if (found) setSelectedSession(found);
  };

  // Run history importer from extension or backend API
  const handleTriggerHistoryImport = async () => {
    setIsImporting(true);
    setImportStatus("Requesting browser history...");

    // Check if running in browser extension context with history access
    if (typeof chrome !== "undefined" && chrome.permissions && chrome.history) {
      try {
        const granted = await chrome.permissions.request({ permissions: ["history"] });
        if (!granted) {
          setImportStatus("History permission denied by user.");
          setIsImporting(false);
          return;
        }

        setImportStatus("Scanning browser history...");
        const items = await chrome.history.search({
          text: "",
          startTime: Date.now() - 30 * 86400 * 1000,
          maxResults: 2000,
        });

        setImportStatus(`Processing ${items.length} history items...`);
        let imported = 0;
        const batchSize = 100;
        const chunks: any[][] = [];

        for (let i = 0; i < items.length; i += batchSize) {
          chunks.push(items.slice(i, i + batchSize));
        }

        for (const chunk of chunks) {
          const eventsPayload = chunk
            .filter((item) => item.url && item.url.startsWith("http"))
            .map((item) => {
              let domain = "";
              try {
                domain = new URL(item.url).hostname.toLowerCase();
              } catch {
                domain = "unknown";
              }
              return {
                event_type: "page_visit",
                source: "edge_history",
                timestamp: (item.lastVisitTime || Date.now()) / 1000.0,
                url: item.url,
                domain,
                title: item.title || domain,
                app_name: "Edge",
                duration: 0.0,
                text_content: "",
                metadata_json: JSON.stringify({
                  metadata_only: true,
                  visit_count: item.visitCount,
                  typed_count: item.typedCount,
                }),
              };
            });

          if (eventsPayload.length > 0) {
            await fetch("http://127.0.0.1:8000/api/events/batch", {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                ...(token ? { "X-MemoryOS-Key": token } : {}),
              },
              body: JSON.stringify(eventsPayload),
            });
            imported += eventsPayload.length;
          }
        }

        setImportCount(imported);
        setImportStatus(`Successfully imported ${imported} items!`);
        fetchRealData();
      } catch (err: any) {
        setImportStatus(`Import failed: ${err?.message || "Unknown error"}`);
      } finally {
        setIsImporting(false);
      }
    } else {
      // In web standalone mode, notify user that extension powers the direct browser import
      setImportStatus("To import Edge/Chrome history directly, use the MemoryOS Browser Extension popup.");
      setIsImporting(false);
    }
  };

  const activeSessionIndex = Math.min(
    Math.floor(replayProgress * sessions.length),
    Math.max(0, sessions.length - 1)
  );
  const activeSession = sessions[activeSessionIndex] || sessions[0];

  // 1. Backend Offline Screen
  if (backendOnline === false) {
    return (
      <div className="w-screen h-screen bg-[#030712] flex flex-col items-center justify-center p-6 text-slate-100 font-sans">
        <div className="max-w-md w-full bg-slate-900/90 border border-red-500/30 rounded-2xl p-8 shadow-2xl backdrop-blur-xl text-center space-y-5">
          <div className="w-14 h-14 mx-auto rounded-2xl bg-red-500/10 border border-red-500/30 flex items-center justify-center text-red-400">
            <AlertTriangle className="w-7 h-7" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-white tracking-tight">Backend Offline</h2>
            <p className="text-sm text-slate-400 mt-1">
              Could not connect to MemoryOS local engine at <code className="text-cyan-400">http://127.0.0.1:8000</code>.
            </p>
          </div>
          <div className="bg-slate-950/80 p-3.5 rounded-xl border border-slate-800 text-left font-mono text-xs text-slate-300 space-y-1">
            <div className="text-slate-500 text-[11px]">Start the server in PowerShell:</div>
            <div className="text-cyan-300 font-bold">python -m backend.main</div>
          </div>
          <button
            onClick={fetchRealData}
            className="w-full py-2.5 px-4 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold text-sm transition-all shadow-lg shadow-cyan-500/20 flex items-center justify-center gap-2"
          >
            <RefreshCw className="w-4 h-4" />
            Retry Connection
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="relative w-screen h-screen bg-[#030712] overflow-hidden select-none font-sans text-slate-100">
      {/* 1. Top Navbar */}
      <Navbar
        viewMode={viewMode}
        zoomLevel={zoomLevel}
        projects={projects}
        selectedProjectId={selectedProjectId}
        searchQuery={searchQuery}
        dataSummary={summary}
        onSetViewMode={setViewMode}
        onSetZoomLevel={setZoomLevel}
        onSelectProject={setSelectedProjectId}
        onSearchChange={setSearchQuery}
        onResetCamera={handleResetCamera}
        onOpenHistoryImport={() => setIsImportModalOpen(true)}
      />

      {/* 2. Empty State (Zero Fake Data) */}
      {!isLoadingData && summary && summary.total_events === 0 ? (
        <div className="w-full h-full flex flex-col items-center justify-center p-6 text-center z-10 relative">
          <div className="max-w-lg w-full bg-slate-900/80 border border-slate-800/80 rounded-2xl p-8 backdrop-blur-xl shadow-2xl space-y-6">
            <div className="w-16 h-16 mx-auto rounded-2xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
              <Sparkles className="w-8 h-8" />
            </div>
            <div>
              <h2 className="text-2xl font-bold text-white tracking-tight">No activity recorded yet</h2>
              <p className="text-sm text-slate-400 mt-2 leading-relaxed">
                MemoryOS captures your digital memory in real-time. Start browsing or import your browser history to watch your 3D cognitive world form.
              </p>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-left">
              <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800/80">
                <div className="flex items-center gap-2 font-semibold text-xs text-cyan-300">
                  <Globe className="w-4 h-4" /> Browser Capture
                </div>
                <p className="text-[11px] text-slate-400 mt-1">
                  Active tabs, reading time & search queries recorded automatically.
                </p>
              </div>
              <div className="p-3.5 rounded-xl bg-slate-950/60 border border-slate-800/80">
                <div className="flex items-center gap-2 font-semibold text-purple-300">
                  <Laptop className="w-4 h-4" /> Desktop Agent
                </div>
                <p className="text-[11px] text-slate-400 mt-1">
                  Tracks active windows, files edited, and coding blocks.
                </p>
              </div>
            </div>

            <div className="flex flex-col sm:flex-row gap-3 pt-2">
              <button
                onClick={() => setIsImportModalOpen(true)}
                className="flex-1 py-2.5 px-4 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold text-sm transition-all shadow-lg shadow-cyan-500/20 flex items-center justify-center gap-2"
              >
                <Upload className="w-4 h-4" />
                Import History
              </button>
              <button
                onClick={fetchRealData}
                className="py-2.5 px-4 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 font-semibold text-sm transition-all flex items-center justify-center gap-2"
              >
                <RefreshCw className="w-4 h-4" />
                Refresh
              </button>
            </div>
          </div>
        </div>
      ) : (
        /* 3. Main Views: 3D Scene, 2D Timeline Fallback, Websites Log, or Apps Graph */
        <>
          {viewMode === "APPS" ? (
            <div className="pt-16 pb-0 h-full">
              <AppsGraphView
                onSelectNodeIn3D={(nodeId) => {
                  setViewMode("JOURNEY");
                  setHighlightedId(nodeId);
                }}
              />
            </div>
          ) : viewMode === "WEBSITES" ? (
            <div className="pt-16 pb-0 h-full">
              <WebsitesLogView
                onFlyToDomainIn3D={handleFlyToDomainIn3D}
                initialDomain={websitesInitialDomain}
              />
            </div>
          ) : viewMode === "2D_TIMELINE" ? (
            <div className="pt-16 pb-8 h-full">
              <TwoDTimelineFallback
                sessions={filteredSessions}
                projects={projects}
                onSelectSession={handleSelectSession}
                selectedSessionId={selectedSession?.id || null}
              />
            </div>
          ) : (
            <SpaceScene
              viewMode={viewMode}
              zoomLevel={zoomLevel}
              sessions={filteredSessions}
              galaxyNodes={galaxyNodes}
              galaxyEdges={galaxyEdges}
              cityTowers={cityTowers}
              selectedSession={selectedSession}
              selectedPage={selectedPage}
              selectedGalaxyNode={selectedGalaxyNode}
              selectedCityDay={selectedCityDay}
              highlightedId={highlightedId}
              isReplaying={isReplaying}
              replayProgress={replayProgress}
              cameraTargetPos={cameraTargetPos}
              onSelectSession={handleSelectSession}
              onSelectPage={handleSelectPage}
              onSelectGalaxyNode={handleSelectGalaxyNode}
              onSelectCityDay={handleSelectCityDay}
              onHoverNode={setHoverInfo}
            />
          )}

          {/* Replay Flight Controller */}
          {viewMode === "JOURNEY" && sessions.length > 0 && (
            <ReplayController
              isReplaying={isReplaying}
              onToggleReplay={() => setIsReplaying(!isReplaying)}
              replayProgress={replayProgress}
              onSeek={setReplayProgress}
              replaySpeed={replaySpeed}
              onSpeedChange={setReplaySpeed}
              currentDateLabel={activeSession?.dateStr || "Today"}
              currentActivityLabel={activeSession?.title || "Exploring Memory"}
            />
          )}

          {/* Docked Chat Panel */}
          <DockedChatPanel onHighlight3DNode={handleChatHighlight} />

          {/* Inspector Panel */}
          <InspectorPanel
            session={selectedSession}
            selectedPage={selectedPage}
            galaxyNode={selectedGalaxyNode}
            isReplaying={isReplaying}
            onClose={() => {
              setSelectedSession(null);
              setSelectedPage(null);
              setSelectedGalaxyNode(null);
            }}
            onSwitchTo2D={handleSwitchTo2D}
            onOpenWebsites={(dom) => {
              setWebsitesInitialDomain(dom);
              setViewMode("WEBSITES");
            }}
          />
        </>
      )}

      {/* 4. History Importer Modal */}
      {isImportModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="max-w-md w-full bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center gap-2 font-bold text-white text-base">
                <Upload className="w-5 h-5 text-cyan-400" />
                Import Browser History
              </div>
              <button
                onClick={() => {
                  setIsImportModalOpen(false);
                  setImportStatus(null);
                }}
                className="text-slate-400 hover:text-white"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <p className="text-xs text-slate-300 leading-relaxed">
              Import past website visits from Microsoft Edge or Google Chrome to populate your 3D roadmap. Sensitive tokens and passwords are automatically scrubbed.
            </p>

            {importStatus && (
              <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 text-xs font-mono text-cyan-300 flex items-center gap-2">
                {importCount !== null ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                ) : (
                  <RefreshCw className="w-4 h-4 animate-spin text-cyan-400 flex-shrink-0" />
                )}
                <span>{importStatus}</span>
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => {
                  setIsImportModalOpen(false);
                  setImportStatus(null);
                }}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold"
              >
                Close
              </button>
              <button
                disabled={isImporting}
                onClick={handleTriggerHistoryImport}
                className="px-4 py-2 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-slate-950 text-xs font-semibold disabled:opacity-50 flex items-center gap-1.5 shadow-md shadow-cyan-500/20"
              >
                <Upload className="w-3.5 h-3.5" />
                {isImporting ? "Importing..." : "Start Import"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 5. Hover Tooltip */}
      {hoverInfo && (
        <div
          className="fixed pointer-events-none z-50 bg-slate-900/95 backdrop-blur-md border border-cyan-500/40 px-3 py-1.5 rounded-lg shadow-xl text-xs -translate-x-1/2 -translate-y-full mb-3"
          style={{ left: hoverInfo.x, top: hoverInfo.y }}
        >
          <div className="font-bold text-cyan-300">{hoverInfo.title}</div>
          <div className="text-[10px] text-slate-400">{hoverInfo.subtitle}</div>
        </div>
      )}
    </div>
  );
};

export default App;
