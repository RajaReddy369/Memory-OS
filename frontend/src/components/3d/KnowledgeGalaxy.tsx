import React, { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import { GalaxyEdge, GalaxyNode } from "../../types";

interface KnowledgeGalaxyProps {
  nodes: GalaxyNode[];
  edges: GalaxyEdge[];
  selectedNodeId: string | null;
  onSelectNode: (node: GalaxyNode) => void;
  onHoverNode: (info: { title: string; subtitle: string; x: number; y: number } | null) => void;
}

export const KnowledgeGalaxy: React.FC<KnowledgeGalaxyProps> = ({
  nodes,
  edges,
  selectedNodeId,
  onSelectNode,
  onHoverNode,
}) => {
  const galaxyGroupRef = useRef<THREE.Group>(null);

  // Slow ambient rotation of the cosmic galaxy
  useFrame((_, delta) => {
    if (galaxyGroupRef.current) {
      galaxyGroupRef.current.rotation.y += delta * 0.04;
    }
  });

  return (
    <group ref={galaxyGroupRef}>
      {/* 1. Connecting Edges */}
      {edges.map((edge) => {
        const sourceNode = nodes.find((n) => n.id === edge.source);
        const targetNode = nodes.find((n) => n.id === edge.target);
        if (!sourceNode || !targetNode) return null;

        const pts = [
          new THREE.Vector3(...sourceNode.position),
          new THREE.Vector3(
            (sourceNode.position[0] + targetNode.position[0]) * 0.5,
            (sourceNode.position[1] + targetNode.position[1]) * 0.5 + 2.5,
            (sourceNode.position[2] + targetNode.position[2]) * 0.5
          ),
          new THREE.Vector3(...targetNode.position),
        ];
        const curve = new THREE.QuadraticBezierCurve3(pts[0], pts[1], pts[2]);

        return (
          <line key={edge.id}>
            <bufferGeometry
              attach="geometry"
              {...new THREE.BufferGeometry().setFromPoints(curve.getPoints(24))}
            />
            <lineBasicMaterial
              color={edge.color}
              transparent
              opacity={0.35}
              linewidth={1}
            />
          </line>
        );
      })}

      {/* 2. Galaxy Nodes */}
      {nodes.map((node) => {
        const isSelected = selectedNodeId === node.id;
        return (
          <group key={node.id} position={node.position}>
            {/* Center Core */}
            <mesh
              onClick={(e) => {
                e.stopPropagation();
                onSelectNode(node);
              }}
              onPointerOver={(e) => {
                e.stopPropagation();
                onHoverNode({
                  title: node.name,
                  subtitle: `${node.type.toUpperCase()} • ${node.details}`,
                  x: e.clientX,
                  y: e.clientY,
                });
              }}
              onPointerOut={() => onHoverNode(null)}
            >
              <sphereGeometry args={[node.size, 32, 32]} />
              <meshStandardMaterial
                color={node.color}
                emissive={node.color}
                emissiveIntensity={isSelected ? 2.0 : node.glow ? 1.0 : 0.4}
                roughness={0.2}
                metalness={0.6}
              />
            </mesh>

            {/* Glowing Atmosphere Shell */}
            <mesh scale={[1.35, 1.35, 1.35]}>
              <sphereGeometry args={[node.size, 16, 16]} />
              <meshBasicMaterial
                color={node.color}
                transparent
                opacity={node.glow ? 0.25 : 0.08}
                side={THREE.BackSide}
              />
            </mesh>
          </group>
        );
      })}
    </group>
  );
};
