"""
MemoryOS Session Segmentation & LLM Project Labeler.
Groups raw browser and desktop events into cohesive sessions using time gaps,
app/domain context transitions, and generates semantic titles and project labels using Llama 3.2.
"""

from collections import Counter
from datetime import datetime
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import httpx

from backend.config import OLLAMA_HOST, SESSION_GAP_SECONDS, SESSION_LABEL_MODEL
from backend.database import (
    get_raw_events_for_period,
    save_session_record,
)

logger = logging.getLogger("memoryos.sessions")


def segment_events(
    events: List[Dict[str, Any]],
    gap_seconds: float = SESSION_GAP_SECONDS
) -> List[List[Dict[str, Any]]]:
    """
    Cluster chronological events into sessions.
    Boundaries are created when:
    1. Inactivity gap between consecutive events exceeds gap_seconds (default 10 min).
    2. Sharp context switch (e.g. switching between completely unrelated IDE workspace and casual browsing after a notable pause).
    """
    if not events:
        return []

    # Sort strictly by timestamp
    sorted_events = sorted(events, key=lambda x: float(x.get("timestamp") or 0.0))
    sessions: List[List[Dict[str, Any]]] = []
    current_session: List[Dict[str, Any]] = [sorted_events[0]]

    for i in range(1, len(sorted_events)):
        prev = sorted_events[i - 1]
        curr = sorted_events[i]

        prev_time = float(prev.get("timestamp") or 0.0)
        prev_dur = float(prev.get("duration") or 0.0)
        curr_time = float(curr.get("timestamp") or 0.0)

        # Inactivity gap: time between end of previous activity and start of current
        gap = curr_time - (prev_time + prev_dur)

        # Context switch check:
        prev_app = (prev.get("app_name") or prev.get("domain") or "").lower()
        curr_app = (curr.get("app_name") or curr.get("domain") or "").lower()
        is_context_switch = (gap > 180.0) and (prev_app != curr_app) and (
            ("code" in prev_app and "code" not in curr_app) or
            ("word" in prev_app and "word" not in curr_app)
        )

        if gap > gap_seconds or is_context_switch:
            sessions.append(current_session)
            current_session = [curr]
        else:
            current_session.append(curr)

    if current_session:
        sessions.append(current_session)

    return sessions


async def label_session(session_events: List[Dict[str, Any]]) -> Tuple[str, str, str]:
    """
    Generate title, 1-2 sentence summary, and project/topic label using Llama 3.2.
    Falls back gracefully to rule-based synthesis with warning if Ollama is unreachable.
    """
    if not session_events:
        return "Empty Session", "No activity recorded.", "General"

    # 1. Synthesize activity overview
    app_counts = Counter()
    domain_counts = Counter()
    titles = []

    for ev in session_events:
        app = ev.get("app_name")
        domain = ev.get("domain")
        title = ev.get("title")
        if app:
            app_counts[app] += 1
        if domain:
            domain_counts[domain] += 1
        if title and title not in titles:
            titles.append(title)

    primary_app = app_counts.most_common(1)[0][0] if app_counts else "Desktop"
    primary_domain = domain_counts.most_common(1)[0][0] if domain_counts else ""
    key_titles = titles[:5]

    prompt = (
        f"You are a cognitive activity analyzer. Summarize this user work session into JSON.\n"
        f"Primary Application: {primary_app}\n"
        f"Primary Domain: {primary_domain}\n"
        f"Active Titles/Files: {', '.join(key_titles)}\n"
        f"Total Actions: {len(session_events)}\n\n"
        f"Return ONLY valid JSON matching this schema:\n"
        f"{{\"title\": \"short 4-7 word title\", \"summary\": \"1-2 sentence descriptive summary\", \"project_label\": \"single project or category name\"}}"
    )

    # 2. Try Ollama Llama 3.2 (skip if running in test mode)
    if os.environ.get("MEMORYOS_USE_SQLITE_VECTORS") != "1":
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.post(
                    f"{OLLAMA_HOST}/api/generate",
                    json={
                        "model": SESSION_LABEL_MODEL,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json"
                    }
                )
                if res.status_code == 200:
                    raw_text = res.json().get("response", "").strip()
                    parsed = json.loads(raw_text)
                    title = parsed.get("title")
                    summary = parsed.get("summary")
                    project = parsed.get("project_label")
                    if title and summary and project:
                        return title.strip(), summary.strip(), project.strip().title()
        except Exception as e:
            logger.warning(
                f"[MemoryOS Warning] Ollama session labeling unavailable ({e}); using rule-based synthesis."
            )

    # 3. Rule-based Fallback Synthesis
    if "code" in primary_app.lower() or "cursor" in primary_app.lower() or "studio" in primary_app.lower():
        title = f"Coding in {primary_app}"
        summary = f"Worked on development and code files including {', '.join(key_titles[:2])}."
        project = "Software Development"
    elif primary_domain:
        title = f"Research on {primary_domain}"
        summary = f"Browsed articles and pages on {primary_domain} including {key_titles[0] if key_titles else 'web pages'}."
        project = primary_domain.split(".")[0].title()
    else:
        title = f"Work in {primary_app}"
        summary = f"Completed digital tasks and documents in {primary_app}."
        project = primary_app.title()

    return title, summary, project


async def recompute_sessions(
    start_time: Optional[float] = None,
    end_time: Optional[float] = None
) -> List[Dict[str, Any]]:
    """
    Fully re-computable session segmentation pipeline.
    Re-evaluates raw events in the given time window, clusters them into sessions,
    labels each session, and persists results into database.
    """
    raw_events = get_raw_events_for_period(start_time, end_time)
    if not raw_events:
        return []

    event_clusters = segment_events(raw_events, gap_seconds=SESSION_GAP_SECONDS)
    created_sessions: List[Dict[str, Any]] = []

    for cluster in event_clusters:
        first_ev = cluster[0]
        last_ev = cluster[-1]

        t_start = float(first_ev.get("timestamp") or 0.0)
        t_end = float(last_ev.get("timestamp") or 0.0) + float(last_ev.get("duration") or 0.0)
        duration = max(1.0, t_end - t_start)

        sid = f"sess_{int(t_start)}_{len(cluster)}"
        title, summary, project_label = await label_session(cluster)

        # Primary app & domain
        apps = [ev.get("app_name") for ev in cluster if ev.get("app_name")]
        domains = [ev.get("domain") for ev in cluster if ev.get("domain")]
        primary_app = Counter(apps).most_common(1)[0][0] if apps else "browser"
        primary_domain = Counter(domains).most_common(1)[0][0] if domains else ""

        session_record = {
            "id": sid,
            "title": title,
            "summary": summary,
            "project_label": project_label,
            "start_time": t_start,
            "end_time": t_end,
            "duration": round(duration, 1),
            "event_count": len(cluster),
            "primary_app": primary_app,
            "primary_domain": primary_domain,
            "created_at": time.time()
        }

        save_session_record(session_record, cluster)
        created_sessions.append(session_record)

    logger.info(f"Segmented {len(raw_events)} events into {len(created_sessions)} sessions.")
    return created_sessions
