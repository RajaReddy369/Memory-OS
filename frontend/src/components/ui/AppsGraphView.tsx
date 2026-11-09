import React, { useState, useEffect } from "react";
import {
  Cpu,
  FolderTree,
  Network,
  Route,
  Users,
  Search,
  Filter,
  RefreshCw,
  Trash2,
  ExternalLink,
  ChevronRight,
  ChevronDown,
  Monitor,
  FileCode,
  Globe,
  Clock,
  ArrowRight,
  Shield,
  Layers,
  Sparkles,
  FileText,
  Activity
} from "lucide-react";
import { AppTreeNode, GraphCommunityItem, GraphNeighborData } from "../../types";

interface AppsGraphViewProps {
  onClose?: () => void;
  onSelectNodeIn3D?: (nodeId: string) => void;
}

export const AppsGraphView: React.FC<AppsGraphViewProps> = ({
  onClose,
  onSelectNodeIn3D,
}) => {
  const [activeTab, setActiveTab] = useState<"tree" | "neighbors" | "path" | "communities">("tree");
  const [isLoading, setIsLoading] = useState(false);
  const [treeData, setTreeData] = useState<AppTreeNode | null>(null);
  const [communities, setCommunities] = useState<GraphCommunityItem[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string>("root:desktop");
  const [neighborData, setNeighborData] = useState<GraphNeighborData | null>(null);

  // Path Traversal State
  const [pathFrom, setPathFrom] = useState("code.exe");
  const [pathTo, setPathTo] = useState("msedge.exe");
  const [pathResult, setPathResult] = useState<any | null>(null);
  const [isSearchingPath, setIsSearchingPath] = useState(false);

  // Filters & Search
  const [searchQuery, setSearchQuery] = useState("");
  const [expandedNodes, setExpandedNodes] = useState<Record<string, boolean>>({ "root:desktop": true });
  const [deleteStatus, setDeleteStatus] = useState<string | null>(null);

  const [token, setToken] = useState<string>(() => localStorage.getItem("memoryos_token") || "");

  // Auto-handshake with local API for token
  const getAuthToken = async (): Promise<string> => {
    let t = token || localStorage.getItem("memoryos_token") || "";
    if (t) return t;

    try {
      if (typeof chrome !== "undefined" && chrome?.storage?.local) {
        const stored = await chrome.storage.local.get(["apiKey"]);
        if (stored?.apiKey) {
          localStorage.setItem("memoryos_token", stored.apiKey);
          setToken(stored.apiKey);
          return stored.apiKey;
        }
      }
    } catch {}

    try {
      const authRes = await fetch("http://127.0.0.1:8000/api/auth/token");
      if (authRes.ok) {
        const data = await authRes.json();
        if (data.token) {
          localStorage.setItem("memoryos_token", data.token);
          setToken(data.token);
          if (typeof chrome !== "undefined" && chrome?.storage?.local) {
            chrome.storage.local.set({ apiKey: data.token });
          }
          return data.token;
        }
      }
    } catch {}

    return "";
  };

  // 1. Fetch Apps Tree
  const fetchTree = async () => {
    setIsLoading(true);
    const activeToken = await getAuthToken();
    try {
      const res = await fetch("http://127.0.0.1:8000/api/apps/tree", {
        headers: activeToken ? { "X-MemoryOS-Key": activeToken } : {},
      });
      if (res.ok) {
        const data = await res.json();
        setTreeData(data);
        // Expand first level apps automatically
        if (data && data.children) {
          const initExp: Record<string, boolean> = { "root:desktop": true };
          data.children.forEach((c: AppTreeNode) => {
            initExp[c.id] = true;
          });
          setExpandedNodes((prev) => ({ ...prev, ...initExp }));
        }
      }
    } catch (e) {
      console.error("Failed to fetch apps tree", e);
    } finally {
      setIsLoading(false);
    }
  };

  // 2. Fetch Neighbor Subgraph
  const fetchNeighbors = async (nodeId: string) => {
    const activeToken = await getAuthToken();
    try {
      const res = await fetch(`http://127.0.0.1:8000/api/graph/neighbors?id=${encodeURIComponent(nodeId)}&hops=2`, {
        headers: activeToken ? { "X-MemoryOS-Key": activeToken } : {},
      });
      if (res.ok) {
        const data = await res.json();
        setNeighborData(data);
      }
    } catch (e) {
      console.error("Failed to fetch neighbors", e);
    }
  };

  // 3. Fetch Communities
  const fetchCommunities = async () => {
    const activeToken = await getAuthToken();
    try {
      const res = await fetch("http://127.0.0.1:8000/api/graph/communities", {
        headers: activeToken ? { "X-MemoryOS-Key": activeToken } : {},
      });
      if (res.ok) {
        const data = await res.json();
        setCommunities(Array.isArray(data) ? data : []);
      }
    } catch (e) {
      console.error("Failed to fetch communities", e);
    }
  };

  // 4. Execute Path Traversal
  const handleFindPath = async () => {
    if (!pathFrom || !pathTo) return;
    setIsSearchingPath(true);
    const activeToken = await getAuthToken();
    try {
      const res = await fetch(
        `http://127.0.0.1:8000/api/graph/path?from=${encodeURIComponent(pathFrom)}&to=${encodeURIComponent(pathTo)}`,
        { headers: activeToken ? { "X-MemoryOS-Key": activeToken } : {} }
      );
      if (res.ok) {
        const data = await res.json();
        setPathResult(data);
      } else {
        setPathResult({ found: false, message: "No connecting path found." });
      }
    } catch (e) {
      setPathResult({ found: false, message: "Error calculating graph path." });
    } finally {
      setIsSearchingPath(false);
    }
  };

  // 5. Delete App History
  const handleDeleteApp = async (appId: string) => {
    const appName = appId.replace("app:", "");
    if (!window.confirm(`Permanently delete all graph nodes, sessions, and history for ${appName}? This cannot be undone.`)) {
      return;
    }
    const activeToken = await getAuthToken();
    try {
      const res = await fetch(`http://127.0.0.1:8000/api/apps/${encodeURIComponent(appName)}`, {
        method: "DELETE",
        headers: activeToken ? { "X-MemoryOS-Key": activeToken } : {},
      });
      if (res.ok) {
        setDeleteStatus(`Deleted history for ${appName}`);
        fetchTree();
        fetchCommunities();
        if (selectedNodeId === appId) {
          setSelectedNodeId("root:desktop");
        }
      }
    } catch (e) {
      setDeleteStatus(`Failed to delete ${appName}`);
    }
    setTimeout(() => setDeleteStatus(null), 4000);
  };

  useEffect(() => {
    fetchTree();
    fetchCommunities();
  }, []);

  useEffect(() => {
    if (selectedNodeId) {
      fetchNeighbors(selectedNodeId);
    }
  }, [selectedNodeId]);

  const toggleExpand = (id: string) => {
    setExpandedNodes((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  // Helper node icon
  const getNodeIcon = (type: string) => {
    switch (type) {
      case "root":
        return <Monitor className="w-4 h-4 text-cyan-400" />;
      case "app":
        return <Cpu className="w-4 h-4 text-fuchsia-400" />;
      case "app_session":
        return <Clock className="w-4 h-4 text-amber-400" />;
      case "window_item":
        return <FileText className="w-4 h-4 text-emerald-400" />;
      case "file":
        return <FileCode className="w-4 h-4 text-blue-400" />;
      case "website":
        return <Globe className="w-4 h-4 text-cyan-300" />;
      case "search_query":
        return <Search className="w-4 h-4 text-purple-400" />;
      default:
        return <Activity className="w-4 h-4 text-slate-400" />;
    }
  };

  // Recursive Tree Item Renderer
  const renderTreeItem = (node: AppTreeNode, depth = 0) => {
    const isExpanded = !!expandedNodes[node.id];
    const hasChildren = node.children && node.children.length > 0;
    const isSelected = selectedNodeId === node.id;

    // Filter match
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const matchesSelf = node.label.toLowerCase().includes(q) || node.id.toLowerCase().includes(q);
      const matchesChild = JSON.stringify(node.children || []).toLowerCase().includes(q);
      if (!matchesSelf && !matchesChild) return null;
    }

    return (
      <div key={node.id} className="select-none text-xs font-sans">
        <div
          onClick={() => setSelectedNodeId(node.id)}
          className={`group flex items-center justify-between py-1.5 px-2 rounded-lg cursor-pointer transition-colors ${
            isSelected
              ? "bg-fuchsia-950/60 border border-fuchsia-500/40 text-white"
              : "hover:bg-slate-800/60 text-slate-300 border border-transparent"
          }`}
          style={{ paddingLeft: `${Math.max(8, depth * 16)}px` }}
        >
          <div className="flex items-center gap-2 overflow-hidden">
            {hasChildren ? (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  toggleExpand(node.id);
                }}
                className="w-4 h-4 flex items-center justify-center text-slate-500 hover:text-white"
              >
                {isExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
              </button>
            ) : (
              <span className="w-4" />
            )}

            {getNodeIcon(node.node_type)}

            <span className="font-medium truncate max-w-[220px]" title={node.label}>
              {node.label}
            </span>

            <span className="text-[10px] px-1 py-0.2 rounded bg-slate-800 text-slate-400 font-mono">
              {node.node_type}
            </span>
          </div>

          <div className="flex items-center gap-2 text-[11px] text-slate-400 font-mono">
            {node.weight > 0 && (
              <span>
                {node.weight >= 60 ? `${Math.round(node.weight / 60)}m` : `${Math.round(node.weight)}s`}
              </span>
            )}

            {node.node_type === "app" && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleDeleteApp(node.id);
                }}
                title="Permanently Delete App"
                className="opacity-0 group-hover:opacity-100 p-1 hover:text-red-400 transition-opacity"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>

        {hasChildren && isExpanded && (
          <div className="border-l border-slate-800 ml-3">
            {node.children!.map((child) => renderTreeItem(child, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="w-full h-full bg-[#030712] text-slate-100 flex flex-col font-sans overflow-hidden">
      {/* 1. Header Toolbar */}
      <div className="p-4 border-b border-slate-800/80 bg-slate-900/50 backdrop-blur-md flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-fuchsia-500/20 border border-fuchsia-400/40 flex items-center justify-center text-fuchsia-400 shadow-lg shadow-fuchsia-500/10">
            <Cpu className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-base font-bold text-white tracking-tight">Apps & Unified Graph</h2>
              <span className="text-[10px] uppercase font-semibold px-1.5 py-0.5 rounded bg-fuchsia-500/10 text-fuchsia-400 border border-fuchsia-500/30">
                GraphRAG Verified
              </span>
            </div>
            <p className="text-xs text-slate-400">Desktop Hierarchy • Cross-Links • Navigation Paths • Communities</p>
          </div>
        </div>

        {/* Tab Switcher */}
        <div className="flex items-center gap-1.5 bg-slate-950 p-1 rounded-xl border border-slate-800">
          <button
            onClick={() => setActiveTab("tree")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              activeTab === "tree" ? "bg-fuchsia-500 text-slate-950 shadow-md" : "text-slate-400 hover:text-white"
            }`}
          >
            <FolderTree className="w-3.5 h-3.5" />
            Hierarchy Tree
          </button>
          <button
            onClick={() => setActiveTab("neighbors")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              activeTab === "neighbors" ? "bg-fuchsia-500 text-slate-950 shadow-md" : "text-slate-400 hover:text-white"
            }`}
          >
            <Network className="w-3.5 h-3.5" />
            Cross-Links
          </button>
          <button
            onClick={() => setActiveTab("path")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              activeTab === "path" ? "bg-fuchsia-500 text-slate-950 shadow-md" : "text-slate-400 hover:text-white"
            }`}
          >
            <Route className="w-3.5 h-3.5" />
            Path Traversal
          </button>
          <button
            onClick={() => setActiveTab("communities")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              activeTab === "communities" ? "bg-fuchsia-500 text-slate-950 shadow-md" : "text-slate-400 hover:text-white"
            }`}
          >
            <Users className="w-3.5 h-3.5" />
            Communities
          </button>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              fetchTree();
              fetchCommunities();
              if (selectedNodeId) fetchNeighbors(selectedNodeId);
            }}
            disabled={isLoading}
            className="p-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
            title="Refresh Graph"
          >
            <RefreshCw className={`w-4 h-4 ${isLoading ? "animate-spin text-fuchsia-400" : ""}`} />
          </button>
        </div>
      </div>

      {deleteStatus && (
        <div className="bg-emerald-950/80 border-b border-emerald-500/40 text-emerald-300 text-xs px-4 py-1.5 text-center font-medium animate-fadeIn">
          {deleteStatus}
        </div>
      )}

      {/* 2. Main Content Split View */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Side: Tree or Active Tab List */}
        <div className="w-1/2 md:w-5/12 border-r border-slate-800/80 flex flex-col bg-slate-950/50">
          <div className="p-3 border-b border-slate-800 flex items-center gap-2">
            <Search className="w-4 h-4 text-slate-500" />
            <input
              type="text"
              placeholder="Search apps, windows, or documents..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="bg-transparent border-none outline-none text-xs text-white placeholder-slate-500 w-full"
            />
            {searchQuery && (
              <button onClick={() => setSearchQuery("")} className="text-xs text-slate-500 hover:text-white">
                Clear
              </button>
            )}
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-1">
            {activeTab === "tree" && (
              treeData ? renderTreeItem(treeData) : (
                <div className="text-xs text-slate-500 text-center py-8">Loading graph tree...</div>
              )
            )}

            {activeTab === "path" && (
              <div className="p-2 space-y-4">
                <div className="space-y-2">
                  <label className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">From Node</label>
                  <input
                    type="text"
                    value={pathFrom}
                    onChange={(e) => setPathFrom(e.target.value)}
                    placeholder="e.g. code.exe or Winword"
                    className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-xs text-white outline-none focus:border-fuchsia-500"
                  />
                </div>

                <div className="space-y-2">
                  <label className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">To Destination</label>
                  <input
                    type="text"
                    value={pathTo}
                    onChange={(e) => setPathTo(e.target.value)}
                    placeholder="e.g. msedge.exe or github.com"
                    className="w-full bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-xs text-white outline-none focus:border-fuchsia-500"
                  />
                </div>

                <button
                  onClick={handleFindPath}
                  disabled={isSearchingPath}
                  className="w-full py-2 px-3 rounded-xl bg-fuchsia-500 hover:bg-fuchsia-400 text-slate-950 text-xs font-bold transition-all shadow-md flex items-center justify-center gap-2"
                >
                  <Route className="w-3.5 h-3.5" />
                  {isSearchingPath ? "Traversing Graph..." : "Calculate Shortest Path"}
                </button>
              </div>
            )}

            {activeTab === "communities" && (
              <div className="space-y-2.5">
                {communities.length === 0 ? (
                  <div className="text-xs text-slate-500 text-center py-8">No multi-modal communities detected yet.</div>
                ) : (
                  communities.map((c) => (
                    <div
                      key={c.community_id}
                      className="p-3 bg-slate-900/60 border border-slate-800 rounded-xl space-y-2"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-xs text-fuchsia-300">Community #{c.community_id}</span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">
                          {c.node_count} nodes
                        </span>
                      </div>
                      <div className="text-xs font-medium text-white">{c.label}</div>
                      <div className="flex flex-wrap gap-1 text-[10px] text-slate-400">
                        {c.apps.map((a) => (
                          <span key={a} className="px-1.5 py-0.5 rounded bg-fuchsia-950/60 text-fuchsia-300 border border-fuchsia-800/40">
                            {a}
                          </span>
                        ))}
                        {c.websites.map((w) => (
                          <span key={w} className="px-1.5 py-0.5 rounded bg-cyan-950/60 text-cyan-300 border border-cyan-800/40">
                            {w}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}

            {activeTab === "neighbors" && (
              <div className="space-y-2">
                <div className="text-[11px] text-slate-400 px-1">Selected Center Node:</div>
                <div className="p-2.5 bg-slate-900 border border-fuchsia-500/30 rounded-xl text-xs font-bold text-white flex items-center justify-between">
                  <span>{selectedNodeId}</span>
                  <span className="text-[10px] text-fuchsia-400 font-mono">Radius: 2 hops</span>
                </div>

                <div className="text-[11px] text-slate-400 px-1 mt-3">Connected Nodes ({neighborData?.nodes.length || 0}):</div>
                <div className="space-y-1">
                  {neighborData?.nodes.map((n) => (
                    <div
                      key={n.id}
                      onClick={() => setSelectedNodeId(n.id)}
                      className={`p-2 rounded-lg text-xs cursor-pointer flex items-center justify-between ${
                        selectedNodeId === n.id ? "bg-fuchsia-950/60 border border-fuchsia-500/40 text-white" : "hover:bg-slate-900 text-slate-300"
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        {getNodeIcon(n.node_type)}
                        <span className="font-medium truncate max-w-[180px]">{n.label}</span>
                      </div>
                      <span className="text-[10px] font-mono text-slate-500">{n.node_type}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Right Side: Detail Panel, Path Visualization, or Cross-link Inspector */}
        <div className="flex-1 bg-slate-900/30 overflow-y-auto p-5 space-y-5">
          {activeTab === "path" && pathResult && (
            <div className="bg-slate-950 border border-slate-800 rounded-2xl p-5 space-y-4 shadow-xl">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-fuchsia-400 uppercase tracking-wider flex items-center gap-2">
                  <Route className="w-4 h-4" />
                  GraphRAG Path Traversal
                </span>
                {pathResult.found && (
                  <span className="text-[10px] font-semibold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                    Path Verified ({pathResult.path.length} steps)
                  </span>
                )}
              </div>

              {pathResult.found ? (
                <div className="space-y-3">
                  <div className="p-3 bg-slate-900/80 rounded-xl border border-slate-800 text-xs font-mono text-cyan-300">
                    {pathResult.formatted}
                  </div>

                  <div className="space-y-2">
                    <div className="text-xs font-semibold text-slate-300">Navigation Steps:</div>
                    <div className="relative pl-6 space-y-3 before:absolute before:left-2.5 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-800">
                      {pathResult.path.map((nodeId: string, idx: number) => (
                        <div key={idx} className="relative flex items-center justify-between text-xs">
                          <span className="absolute -left-6 w-3 h-3 rounded-full bg-fuchsia-500 border-2 border-slate-950"></span>
                          <span className="font-semibold text-white">{nodeId}</span>
                          {idx < pathResult.edges.length && (
                            <span className="text-[10px] font-mono text-slate-400 px-2 py-0.5 rounded bg-slate-900">
                              {pathResult.edges[idx].edge_type}
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ) : (
                <div className="text-xs text-red-400 bg-red-950/40 p-3 rounded-xl border border-red-800/40">
                  {pathResult.message || "No connecting path found."}
                </div>
              )}
            </div>
          )}

          {/* Node Inspector Card */}
          <div className="bg-slate-950 border border-slate-800 rounded-2xl p-5 space-y-4 shadow-xl">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">Node Details</span>
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-300">
                  {selectedNodeId}
                </span>
              </div>

              {onSelectNodeIn3D && (
                <button
                  onClick={() => onSelectNodeIn3D(selectedNodeId)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-400 border border-cyan-500/30 text-xs font-semibold transition-all"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                  Locate in 3D
                </button>
              )}
            </div>

            {neighborData?.nodes.find((n) => n.id === selectedNodeId) ? (
              (() => {
                const node = neighborData.nodes.find((n) => n.id === selectedNodeId)!;
                const outgoing = neighborData.edges.filter((e) => e.source === selectedNodeId);
                const incoming = neighborData.edges.filter((e) => e.target === selectedNodeId);

                return (
                  <div className="space-y-4">
                    <div className="p-4 bg-slate-900/60 rounded-xl border border-slate-800 space-y-2">
                      <div className="flex items-center gap-2">
                        {getNodeIcon(node.node_type)}
                        <h3 className="font-bold text-sm text-white">{node.label}</h3>
                      </div>
                      <div className="grid grid-cols-2 gap-2 text-xs pt-2 border-t border-slate-800/60">
                        <div>
                          <span className="text-slate-500">Node Type:</span>{" "}
                          <span className="font-semibold text-slate-200">{node.node_type}</span>
                        </div>
                        <div>
                          <span className="text-slate-500">Source:</span>{" "}
                          <span className="font-semibold text-slate-200">{node.source}</span>
                        </div>
                        <div>
                          <span className="text-slate-500">Weight:</span>{" "}
                          <span className="font-semibold text-slate-200">
                            {node.weight >= 60 ? `${Math.round(node.weight / 60)} mins` : `${Math.round(node.weight)} secs`}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Cross-Link Transitions */}
                    <div className="space-y-3">
                      <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wider">Outgoing Cross-Links ({outgoing.length})</h4>
                      {outgoing.length === 0 ? (
                        <div className="text-xs text-slate-500 italic">No outgoing links.</div>
                      ) : (
                        <div className="space-y-1.5">
                          {outgoing.map((e) => (
                            <div key={e.id} className="p-2.5 bg-slate-900/40 border border-slate-800 rounded-xl flex items-center justify-between text-xs">
                              <div className="flex items-center gap-2">
                                <span className="text-fuchsia-400 font-mono text-[11px] font-semibold">{e.edge_type}</span>
                                <ArrowRight className="w-3.5 h-3.5 text-slate-600" />
                                <span className="text-white font-medium">{e.target}</span>
                              </div>
                              <span className="text-[10px] text-slate-400 font-mono">w={e.weight} ({e.confidence})</span>
                            </div>
                          ))}
                        </div>
                      )}

                      <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wider pt-2">Incoming Transitions ({incoming.length})</h4>
                      {incoming.length === 0 ? (
                        <div className="text-xs text-slate-500 italic">No incoming links.</div>
                      ) : (
                        <div className="space-y-1.5">
                          {incoming.map((e) => (
                            <div key={e.id} className="p-2.5 bg-slate-900/40 border border-slate-800 rounded-xl flex items-center justify-between text-xs">
                              <div className="flex items-center gap-2">
                                <span className="text-white font-medium">{e.source}</span>
                                <ArrowRight className="w-3.5 h-3.5 text-slate-600" />
                                <span className="text-cyan-400 font-mono text-[11px] font-semibold">{e.edge_type}</span>
                              </div>
                              <span className="text-[10px] text-slate-400 font-mono">w={e.weight}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })()
            ) : (
              <div className="text-xs text-slate-500 italic text-center py-4">Select a node from the hierarchy tree to inspect its subgraph.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
