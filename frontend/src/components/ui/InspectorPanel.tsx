import React from "react";
import {
  X,
  ExternalLink,
  Clock,
  Calendar,
  FolderCode,
  FileText,
  Compass,
  ArrowRight,
  Code2,
  Bookmark,
  Share2,
  Globe,
  Box,
} from "lucide-react";
import { GalaxyNode, PageNode, SessionNode } from "../../types";

interface InspectorPanelProps {
  session: SessionNode | null;
  selectedPage: PageNode | null;
  galaxyNode?: GalaxyNode | null;
  isReplaying: boolean;
  onClose: () => void;
  onSwitchTo2D: (sessionId: string) => void;
  onOpenWebsites?: (domain: string) => void;
}

export const InspectorPanel: React.FC<InspectorPanelProps> = ({
  session,
  selectedPage,
  galaxyNode,
  isReplaying,
  onClose,
  onSwitchTo2D,
  onOpenWebsites,
}) => {
  if (!session && !galaxyNode) return null;

  // Render for Galaxy Domain Node
  if (!session && galaxyNode) {
    return (
      <aside className="absolute top-16 right-5 bottom-20 w-96 z-20 bg-slate-900/90 backdrop-blur-xl border border-slate-800 rounded-2xl shadow-2xl flex flex-col overflow-hidden animate-in fade-in slide-in-from-right duration-200">
        <div className="p-4 border-b border-slate-800/80 flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 mb-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-cyan-400" />
              <span className="text-[11px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border border-cyan-500/40 text-cyan-300 bg-cyan-950/30">
                {galaxyNode.type}
              </span>
            </div>
            <h2 className="text-base font-bold text-white leading-tight flex items-center gap-2">
              <Globe className="w-4 h-4 text-cyan-400" />
              {galaxyNode.name}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 hover:bg-slate-800 text-slate-400 hover:text-white rounded-lg transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
          <p className="text-slate-300 leading-relaxed">{galaxyNode.details}</p>

          <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-xl space-y-2">
            <span className="text-[10px] font-mono uppercase text-slate-500 tracking-wider">
              Galaxy Node Information
            </span>
            <div className="flex justify-between font-mono text-[11px] text-slate-300">
              <span>Category</span>
              <span className="capitalize text-cyan-300">{galaxyNode.type}</span>
            </div>
            <div className="flex justify-between font-mono text-[11px] text-slate-300">
              <span>Connections</span>
              <span>{galaxyNode.connections.length} linked hubs</span>
            </div>
          </div>
        </div>

        <div className="p-3 bg-slate-950/80 border-t border-slate-800/80 space-y-2">
          {onOpenWebsites && (
            <button
              onClick={() => onOpenWebsites(galaxyNode.name)}
              className="w-full flex items-center justify-center gap-2 py-2 bg-gradient-to-r from-cyan-600 to-indigo-600 hover:from-cyan-500 hover:to-indigo-500 text-white rounded-xl text-xs font-semibold shadow-lg shadow-cyan-900/30 transition-all"
            >
              <Globe className="w-3.5 h-3.5" />
              Open Full Websites & Search Log
            </button>
          )}
        </div>
      </aside>
    );
  }

  if (!session) return null;

  return (
    <aside className="absolute top-16 right-5 bottom-20 w-96 z-20 bg-slate-900/90 backdrop-blur-xl border border-slate-800 rounded-2xl shadow-2xl flex flex-col overflow-hidden animate-in fade-in slide-in-from-right duration-200">
      {/* 1. Header with Project Color Badge */}
      <div className="p-4 border-b border-slate-800/80 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <span
              className="w-2.5 h-2.5 rounded-full"
              style={{ backgroundColor: session.projectColor }}
            />
            <span
              className="text-[11px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border"
              style={{
                color: session.projectColor,
                borderColor: `${session.projectColor}40`,
                backgroundColor: `${session.projectColor}15`,
              }}
            >
              {session.projectName}
            </span>
            {isReplaying && (
              <span className="text-[10px] uppercase font-bold text-cyan-400 bg-cyan-500/20 px-1.5 py-0.5 rounded animate-pulse">
                Replaying
              </span>
            )}
          </div>
          <h2 className="text-sm font-bold text-white leading-tight">
            {selectedPage ? selectedPage.title : session.title}
          </h2>
        </div>

        <button
          onClick={onClose}
          className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-all"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* 2. Scrollable Detail Body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs text-slate-300">
        {/* Live Replay Narration Banner */}
        {isReplaying && (
          <div className="p-3 bg-cyan-950/40 border border-cyan-800/60 rounded-xl space-y-1">
            <span className="text-[10px] font-bold text-cyan-400 uppercase tracking-wide flex items-center gap-1.5">
              <Compass className="w-3.5 h-3.5" /> Replay Live Narration
            </span>
            <p className="text-xs text-slate-200 italic leading-relaxed">
              "{session.summary}"
            </p>
          </div>
        )}

        {/* Time & Duration Meta */}
        <div className="grid grid-cols-2 gap-2 bg-slate-950/60 p-2.5 rounded-xl border border-slate-800/60">
          <div className="flex items-center gap-2 text-slate-400">
            <Clock className="w-3.5 h-3.5 text-cyan-400" />
            <span>{session.durationMinutes} mins active</span>
          </div>
          <div className="flex items-center gap-2 text-slate-400">
            <Calendar className="w-3.5 h-3.5 text-violet-400" />
            <span>{session.dateStr}</span>
          </div>
        </div>

        {/* Session Summary */}
        <div>
          <h3 className="text-[11px] font-bold uppercase text-slate-400 tracking-wider mb-1.5">
            Session Summary
          </h3>
          <p className="text-slate-300 leading-relaxed bg-slate-950/40 p-3 rounded-xl border border-slate-800/50">
            {session.summary}
          </p>
        </div>

        {/* Referrer Navigation Journey Breadcrumbs */}
        {selectedPage && (
          <div className="space-y-1.5">
            <h3 className="text-[11px] font-bold uppercase text-slate-400 tracking-wider flex items-center gap-1.5">
              <Share2 className="w-3.5 h-3.5 text-cyan-400" /> Referrer Journey
            </h3>
            <div className="bg-slate-950/50 p-2.5 rounded-xl border border-slate-800/60 space-y-2 text-[11px]">
              <div>
                <span className="text-slate-500 block mb-0.5">Came from:</span>
                <span className="text-slate-300 font-mono break-all">
                  {selectedPage.referrerUrl || "Direct navigation / Bookmark / Tab switch"}
                </span>
              </div>
              <div className="flex items-center gap-1.5 text-cyan-400 font-semibold">
                <ArrowRight className="w-3.5 h-3.5" />
                <span>Reading on {selectedPage.domain}</span>
              </div>
              <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                <div
                  className="bg-cyan-400 h-full rounded-full transition-all duration-300"
                  style={{ width: `${selectedPage.scrollDepth}%` }}
                />
              </div>
              <span className="text-slate-500 text-[10px]">
                Reached {selectedPage.scrollDepth}% reading depth
              </span>
            </div>
          </div>
        )}

        {/* Pages & Tabs in this Session */}
        <div>
          <h3 className="text-[11px] font-bold uppercase text-slate-400 tracking-wider mb-2">
            Visited Pages & Documents ({session.pages.length})
          </h3>
          <div className="space-y-1.5">
            {session.pages.map((p) => {
              const isSelected = selectedPage?.id === p.id;
              return (
                <div
                  key={p.id}
                  className={`p-2.5 rounded-xl border transition-all ${
                    isSelected
                      ? "bg-cyan-500/10 border-cyan-500/50 text-white"
                      : "bg-slate-950/40 border-slate-800/60 hover:border-slate-700"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="font-semibold truncate">{p.title}</span>
                    <span className="text-[10px] text-slate-500 shrink-0">{p.timeStr}</span>
                  </div>
                  <div className="flex items-center justify-between text-[10px] text-slate-400">
                    <span className="truncate">{p.domain}</span>
                    <span>{Math.round(p.durationSeconds / 60)}m spent</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Scrubbed Typed Code / Text */}
        {session.typedChunks.length > 0 && (
          <div>
            <h3 className="text-[11px] font-bold uppercase text-slate-400 tracking-wider mb-1.5 flex items-center gap-1.5">
              <Code2 className="w-3.5 h-3.5 text-emerald-400" />
              Scrubbed Typed Chunks
            </h3>
            <div className="space-y-1.5">
              {session.typedChunks.map((chunk, cIdx) => (
                <pre
                  key={cIdx}
                  className="bg-slate-950 p-2.5 rounded-xl border border-slate-800 font-mono text-[11px] text-slate-300 overflow-x-auto"
                >
                  <code>{chunk}</code>
                </pre>
              ))}
            </div>
          </div>
        )}

        {/* Files Touched */}
        {session.filesTouched.length > 0 && (
          <div>
            <h3 className="text-[11px] font-bold uppercase text-slate-400 tracking-wider mb-1.5 flex items-center gap-1.5">
              <FolderCode className="w-3.5 h-3.5 text-amber-400" />
              Files Touched
            </h3>
            <div className="space-y-1">
              {session.filesTouched.map((f, idx) => (
                <div
                  key={idx}
                  className="px-2.5 py-1.5 rounded-lg bg-slate-950/60 border border-slate-800/60 text-[11px] font-mono text-slate-300 truncate"
                >
                  {f}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* 3. Footer Action: Open in 2D Timeline & Website Log */}
      <div className="p-3 bg-slate-950/80 border-t border-slate-800/80 space-y-2">
        {onOpenWebsites && session.primaryDomain && (
          <button
            onClick={() => onOpenWebsites(session.primaryDomain)}
            className="w-full flex items-center justify-center gap-2 py-2 bg-cyan-950/40 hover:bg-cyan-900/60 text-cyan-300 rounded-xl text-xs font-semibold transition-all border border-cyan-800/40"
          >
            <Globe className="w-3.5 h-3.5 text-cyan-400" />
            View {session.primaryDomain} Log
          </button>
        )}
        <button
          onClick={() => onSwitchTo2D(session.id)}
          className="w-full flex items-center justify-center gap-2 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-xl text-xs font-semibold transition-all border border-slate-700"
        >
          <ExternalLink className="w-3.5 h-3.5 text-amber-400" />
          Open in 2D Timeline
        </button>
      </div>
    </aside>
  );
};

