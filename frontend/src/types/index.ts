declare global {
  const chrome: any;
}

export type ViewMode = "JOURNEY" | "GALAXY" | "CITY" | "2D_TIMELINE" | "WEBSITES";

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

export interface WebsitePageItem {
  id: number;
  title: string;
  url: string;
  timestamp: number;
  duration: number;
  scroll_depth?: number;
}

export interface WebsiteSearchQueryItem {
  id: number;
  query: string;
  engine: string;
  timestamp: number;
  url: string;
}

export interface WebsiteTypedItem {
  id: number;
  text: string;
  timestamp: number;
  url: string;
}

export interface WebsiteHighlightItem {
  id: number;
  text: string;
  timestamp: number;
  url: string;
}

export interface WebsiteNavigationLink {
  type: "came_from" | "went_to";
  from_domain: string;
  to_domain: string;
  referrer_url: string;
  target_url: string;
  timestamp: number;
}

export interface WebsiteSummaryItem {
  domain: string;
  first_visit: number;
  last_visit: number;
  total_visits: number;
  total_active_time: number;
  search_count: number;
  typed_count: number;
  pages: WebsitePageItem[];
}

export interface WebsiteDetail {
  domain: string;
  first_visit: number;
  last_visit: number;
  total_visits: number;
  total_active_time: number;
  pages_visited: WebsitePageItem[];
  search_queries: WebsiteSearchQueryItem[];
  typed_text: WebsiteTypedItem[];
  highlights: WebsiteHighlightItem[];
  navigation_links: WebsiteNavigationLink[];
}

export interface SearchTimelineItem {
  id: number;
  query: string;
  engine: string;
  domain: string;
  url: string;
  title: string;
  timestamp: number;
  result_page?: {
    title: string;
    url: string;
  } | null;
}

export interface YouTubeVideoItem {
  video_id: string;
  title: string;
  channel?: string;
  description?: string;
  duration: number;
  play_time: number;
  upload_date?: string;
  search_query?: string;
  referrer_url?: string;
  created_at: number;
  updated_at: number;
}

export interface BranchTreeNode {
  id: string;
  type: "domain" | "search" | "page" | "video";
  label?: string;
  query?: string;
  title?: string;
  url?: string;
  domain?: string;
  channel?: string;
  duration?: number;
  play_time?: number;
  timestamp?: number;
  children?: BranchTreeNode[];
}


export interface Graph3DNode {
  id: string;
  eventId?: number;
  name: string;
  type: "region" | "city" | "building";
  subType?: string;
  city?: string;
  url?: string;
  source?: string;
  timestamp?: number;
  duration?: number;
  height?: number;
  scroll_depth?: number;
  position: [number, number, number];
  provenance?: string;
}

export interface Graph3DEdge {
  id: string;
  source: string;
  target: string;
  type: "road" | "branch" | "referrer";
  weight: number;
}

export interface Graph3DResponse {
  nodes: Graph3DNode[];
  edges: Graph3DEdge[];
  meta: {
    total_nodes: number;
    total_edges: number;
    total_events: number;
    date_span_days: number;
    total_domains: number;
    data_source: string;
  };
}

export interface DataSummary {
  total_events: number;
  first_timestamp: number | null;
  last_timestamp: number | null;
  date_span_days: number;
  total_domains: number;
  total_apps: number;
  total_files: number;
  sources: Record<string, number>;
}



