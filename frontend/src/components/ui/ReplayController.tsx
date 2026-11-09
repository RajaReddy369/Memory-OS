import React from 'react';
import { Play, Pause, RotateCcw, FastForward, Clock } from 'lucide-react';

interface ReplayControllerProps {
  isReplaying: boolean;
  onToggleReplay: () => void;
  replayProgress: number; // 0.0 to 1.0
  onSeek: (val: number) => void;
  replaySpeed: number; // 1, 2, 5
  onSpeedChange: (speed: number) => void;
  currentDateLabel: string;
  currentActivityLabel: string;
}

export const ReplayController: React.FC<ReplayControllerProps> = ({
  isReplaying,
  onToggleReplay,
  replayProgress,
  onSeek,
  replaySpeed,
  onSpeedChange,
  currentDateLabel,
  currentActivityLabel,
}) => {
  const speeds = [1, 2, 5];

  return (
    <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-20 w-[90%] max-w-2xl bg-slate-900/90 backdrop-blur-md border border-cyan-500/30 rounded-2xl p-4 shadow-2xl shadow-cyan-950/40 text-slate-200">
      <div className="flex items-center justify-between gap-4 mb-2">
        <div className="flex items-center gap-3">
          <button
            onClick={onToggleReplay}
            className={`flex items-center justify-center w-10 h-10 rounded-full font-bold transition-all shadow-md ${
              isReplaying
                ? 'bg-amber-500 hover:bg-amber-400 text-slate-950'
                : 'bg-cyan-500 hover:bg-cyan-400 text-slate-950 shadow-cyan-500/30'
            }`}
            title={isReplaying ? 'Pause Replay' : 'Play Replay'}
          >
            {isReplaying ? <Pause className="w-5 h-5 fill-current" /> : <Play className="w-5 h-5 fill-current ml-0.5" />}
          </button>

          <button
            onClick={() => onSeek(0)}
            className="p-2 hover:bg-slate-800 rounded-lg text-slate-400 hover:text-slate-200 transition-colors"
            title="Restart Journey"
          >
            <RotateCcw className="w-4 h-4" />
          </button>

          <div className="flex items-center gap-1 bg-slate-950/60 p-1 rounded-lg border border-slate-800 text-xs font-mono">
            <FastForward className="w-3.5 h-3.5 text-slate-400 ml-1" />
            {speeds.map((s) => (
              <button
                key={s}
                onClick={() => onSpeedChange(s)}
                className={`px-2 py-0.5 rounded transition-colors ${
                  replaySpeed === s
                    ? 'bg-cyan-500/20 text-cyan-300 font-bold border border-cyan-500/30'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {s}x
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2 text-xs font-mono text-cyan-300 bg-cyan-950/40 border border-cyan-500/20 px-3 py-1.5 rounded-lg max-w-xs truncate">
          <Clock className="w-3.5 h-3.5 flex-shrink-0 text-cyan-400" />
          <span className="font-semibold">{currentDateLabel}</span>
          <span className="text-slate-500">|</span>
          <span className="text-slate-300 truncate" title={currentActivityLabel}>
            {currentActivityLabel}
          </span>
        </div>
      </div>

      {/* Progress Track */}
      <div className="flex items-center gap-3">
        <span className="text-[10px] font-mono text-slate-400 w-8">0%</span>
        <div className="relative flex-1 group">
          <input
            type="range"
            min="0"
            max="1"
            step="0.001"
            value={replayProgress}
            onChange={(e) => onSeek(parseFloat(e.target.value))}
            className="w-full h-2 bg-slate-950 rounded-lg appearance-none cursor-pointer accent-cyan-400 focus:outline-none focus:ring-1 focus:ring-cyan-500"
          />
          <div
            className="absolute top-0 left-0 h-2 bg-gradient-to-r from-cyan-500 to-indigo-500 rounded-lg pointer-events-none"
            style={{ width: `${replayProgress * 100}%` }}
          />
        </div>
        <span className="text-[10px] font-mono text-slate-400 w-8 text-right">
          {Math.round(replayProgress * 100)}%
        </span>
      </div>
    </div>
  );
};
