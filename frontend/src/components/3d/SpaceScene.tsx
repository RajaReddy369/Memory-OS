import React, { useEffect, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls, Stars } from "@react-three/drei";
import * as THREE from "three";
import { CityDayTower, GalaxyEdge, GalaxyNode, PageNode, SessionNode, ViewMode, ZoomLevel } from "../../types";
import { JourneyRoad } from "./JourneyRoad";
import { KnowledgeGalaxy } from "./KnowledgeGalaxy";
import { TimeCity } from "./TimeCity";

interface SpaceSceneProps {
  viewMode: ViewMode;
  zoomLevel: ZoomLevel;
  sessions: SessionNode[];
  galaxyNodes: GalaxyNode[];
  galaxyEdges: GalaxyEdge[];
  cityTowers: CityDayTower[];
  selectedSession: SessionNode | null;
  selectedPage: PageNode | null;
  selectedGalaxyNode: GalaxyNode | null;
  selectedCityDay: CityDayTower | null;
  highlightedId: string | null;
  isReplaying: boolean;
  replayProgress: number;
  cameraTargetPos: [number, number, number] | null;
  onSelectSession: (session: SessionNode) => void;
  onSelectPage: (page: PageNode) => void;
  onSelectGalaxyNode: (node: GalaxyNode) => void;
  onSelectCityDay: (tower: CityDayTower) => void;
  onHoverNode: (info: { title: string; subtitle: string; x: number; y: number } | null) => void;
}

// Internal smooth camera animator
const CameraFlightController: React.FC<{
  targetPos: [number, number, number] | null;
  isReplaying: boolean;
  replayProgress: number;
  sessions: SessionNode[];
}> = ({ targetPos, isReplaying, replayProgress, sessions }) => {
  const controlsRef = useRef<any>(null);

  // Compute curve for replay camera flight
  const curve = React.useMemo(() => {
    if (!sessions || sessions.length < 2) return null;
    const pts = sessions.map((s) => new THREE.Vector3(...s.position3D));
    return new THREE.CatmullRomCurve3(pts, false, "centripetal", 0.5);
  }, [sessions]);

  useFrame(({ camera }) => {
    if (isReplaying && curve) {
      const p = Math.max(0.001, Math.min(0.999, replayProgress));
      const lookAtPoint = curve.getPointAt(p);
      const tangent = curve.getTangentAt(p);

      // Camera sits slightly behind and above the moving marker
      const camPos = lookAtPoint.clone().sub(tangent.clone().multiplyScalar(14)).add(new THREE.Vector3(0, 6, 0));
      camera.position.lerp(camPos, 0.08);
      camera.lookAt(lookAtPoint);
    } else if (targetPos) {
      // Smooth fly-to target position
      const destination = new THREE.Vector3(targetPos[0], targetPos[1] + 6, targetPos[2] + 16);
      camera.position.lerp(destination, 0.06);
      if (controlsRef.current) {
        controlsRef.current.target.lerp(new THREE.Vector3(...targetPos), 0.06);
        controlsRef.current.update();
      }
    }
  });

  return (
    <OrbitControls
      ref={controlsRef}
      enableDamping
      dampingFactor={0.06}
      maxDistance={220}
      minDistance={4}
      rotateSpeed={0.8}
    />
  );
};

export const SpaceScene: React.FC<SpaceSceneProps> = ({
  viewMode,
  zoomLevel,
  sessions,
  galaxyNodes,
  galaxyEdges,
  cityTowers,
  selectedSession,
  selectedPage,
  selectedGalaxyNode,
  selectedCityDay,
  highlightedId,
  isReplaying,
  replayProgress,
  cameraTargetPos,
  onSelectSession,
  onSelectPage,
  onSelectGalaxyNode,
  onSelectCityDay,
  onHoverNode,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // Pause rendering when tab is hidden to save GPU/CPU cycles
  const [isTabVisible, setIsTabVisible] = React.useState(!document.hidden);
  useEffect(() => {
    const handleVisibility = () => setIsTabVisible(!document.hidden);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, []);

  return (
    <div className="w-full h-full relative cursor-grab active:cursor-grabbing">
      <Canvas
        ref={canvasRef}
        camera={{ position: [0, 20, 65], fov: 48, near: 0.1, far: 1000 }}
        gl={{ antialias: true, powerPreference: "high-performance" }}
        frameloop={isTabVisible ? "always" : "never"}
      >
        {/* Deep Space Background Lighting */}
        <color attach="background" args={["#030712"]} />
        <ambientLight intensity={0.65} />
        <pointLight position={[40, 60, 40]} intensity={1.5} color="#38bdf8" />
        <pointLight position={[-40, -30, -30]} intensity={0.9} color="#a855f7" />

        {/* Distant Twinkling Stars */}
        <Stars radius={160} depth={60} count={3500} factor={4} saturation={0.5} fade speed={1.2} />

        {/* Active 3D Mode Switching */}
        {viewMode === "JOURNEY" && (
          <JourneyRoad
            sessions={sessions}
            selectedSession={selectedSession}
            selectedPage={selectedPage}
            zoomLevel={zoomLevel}
            highlightedId={highlightedId}
            isReplaying={isReplaying}
            replayProgress={replayProgress}
            onSelectSession={onSelectSession}
            onSelectPage={onSelectPage}
            onHoverNode={onHoverNode}
          />
        )}

        {viewMode === "GALAXY" && (
          <KnowledgeGalaxy
            nodes={galaxyNodes}
            edges={galaxyEdges}
            selectedNodeId={selectedGalaxyNode?.id || null}
            onSelectNode={onSelectGalaxyNode}
            onHoverNode={onHoverNode}
          />
        )}

        {viewMode === "CITY" && (
          <TimeCity
            towers={cityTowers}
            selectedDayId={selectedCityDay?.id || null}
            onSelectDay={onSelectCityDay}
            onHoverNode={onHoverNode}
          />
        )}

        <CameraFlightController
          targetPos={cameraTargetPos}
          isReplaying={isReplaying}
          replayProgress={replayProgress}
          sessions={sessions}
        />
      </Canvas>
    </div>
  );
};

