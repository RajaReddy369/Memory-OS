# Memory-OS
A memory operating system for LLM agents. Memory OS gives an AI agent long-term conversational memory by managing it the way an operating system manages data: small and fast at the top, large and persistent at the bottom, with automatic movement between the two.

Large language models forget. Context windows are finite, and stuffing the whole history into every prompt is slow, expensive and noisy. Memory OS keeps what matters, summarizes what is fading, and forgets the rest.

Why Memory OS?
Problem	How Memory OS helps
The context window is limited	Only the most relevant memories are loaded for each turn
Agents forget users between sessions	A persistent user profile survives across sessions
Plain RAG treats everything as flat chunks	Memory is tiered and promoted or demoted by usage
Old, unused details clutter retrieval	Low-activity memory fades instead of piling up
Core idea

Memory OS borrows its structure from operating systems. It has three storage tiers and four modules.

Three memory tiers
Tier	Contents	OS analogy
Short-term memory	The most recent conversation turns	CPU cache
Mid-term memory	Topic-grouped, summarized conversation segments	RAM
Long-term personal memory	User profile, preferences, persistent knowledge	Disk
Four modules
Storage organizes information into the three tiers.
Updating moves memory between tiers.
Short-term to mid-term follows a first-in-first-out rule over dialogue chains.
Mid-term to long-term uses segment "heat" (how often and how recently a segment is used) to decide what gets promoted into the user profile.
Retrieval pulls semantically relevant context from all three tiers for the current query.
Generation combines the retrieved memory with the current question to produce a coherent, personalized response.
