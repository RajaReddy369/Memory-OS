import React, { useState } from 'react';
import { SessionNode, Project } from '../../types';
import { Calendar, Clock, Globe, Laptop, ChevronRight, Layers } from 'lucide-react';

interface TwoDTimelineFallbackProps {
  sessions: SessionNode[];
  projects: Project[];
  onSelectSession: (s: SessionNode) => void;
  selectedSessionId: string | null;
}

export const TwoDTimelineFallback: React.FC<TwoDTimelineFallbackProps> = ({
  sessions,
  projects,
  onSelectSession,
  selectedSessionId,
}) => {
  const [filterProject, setFilterProject] = useState<string>('all');
  const [search, setSearch] = useState('');

  const filtered = sessions.filter((s) => {
    if (filterProject !== 'all' && s.projectId !== filterProject) return false;
    if (search.trim()) {
      const q = search.toLowerCase();
      const matchTitle = s.title.toLowerCase().includes(q);
      const matchSummary = s.summary.toLowerCase().includes(q);
      const matchApp = s.primaryApp.toLowerCase().includes(q);
      const matchDomain = s.primaryDomain.toLowerCase().includes(q);
      if (!matchTitle && !matchSummary && !matchApp && !matchDomain) return false;
    }
    return true;
  });

  const grouped = filtered.reduce<Record<string, SessionNode[]>>((acc, s) => {
    const day = s.dateStr;
    if (!acc[day]) acc[day] = [];
    acc[day].push(s);
    return acc;
  }, {});

  const dates = Object.keys(grouped);

  return (
    <div className="w-full h-full overflow-y-auto bg-slate-950 p-8 text-slate-200">
      <div className="max-w-4xl mx-auto space-y-6">
        {/* Header & Filters */}
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-800 pb-4">
          <div>
            <h1 className="text-xl font-bold text-cyan-300 flex items-center gap-2">
              <Layers className="w-5 h-5 text-cyan-400" />
              2D Journey Timeline
            </h1>
            <p className="text-xs text-slate-400 mt-1">
              Low-resource chronological list view of digital sessions and captured activities
            </p>
          </div>

          <div className="flex items-center gap-3">
            <input
              type="text"
              placeholder="Filter activities..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-cyan-500 w-48"
            />
            <select
              value={filterProject}
              onChange={(e) => setFilterProject(e.target.value)}
              className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-cyan-500"
            >
              <option value="all">All Projects</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Timeline by date */}
        {dates.length === 0 ? (
          <div className="text-center py-20 text-slate-500 text-sm">
            No sessions match your filter criteria.
          </div>
        ) : (
          <div className="space-y-8">
            {dates.map((day) => {
              const daySessions = grouped[day];
              const totalMin = daySessions.reduce((acc, s) => acc + s.durationMinutes, 0);

              return (
                <div key={day} className="relative pl-6 border-l-2 border-cyan-500/30 space-y-4">
                  {/* Date Badge on Timeline */}
                  <div className="absolute -left-2.5 top-0 w-5 h-5 rounded-full bg-slate-900 border-2 border-cyan-400 flex items-center justify-center">
                    <div className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
                  </div>

                  <div className="flex items-center justify-between pb-1">
                    <span className="font-mono text-sm font-bold text-cyan-300 flex items-center gap-2">
                      <Calendar className="w-4 h-4 text-cyan-400" />
                      {day}
                    </span>
                    <span className="text-xs text-slate-400 font-mono">
                      {daySessions.length} session{daySessions.length > 1 ? 's' : ''} ({totalMin}m total)
                    </span>
                  </div>

                  {/* Sessions */}
                  <div className="grid gap-3">
                    {daySessions.map((session) => {
                      const isSelected = selectedSessionId === session.id;

                      return (
                        <div
                          key={session.id}
                          onClick={() => onSelectSession(session)}
                          className={`group cursor-pointer rounded-xl p-4 transition-all border ${
                            isSelected
                              ? 'bg-slate-900/90 border-cyan-400 shadow-lg shadow-cyan-950/50 ring-1 ring-cyan-500/50'
                              : 'bg-slate-900/40 border-slate-800 hover:border-slate-700 hover:bg-slate-900/70'
                          }`}
                        >
                          <div className="flex items-start justify-between gap-4">
                            <div className="space-y-1.5 flex-1">
                              <div className="flex items-center gap-2">
                                <span
                                  className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                                  style={{ backgroundColor: session.projectColor || '#38bdf8' }}
                                />
                                <span className="text-xs font-mono font-medium text-slate-400">
                                  {session.projectName || 'General'}
                                </span>
                                <span className="text-slate-600">•</span>
                                <span className="text-xs font-mono text-slate-400 flex items-center gap-1">
                                  <Clock className="w-3 h-3 text-slate-500" />
                                  {session.timeStr} ({session.durationMinutes}m)
                                </span>
                              </div>

                              <h3 className="text-sm font-semibold text-slate-100 group-hover:text-cyan-300 transition-colors">
                                {session.title}
                              </h3>

                              <p className="text-xs text-slate-400 line-clamp-2 leading-relaxed">
                                {session.summary}
                              </p>
                            </div>

                            <ChevronRight
                              className={`w-5 h-5 text-slate-500 group-hover:text-cyan-400 transition-transform ${
                                isSelected ? 'rotate-90 text-cyan-400' : 'group-hover:translate-x-1'
                              }`}
                            />
                          </div>

                          {/* App & Page chips */}
                          <div className="mt-3 pt-3 border-t border-slate-800/60 flex flex-wrap items-center gap-2 text-[11px]">
                            <span className="px-2 py-0.5 rounded-md bg-slate-800/80 text-slate-300 border border-slate-700/50 flex items-center gap-1 font-mono">
                              <Laptop className="w-3 h-3 text-slate-400" />
                              {session.primaryApp}
                            </span>

                            {session.primaryDomain && (
                              <span className="px-2 py-0.5 rounded-md bg-cyan-950/40 text-cyan-300 border border-cyan-800/30 flex items-center gap-1 font-mono truncate max-w-xs">
                                <Globe className="w-3 h-3 text-cyan-400" />
                                {session.primaryDomain}
                              </span>
                            )}

                            {session.pages.length > 0 && (
                              <span className="text-slate-500 font-mono text-[10px]">
                                {session.pages.length} visited pages
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
