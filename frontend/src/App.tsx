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
} from "./types";
import {
  SAMPLE_PROJECTS,
  generateCityTowers,
  generateGalaxyData,
  generateSampleSessions,
} from "./data/sampleData";
import { SpaceScene } from "./components/3d/SpaceScene";
import { Navbar } from "./components/ui/Navbar";
import { InspectorPanel } from "./components/ui/InspectorPanel";
import { DockedChatPanel } from "./components/ui/DockedChatPanel";
import { ReplayController } from "./components/ui/ReplayController";
import { TwoDTimelineFallback } from "./components/ui/TwoDTimelineFallback";
import { WebsitesLogView } from "./components/ui/WebsitesLogView";

export const App: React.FC = () => {
  // 1. Data state
  const projects: Project[] = SAMPLE_PROJECTS;
  const sessions: SessionNode[] = useMemo(() => generateSampleSessions(), []);
  const { nodes: galaxyNodes, edges: galaxyEdges } = useMemo(
    () => generateGalaxyData(),
    []
  );
  const cityTowers: CityDayTower[] = useMemo(() => generateCityTowers(), []);

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
    // Find sessions on this day and switch to Road view
    const match = sessions.find((s) => s.dateStr === tower.dateStr);
    if (match) {
      setSelectedSession(match);
    }
  };

  // Reset camera handler
  const handleResetCamera = () => {
    setCameraTargetPos([0, 20, 45]);
    setSelectedSession(null);
    setSelectedPage(null);
    setHighlightedId(null);
    setZoomLevel("DAY");
  };

  // Highlight 3D node from Chat citation click
  const handleChatHighlight = (
    nodeId: string,
    pos?: [number, number, number]
  ) => {
    setHighlightedId(nodeId);
    if (pos) {
      setCameraTargetPos(pos);
    } else {
      // Find matching session
      const found = sessions.find((s) => s.id === nodeId);
      if (found) {
        setSelectedSession(found);
        setCameraTargetPos(found.position3D);
      }
    }
  };

  // Switch to 2D view from inspector
  const handleSwitchTo2D = (sessionId: string) => {
    setViewMode("2D_TIMELINE");
    const found = sessions.find((s) => s.id === sessionId);
    if (found) setSelectedSession(found);
  };

  // Current session label for replay bar
  const activeSessionIndex = Math.min(
    Math.floor(replayProgress * sessions.length),
    Math.max(0, sessions.length - 1)
  );
  const activeSession = sessions[activeSessionIndex] || sessions[0];

  return (
    <div className="relative w-screen h-screen bg-[#030712] overflow-hidden select-none font-sans text-slate-100">
      {/* 1. Top Navbar */}
      <Navbar
        viewMode={viewMode}
        zoomLevel={zoomLevel}
        projects={projects}
        selectedProjectId={selectedProjectId}
        searchQuery={searchQuery}
        onSetViewMode={setViewMode}
        onSetZoomLevel={setZoomLevel}
        onSelectProject={setSelectedProjectId}
        onSearchChange={setSearchQuery}
        onResetCamera={handleResetCamera}
      />

      {/* 2. Main Canvas, 2D View, or Websites Log View */}
      {viewMode === "WEBSITES" ? (
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

      {/* 3. Replay Flight Controller (available on 3D views) */}
      {viewMode === "JOURNEY" && (
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

      {/* 4. Docked Chat Panel (Bottom-Left) */}
      <DockedChatPanel onHighlight3DNode={handleChatHighlight} />

      {/* 5. Inspector Panel (Slide-out Right) */}
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

      {/* 6. Hover Tooltip */}
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

