import React from "react";
import {
  Compass,
  Globe2,
  Building2,
  ListTree,
  Search,
  RotateCcw,
  Sparkles,
  Layers,
  Calendar,
  Filter,
} from "lucide-react";
import { Project, ViewMode, ZoomLevel } from "../../types";

interface NavbarProps {
  viewMode: ViewMode;
  zoomLevel: ZoomLevel;
  projects: Project[];
  selectedProjectId: string | null;
  searchQuery: string;
  onSetViewMode: (mode: ViewMode) => void;
  onSetZoomLevel: (level: ZoomLevel) => void;
  onSelectProject: (projId: string | null) => void;
  onSearchChange: (q: string) => void;
  onResetCamera: () => void;
}

const ZOOM_STEPS: ZoomLevel[] = ["YEAR", "MONTH", "DAY", "SESSION", "PAGE", "ACTION"];

export const Navbar: React.FC<NavbarProps> = ({
  viewMode,
  zoomLevel,
  projects,
  selectedProjectId,
  searchQuery,
  onSetViewMode,
  onSetZoomLevel,
  onSelectProject,
  onSearchChange,
  onResetCamera,
}) => {
  return (
    <header className="absolute top-0 left-0 right-0 z-30 px-5 py-3 flex items-center justify-between pointer-events-none">
      {/* 1. Brand Logo */}
      <div className="flex items-center gap-3 pointer-events-auto">
        <div className="w-9 h-9 rounded-xl bg-cyan-500/20 border border-cyan-400/40 flex items-center justify-center shadow-lg shadow-cyan-500/20">
          <Sparkles className="w-5 h-5 text-cyan-400 animate-pulse" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="font-bold text-base tracking-tight text-white">MemoryOS</span>
            <span className="text-[10px] uppercase font-semibold px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/30">
              3D Spatial
            </span>
          </div>
          <p className="text-[11px] text-slate-400 font-medium">Cognitive Activity Roadmap</p>
        </div>
      </div>

      {/* 2. Mode Selector Pills */}
      <div className="flex items-center gap-1.5 bg-slate-900/80 backdrop-blur-md p-1.5 rounded-2xl border border-slate-800 shadow-2xl pointer-events-auto">
        <button
          onClick={() => onSetViewMode("JOURNEY")}
          className={`flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-semibold transition-all ${
            viewMode === "JOURNEY"
              ? "bg-cyan-500 text-slate-950 shadow-md shadow-cyan-500/30"
              : "text-slate-300 hover:text-white hover:bg-slate-800/60"
          }`}
        >
          <Compass className="w-4 h-4" />
          Journey Road
        </button>

        <button
          onClick={() => onSetViewMode("GALAXY")}
          className={`flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-semibold transition-all ${
            viewMode === "GALAXY"
              ? "bg-violet-500 text-slate-950 shadow-md shadow-violet-500/30"
              : "text-slate-300 hover:text-white hover:bg-slate-800/60"
          }`}
        >
          <Globe2 className="w-4 h-4" />
          Knowledge Galaxy
        </button>

        <button
          onClick={() => onSetViewMode("CITY")}
          className={`flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-semibold transition-all ${
            viewMode === "CITY"
              ? "bg-emerald-500 text-slate-950 shadow-md shadow-emerald-500/30"
              : "text-slate-300 hover:text-white hover:bg-slate-800/60"
          }`}
        >
          <Building2 className="w-4 h-4" />
          Time City
        </button>

        <button
          onClick={() => onSetViewMode("2D_TIMELINE")}
          className={`flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-semibold transition-all ${
            viewMode === "2D_TIMELINE"
              ? "bg-amber-500 text-slate-950 shadow-md shadow-amber-500/30"
              : "text-slate-300 hover:text-white hover:bg-slate-800/60"
          }`}
        >
          <ListTree className="w-4 h-4" />
          2D Timeline
        </button>

        <button
          onClick={() => onSetViewMode("WEBSITES")}
          className={`flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-semibold transition-all ${
            viewMode === "WEBSITES"
              ? "bg-cyan-400 text-slate-950 shadow-md shadow-cyan-400/30"
              : "text-slate-300 hover:text-white hover:bg-slate-800/60"
          }`}
        >
          <Globe2 className="w-4 h-4" />
          Websites Log
        </button>
      </div>

      {/* 3. Search Bar, Zoom Stepper & Reset Controls */}
      <div className="flex items-center gap-2.5 pointer-events-auto">
        {/* Global Search */}
        <div className="relative">
          <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search memory in 3D..."
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-56 pl-9 pr-3 py-1.5 bg-slate-900/80 backdrop-blur-md border border-slate-800 rounded-xl text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500 transition-all shadow-lg"
          />
        </div>

        {/* Zoom Level Stepper */}
        <div className="flex items-center gap-1 bg-slate-900/80 backdrop-blur-md px-2.5 py-1.5 rounded-xl border border-slate-800 text-xs">
          <Layers className="w-3.5 h-3.5 text-cyan-400 mr-1" />
          {ZOOM_STEPS.map((step) => {
            const isActive = zoomLevel === step;
            return (
              <button
                key={step}
                onClick={() => onSetZoomLevel(step)}
                className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase transition-all ${
                  isActive
                    ? "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                    : "text-slate-500 hover:text-slate-300"
                }`}
              >
                {step.slice(0, 3)}
              </button>
            );
          })}
        </div>

        {/* Project Filter */}
        <select
          value={selectedProjectId || ""}
          onChange={(e) => onSelectProject(e.target.value || null)}
          className="bg-slate-900/80 backdrop-blur-md border border-slate-800 rounded-xl px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-cyan-500"
        >
          <option value="">All Projects</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>

        {/* Reset Camera */}
        <button
          onClick={onResetCamera}
          title="Reset Camera View"
          className="p-2 rounded-xl bg-slate-900/80 backdrop-blur-md border border-slate-800 text-slate-400 hover:text-white hover:bg-slate-800 transition-all shadow-lg"
        >
          <RotateCcw className="w-4 h-4" />
        </button>
      </div>
    </header>
  );
};

