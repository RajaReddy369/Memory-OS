export type ViewMode = "JOURNEY" | "GALAXY" | "CITY" | "2D_TIMELINE";

export type ZoomLevel = "YEAR" | "MONTH" | "DAY" | "SESSION" | "PAGE" | "ACTION";

export interface Project {
  id: string;
  name: string;
  color: string;
  glowColor: string;
  description: string;
  totalHours: number;
}

export interface ActionItem {
  id: string;
  type: "typed_code" | "scroll_depth" | "highlight" | "file_edit";
  timestamp: number;
  timeStr: string;
  summary: string;
  content?: string;
  details?: Record<string, any>;
}

export interface PageNode {
  id: string;
  sessionId: string;
  title: string;
  url: string;
  domain: string;
  appName: string;
  durationSeconds: number;
  timeStr: string;
  timestamp: number;
  scrollDepth: number;
  referrerUrl?: string;
  fromEventId?: string;
  actions: ActionItem[];
}

export interface SessionNode {
  id: string;
  title: string;
  summary: string;
  projectId: string;
  projectName: string;
  projectColor: string;
  startTime: number;
  endTime: number;
  durationMinutes: number;
  timeStr: string;
  dateStr: string;
  primaryApp: string;
  primaryDomain: string;
  eventCount: number;
  position3D: [number, number, number];
  pages: PageNode[];
  filesTouched: string[];
  typedChunks: string[];
}

export interface GalaxyNode {
  id: string;
  name: string;
  type: "project" | "domain" | "topic" | "file";
  size: number;
  color: string;
  glow: boolean;
  position: [number, number, number];
  connections: string[];
  details: string;
}

export interface GalaxyEdge {
  id: string;
  source: string;
  target: string;
  weight: number;
  color: string;
}

export interface CityDayTower {
  id: string;
  dateStr: string;
  timestamp: number;
  totalActiveHours: number;
  sessionsCount: number;
  position: [number, number, number];
  segments: {
    name: string;
    type: "app" | "domain";
    color: string;
    hours: number;
    height: number;
  }[];
}

export interface CitationReference {
  event_id: number | string;
  title: string;
  url?: string;
  domain?: string;
  timestamp: number;
  time_str: string;
  snippet: string;
  score?: number;
}
