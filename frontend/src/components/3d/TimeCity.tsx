import React from "react";
import { CityDayTower } from "../../types";

interface TimeCityProps {
  towers: CityDayTower[];
  selectedDayId: string | null;
  onSelectDay: (tower: CityDayTower) => void;
  onHoverNode: (info: { title: string; subtitle: string; x: number; y: number } | null) => void;
}

export const TimeCity: React.FC<TimeCityProps> = ({
  towers,
  selectedDayId,
  onSelectDay,
  onHoverNode,
}) => {
  return (
    <group position={[0, -5, 0]}>
      {/* 1. City Grid Ground Floor */}
      <gridHelper args={[100, 40, "#1e293b", "#0f172a"]} position={[0, 0, 0]} />

      {/* 2. Day Towers */}
      {towers.map((tower) => {
        const isSelected = selectedDayId === tower.id;
        let cumulativeHeight = 0;

        return (
          <group key={tower.id} position={tower.position}>
            {tower.segments.map((seg, sIdx) => {
              const segHeight = seg.height;
              const yPos = cumulativeHeight + segHeight / 2;
              cumulativeHeight += segHeight;

              return (
                <mesh
                  key={`${tower.id}_seg_${sIdx}`}
                  position={[0, yPos, 0]}
                  onClick={(e) => {
                    e.stopPropagation();
                    onSelectDay(tower);
                  }}
                  onPointerOver={(e) => {
                    e.stopPropagation();
                    onHoverNode({
                      title: `${tower.dateStr}: ${tower.totalActiveHours} Active Hours`,
                      subtitle: `${seg.name} (${seg.hours.toFixed(1)}h) • Click to dive into day's Journey Road`,
                      x: e.clientX,
                      y: e.clientY,
                    });
                  }}
                  onPointerOut={() => onHoverNode(null)}
                >
                  <boxGeometry args={[4.2, segHeight, 4.2]} />
                  <meshStandardMaterial
                    color={seg.color}
                    emissive={seg.color}
                    emissiveIntensity={isSelected ? 1.4 : 0.35}
                    roughness={0.2}
                    metalness={0.7}
                  />
                </mesh>
              );
            })}

            {/* Glowing Rooftop Beacon */}
            <mesh position={[0, cumulativeHeight + 0.5, 0]}>
              <sphereGeometry args={[0.5, 16, 16]} />
              <meshBasicMaterial color="#38bdf8" />
            </mesh>
          </group>
        );
      })}
    </group>
  );
};

