---
name: nowledge-mem
description: Use a connected Nowledge Mem workspace for cross-tool context, memory search, scoped knowledge writes, thread lookup, and Library retrieval in ChatGPT or Codex.
---

# Nowledge Mem

Use the connected Nowledge Mem tools when the answer depends on prior decisions, current working context, exact earlier conversations, or durable knowledge that should survive this chat.

## Connect

Use the existing Nowledge Mem App connection. It can point to a self-hosted server or a hosted workspace. If its tools are unavailable, check that connection in the host settings. Follow its actual authentication flow; never ask the user to paste an API key into chat.

This personal package uses the App reference supplied at build time. The public template has no active binding. The skill alone does not authorize or expose a workspace. Do not create another App when an existing registered connection is available.

## Use

1. Start with `read_context_bundle` when broad current context is useful.
2. Use `memory_search` for focused recall and `get_memory_by_id` for exact follow-up.
3. Use `thread_search` and thread message tools only when exact prior conversation evidence matters.
4. Use Library tools for source-backed material.
5. Before `memory_add` or `memory_update`, make the intended Space and durable claim clear. Use the permissions and scopes of the actual connection. Request any required write permission through the host.

Respect the tools actually exposed by the connected server. Do not claim access to hidden administrative, identity, scheduler, deletion, or review/governance tools.

## Boundaries

- Remote MCP lets ChatGPT or Codex call Mem. It does not let Mem read the host's private transcript.
- Use the browser extension or an official export for ChatGPT conversation capture. Use the dedicated local Codex connector for Codex lifecycle hooks and transcript capture.
- A client name and `source_app` are provenance, not an AI Identity or Space selector.
- Never create a new Space merely to make a connection succeed.

When a task materially depends on remembered context, cite or summarize the retrieved evidence honestly. Do not describe a retrieval as proof that the memory helped unless the user or downstream work confirms it.
