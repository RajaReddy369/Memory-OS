import React, { useState } from "react";
import {
  MessageSquare,
  Send,
  Sparkles,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Clock,
  Compass,
} from "lucide-react";
import { CitationReference } from "../../types";

interface MessageItem {
  id: string;
  sender: "user" | "ai";
  text: string;
  citations?: CitationReference[];
}

interface DockedChatPanelProps {
  onHighlight3DNode: (nodeId: string, position?: [number, number, number]) => void;
}

export const DockedChatPanel: React.FC<DockedChatPanelProps> = ({
  onHighlight3DNode,
}) => {
  const [isOpen, setIsOpen] = useState(true);
  const [inputMessage, setInputMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [messages, setMessages] = useState<MessageItem[]>([
    {
      id: "welcome",
      sender: "ai",
      text: "Hello! I am MemoryOS. Ask me anything about what you read, coded, or researched across your digital memory.",
      citations: [],
    },
  ]);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputMessage.trim() || isLoading) return;

    const userQuery = inputMessage.trim();
    setInputMessage("");
    const userMsgId = `usr_${Date.now()}`;

    setMessages((prev) => [
      ...prev,
      { id: userMsgId, sender: "user", text: userQuery },
    ]);
    setIsLoading(true);

    try {
      // Query local backend API
      const res = await fetch("http://127.0.0.1:8000/api/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-MemoryOS-Key": localStorage.getItem("memoryos_token") || "",
        },
        body: JSON.stringify({ message: userQuery, stream: false }),
      });

      if (res.ok) {
        const data = await res.json();
        const aiMsg: MessageItem = {
          id: `ai_${Date.now()}`,
          sender: "ai",
          text: data.answer,
          citations: data.citations || [],
        };
        setMessages((prev) => [...prev, aiMsg]);

        // Automatically light up the first cited node in 3D
        if (data.citations && data.citations.length > 0) {
          const firstCit = data.citations[0];
          onHighlight3DNode(`event_${firstCit.event_id}`);
        }
      } else {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Server returned HTTP ${res.status}`);
      }
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        {
          id: `ai_${Date.now()}`,
          sender: "ai",
          text: `⚠️ MemoryOS backend unreachable (${err?.message || "connection failed"}). Ensure the FastAPI server is running at http://127.0.0.1:8000.`,
          citations: [],
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div
      className={`absolute top-16 left-5 bottom-20 z-20 transition-all duration-300 flex ${
        isOpen ? "w-80" : "w-10"
      }`}
    >
      {/* Toggle Tab */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="absolute -right-3.5 top-1/2 -translate-y-1/2 w-7 h-12 bg-slate-900 border border-slate-800 rounded-r-xl flex items-center justify-center text-slate-400 hover:text-white shadow-xl z-30"
      >
        {isOpen ? <ChevronLeft className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
      </button>

      {/* Main Drawer Body */}
      {isOpen && (
        <div className="w-full h-full bg-slate-900/90 backdrop-blur-xl border border-slate-800 rounded-2xl shadow-2xl flex flex-col overflow-hidden">
          {/* Header */}
          <div className="p-3.5 border-b border-slate-800 flex items-center gap-2">
            <MessageSquare className="w-4 h-4 text-cyan-400" />
            <h3 className="text-xs font-bold text-white uppercase tracking-wider">
              MemoryOS Copilot
            </h3>
          </div>

          {/* Messages Feed */}
          <div className="flex-1 overflow-y-auto p-3.5 space-y-3 text-xs">
            {messages.map((m) => (
              <div
                key={m.id}
                className={`p-3 rounded-xl space-y-2 leading-relaxed ${
                  m.sender === "user"
                    ? "bg-cyan-500/10 border border-cyan-500/30 text-cyan-100 ml-4"
                    : "bg-slate-950/70 border border-slate-800/80 text-slate-300 mr-2"
                }`}
              >
                <p>{m.text}</p>

                {/* Structured Clickable Citations */}
                {m.citations && m.citations.length > 0 && (
                  <div className="space-y-1.5 pt-1 border-t border-slate-800/60">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-cyan-400 flex items-center gap-1">
                      <Sparkles className="w-3 h-3" /> Citations (Click to fly in 3D):
                    </span>
                    {m.citations.map((c, idx) => (
                      <button
                        key={idx}
                        onClick={() => onHighlight3DNode(`sess_${Number(c.event_id) % 70}`)}
                        className="w-full text-left p-2 rounded-lg bg-slate-900 hover:bg-slate-800/80 border border-slate-800 hover:border-cyan-500/50 transition-all group"
                      >
                        <div className="flex items-center justify-between gap-1 mb-0.5">
                          <span className="font-semibold text-white truncate text-[11px] group-hover:text-cyan-300">
                            {c.title}
                          </span>
                          <ExternalLink className="w-3 h-3 text-slate-500 group-hover:text-cyan-400 shrink-0" />
                        </div>
                        <div className="flex items-center gap-1.5 text-[10px] text-slate-400">
                          <Clock className="w-2.5 h-2.5" />
                          <span>{c.time_str}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {isLoading && (
              <div className="p-3 bg-slate-950/70 border border-slate-800 rounded-xl text-slate-400 text-xs animate-pulse flex items-center gap-2">
                <Sparkles className="w-3.5 h-3.5 text-cyan-400 animate-spin" />
                Thinking & retrieving memories...
              </div>
            )}
          </div>

          {/* Input Form */}
          <form onSubmit={handleSendMessage} className="p-3 border-t border-slate-800 bg-slate-950/60">
            <div className="relative flex items-center">
              <input
                type="text"
                placeholder="Ask your memory..."
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                className="w-full pl-3 pr-8 py-2 bg-slate-900 border border-slate-800 rounded-xl text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500"
              />
              <button
                type="submit"
                disabled={isLoading}
                className="absolute right-1.5 p-1 rounded-lg text-cyan-400 hover:text-cyan-300 transition-all disabled:opacity-40"
              >
                <Send className="w-3.5 h-3.5" />
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};

