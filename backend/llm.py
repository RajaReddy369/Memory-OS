"""
MemoryOS Pluggable LLM Interface.
Connects to local Ollama (Llama 3.2 / Llama 3.1 / Qwen) for generation and streaming,
with a fallback response generator when Ollama is offline.
"""

import json
import logging
import os
from typing import AsyncGenerator, Dict, List, Optional
import httpx

from backend.config import OLLAMA_CHAT_MODEL, OLLAMA_HOST

logger = logging.getLogger("memoryos.llm")

DEFAULT_CHAT_MODEL = OLLAMA_CHAT_MODEL

SYSTEM_PROMPT = """You are MemoryOS, a personal second brain that remembers digital activity.
You are answering questions based EXCLUSIVELY on the user's recorded memory passages provided in the context.

RULES:
1. Answer accurately using ONLY the provided memory passages.
2. If the context does not contain the answer, respond with:
   "I couldn't find that in your memory." Do not speculate, invent, or extrapolate.
3. Every claim you make should reference the source title, domain, or timestamp where it was seen.
4. Be concise, direct, and helpful.
"""


class LocalOllamaClient:
    """Client for local Ollama chat and text generation."""

    def __init__(self, model: str = DEFAULT_CHAT_MODEL, host: str = OLLAMA_HOST):
        self.model = model
        self.host = host.rstrip("/")

    async def generate(self, prompt: str, context: List[Dict[str, str]]) -> str:
        """Non-streaming generation."""
        formatted_prompt = self._build_prompt(prompt, context)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(
                    f"{self.host}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": formatted_prompt,
                        "system": SYSTEM_PROMPT,
                        "stream": False
                    }
                )
                if res.status_code == 200:
                    return res.json().get("response", "").strip()
        except Exception as e:
            logger.debug(f"Ollama generation offline ({e}); using grounded context summary.")

        return self._generate_fallback(prompt, context)

    async def stream_generate(self, prompt: str, context: List[Dict[str, str]]) -> AsyncGenerator[str, None]:
        """Streaming generation returning token chunks."""
        formatted_prompt = self._build_prompt(prompt, context)
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.host}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": formatted_prompt,
                        "system": SYSTEM_PROMPT,
                        "stream": True
                    }
                ) as response:
                    if response.status_code == 200:
                        async for line in response.aiter_lines():
                            if line:
                                try:
                                    data = json.loads(line)
                                    chunk = data.get("response", "")
                                    if chunk:
                                        yield chunk
                                    if data.get("done"):
                                        break
                                except json.JSONDecodeError:
                                    pass
                        return
        except Exception:
            pass

        # Fallback stream if Ollama offline
        fallback_text = self._generate_fallback(prompt, context)
        for word in fallback_text.split(" "):
            yield word + " "

    def _build_prompt(self, user_query: str, context_passages: List[Dict[str, str]]) -> str:
        if not context_passages:
            return f"User Question: {user_query}\n\nContext: [No relevant memories recorded.]"

        context_blocks = []
        for idx, p in enumerate(context_passages, 1):
            title = p.get("title") or "Untitled"
            url = p.get("url") or ""
            time_str = p.get("time_str") or ""
            snippet = p.get("snippet") or p.get("text") or ""
            context_blocks.append(
                f"[Source {idx}] Title: {title}\nURL: {url}\nDate/Time: {time_str}\nContent: {snippet}"
            )

        full_context = "\n\n".join(context_blocks)
        return f"Context from MemoryOS:\n{full_context}\n\nUser Question: {user_query}\n\nAnswer:"

    def _generate_fallback(self, query: str, context: List[Dict[str, str]]) -> str:
        """Grounded fallback when Ollama service is not running."""
        if not context:
            return "I couldn't find that in your memory."

        top = context[0]
        title = top.get("title") or "a page"
        url = top.get("url") or ""
        time_str = top.get("time_str") or "recently"
        snippet = top.get("snippet") or top.get("text") or ""

        return (
            f"According to your memory from {time_str}, you visited \"{title}\" ({url}):\n\n"
            f"> {snippet}\n"
        )


_llm_client_instance = None


def get_llm_client() -> LocalOllamaClient:
    global _llm_client_instance
    if _llm_client_instance is None:
        _llm_client_instance = LocalOllamaClient()
    return _llm_client_instance

