import React, { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { PageNode, SessionNode, ZoomLevel } from "../../types";

interface JourneyRoadProps {
  sessions: SessionNode[];
  selectedSession: SessionNode | null;
  selectedPage: PageNode | null;
  zoomLevel: ZoomLevel;
  highlightedId: string | null;
  isReplaying: boolean;
  replayProgress: number; // 0.0 to 1.0
  onSelectSession: (session: SessionNode) => void;
  onSelectPage: (page: PageNode) => void;
  onHoverNode: (info: { title: string; subtitle: string; x: number; y: number } | null) => void;
}

export const JourneyRoad: React.FC<JourneyRoadProps> = ({
  sessions,
  selectedSession,
  selectedPage,
  zoomLevel,
  highlightedId,
  isReplaying,
  replayProgress,
  onSelectSession,
  onSelectPage,
  onHoverNode,
}) => {
  // 1. Construct 3D Spline Curve through session positions
  const { curve, points } = useMemo(() => {
    if (!sessions || sessions.length < 2) {
      return { curve: null, points: [] };
    }
    const pts = sessions.map((s) => new THREE.Vector3(...s.position3D));
    const spline = new THREE.CatmullRomCurve3(pts, false, "centripetal", 0.5);
    return { curve: spline, points: pts };
  }, [sessions]);

  // Tube geometry for the glowing road ribbon
  const tubeGeometry = useMemo(() => {
    if (!curve) return null;
    return new THREE.TubeGeometry(curve, 300, 0.45, 12, false);
  }, [curve]);

  // Replay vehicle / camera target marker
  const vehicleRef = useRef<THREE.Mesh>(null);

  useFrame(() => {
    if (isReplaying && curve && vehicleRef.current) {
      const clampedProgress = Math.max(0.001, Math.min(0.999, replayProgress));
      const pos = curve.getPointAt(clampedProgress);
      vehicleRef.current.position.copy(pos);
    }
  });

  return (
    <group>
      {/* 1. Main Glowing Road Ribbon */}
      {tubeGeometry && (
        <mesh geometry={tubeGeometry}>
          <meshStandardMaterial
            color="#0891b2"
            emissive="#06b6d4"
            emissiveIntensity={0.8}
            roughness={0.2}
            metalness={0.8}
            transparent
            opacity={0.85}
          />
        </mesh>
      )}

      {/* 2. Secondary Ambient Ground Glow Line */}
      {curve && (
        <line>
          <bufferGeometry
            attach="geometry"
            {...new THREE.BufferGeometry().setFromPoints(curve.getPoints(200))}
          />
          <lineBasicMaterial color="#38bdf8" linewidth={2} transparent opacity={0.6} />
        </line>
      )}

      {/* 3. Session Stops */}
      {sessions.map((session, index) => {
        const isSelected = selectedSession?.id === session.id;
        const isHighlighted = highlightedId === session.id;
        const radius = Math.max(0.7, Math.min(1.8, Math.sqrt(session.durationMinutes) * 0.16));

        return (
          <group key={session.id} position={session.position3D}>
            {/* Core Stop Sphere */}
            <mesh
              onClick={(e) => {
                e.stopPropagation();
                onSelectSession(session);
              }}
              onPointerOver={(e) => {
                e.stopPropagation();
                onHoverNode({
                  title: session.title,
                  subtitle: `${session.projectName} • ${session.durationMinutes} mins • ${session.dateStr}`,
                  x: e.clientX,
                  y: e.clientY,
                });
              }}
              onPointerOut={() => onHoverNode(null)}
            >
              <sphereGeometry args={[radius, 32, 32]} />
              <meshStandardMaterial
                color={session.projectColor}
                emissive={session.projectColor}
                emissiveIntensity={isSelected || isHighlighted ? 1.8 : 0.6}
                roughness={0.15}
                metalness={0.5}
              />
            </mesh>

            {/* Pulsing Selection Halo Ring */}
            {(isSelected || isHighlighted) && (
              <mesh rotation={[Math.PI / 2, 0, 0]}>
                <ringGeometry args={[radius * 1.3, radius * 1.6, 32]} />
                <meshBasicMaterial
                  color={isHighlighted ? "#fbbf24" : session.projectColor}
                  side={THREE.DoubleSide}
                  transparent
                  opacity={0.8}
                />
              </mesh>
            )}

            {/* Parallel Branches for Sub-Pages when zoomed in */}
            {isSelected &&
              ["SESSION", "PAGE", "ACTION"].includes(zoomLevel) &&
              session.pages.map((page, pIdx) => {
                const angle = (pIdx / session.pages.length) * Math.PI * 2;
                const branchRadius = 3.8;
                const px = Math.cos(angle) * branchRadius;
                const pz = Math.sin(angle) * branchRadius;
                const py = Math.sin(pIdx * 1.5) * 1.2;
                const isPageSelected = selectedPage?.id === page.id;

                return (
                  <group key={page.id} position={[px, py, pz]}>
                    {/* Connecting Branch Line */}
                    <line>
                      <bufferGeometry
                        attach="geometry"
                        {...new THREE.BufferGeometry().setFromPoints([
                          new THREE.Vector3(0, 0, 0),
                          new THREE.Vector3(px, py, pz).negate(),
                        ])}
                      />
                      <lineBasicMaterial
                        color={session.projectColor}
                        transparent
                        opacity={0.5}
                        linewidth={1}
                      />
                    </line>

                    {/* Page Sphere Node */}
                    <mesh
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectPage(page);
                      }}
                      onPointerOver={(e) => {
                        e.stopPropagation();
                        onHoverNode({
                          title: page.title,
                          subtitle: `${page.domain} • ${page.appName} • ${page.scrollDepth}% read`,
                          x: e.clientX,
                          y: e.clientY,
                        });
                      }}
                      onPointerOut={() => onHoverNode(null)}
                    >
                      <sphereGeometry args={[0.42, 16, 16]} />
                      <meshStandardMaterial
                        color={isPageSelected ? "#ffffff" : session.projectColor}
                        emissive={session.projectColor}
                        emissiveIntensity={isPageSelected ? 1.5 : 0.4}
                      />
                    </mesh>

                    {/* Action Satellite Marker */}
                    {["PAGE", "ACTION"].includes(zoomLevel) &&
                      page.actions.map((act, aIdx) => (
                        <mesh
                          key={act.id}
                          position={[
                            Math.cos(aIdx * 2) * 1.1,
                            Math.sin(aIdx * 2) * 1.1,
                            0.2,
                          ]}
                        >
                          <boxGeometry args={[0.2, 0.2, 0.2]} />
                          <meshStandardMaterial
                            color="#38bdf8"
                            emissive="#38bdf8"
                            emissiveIntensity={0.8}
                          />
                        </mesh>
                      ))}
                  </group>
                );
              })}
          </group>
        );
      })}

      {/* 4. Replay Vehicle / Camera Pointer */}
      <mesh ref={vehicleRef}>
        <sphereGeometry args={[0.75, 16, 16]} />
        <meshBasicMaterial color="#ffffff" />
        <pointLight color="#38bdf8" intensity={4} distance={15} />
      </mesh>
    </group>
  );
};
