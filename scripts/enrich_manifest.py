#!/usr/bin/env python3
"""
The Danual — Enricher (Phase 3)
Adds LLM-written section intros and plain-English explainers to manifest items.

On first run: enriches all items.
On subsequent runs: only enriches items with empty explainers (new items).
"""

import json
import re
import logging
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR.parent / "output"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"

logging.basicConfig(level=logging.INFO, format="  %(message)s")
log = logging.getLogger("danual-enricher")


SECTION_INTROS = {
    "tools": (
        "Tools are capabilities Hermes uses on your behalf — search the web, read files, "
        "run terminal commands, browse websites, generate images, and more. Hermes picks "
        "the right tool automatically based on what you ask. You don't need to memorize "
        "these names, but knowing what's available helps you know what to ask for."
    ),
    "commands": (
        "Commands are slash shortcuts you type directly: /model to switch models, /skills "
        "to browse skills, /cron to manage scheduled tasks. Some work only in the CLI, "
        "others only on messaging platforms, and many work everywhere. They give you "
        "instant control without writing full prompts."
    ),
    "cli_subcommands": (
        "CLI commands are what you type in your terminal to operate Hermes: 'hermes dashboard' "
        "to open the web dashboard, 'hermes backup' to manage backups, 'hermes mcp' to manage "
        "MCP servers, and more. These are different from slash commands (which you type inside "
        "a conversation). CLI commands control Hermes itself — starting, configuring, "
        "diagnosing, and managing the system."
    ),
    "skills": (
        "Skills are reusable knowledge packages that teach Hermes how to handle specific "
        "workflows. Bundled skills ship with Hermes — code review, GitHub workflows, "
        "research templates. Your custom skills are ones you've created or installed, "
        "tailored to your needs. Skills are what make each Hermes instance unique."
    ),
    "integrations": (
        "Integrations let you talk to Hermes from different platforms — Telegram, Discord, "
        "WhatsApp, iMessage, email, and more. Each integration turns that platform into a "
        "full Hermes interface: send messages, share images, run commands, get notifications. "
        "You can run multiple platforms simultaneously, each with its own tool configuration."
    ),
    "config_options": (
        "These settings control how Hermes behaves. They live in ~/.hermes/config.yaml — "
        "edit the file directly, or use 'hermes config set key value' from the CLI. "
        "Most have sensible defaults, so you only need to change what matters to you. "
        "Click any option to see what it does and why you might change it."
    ),
    "environment_variables": (
        "Environment variables are API keys and credentials stored in ~/.hermes/.env. "
        "They connect Hermes to external services — AI providers, search APIs, messaging "
        "platforms. You only need the ones for services you actually use. Set them with "
        "'hermes config set VAR value' or edit the .env file directly."
    ),
    "mcp_servers": (
        "MCP (Model Context Protocol) servers are plugins that give Hermes access to "
        "external data and tools — databases, knowledge bases, custom APIs. Each runs as "
        "a separate process. Add them with 'hermes mcp add', remove with 'hermes mcp remove'. "
        "Click to see what each server provides."
    ),
    "cron_jobs": (
        "Cron jobs are tasks Hermes runs on a schedule — daily briefings, backups, "
        "monitoring checks. They execute automatically and can deliver results to any "
        "connected platform (Telegram, Discord, etc). Manage with /cron in the CLI."
    ),
    "terminal_backends": (
        "Terminal backends control where Hermes runs commands. 'Local' runs directly on "
        "your machine. Others run in Docker containers, remote servers (SSH), or cloud "
        "environments — useful for isolation, GPU access, or running code you don't fully "
        "trust. Change the backend in config.yaml under terminal.backend."
    ),
}

# ─── Platform Integration Descriptions ────────────────────────────────────────

PLATFORM_EXPLAINERS = {
    "cli": {
        "what_it_does": "The terminal interface — run Hermes directly in your shell with full tool access, file editing, and interactive prompts.",
        "why_it_matters": "The most powerful way to use Hermes. Full access to all tools, real-time streaming, voice mode, and the richest UI. This is where you do serious work.",
        "example_use_case": "Open a terminal, type 'hermes', and start a conversation. Use slash commands, paste images, run background tasks.",
    },
    "telegram": {
        "what_it_does": "Chat with Hermes via Telegram — send messages, images, voice notes, and receive formatted responses with code blocks.",
        "why_it_matters": "Access Hermes from your phone or any device with Telegram. Get notifications, run commands remotely, and interact hands-free. Great for on-the-go access.",
        "example_use_case": "Message your Hermes bot on Telegram to check server status, get a morning briefing, or ask questions while away from your desk.",
    },
    "discord": {
        "what_it_does": "Hermes as a Discord bot — responds in channels, supports threads, reactions, and Discord-native formatting.",
        "why_it_matters": "Bring AI assistance to your Discord server. Team members can interact with Hermes in shared channels. Supports mention-based activation and auto-threading.",
        "example_use_case": "Add Hermes to your project's Discord server so team members can ask it questions, get code reviews, or automate tasks.",
    },
    "slack": {
        "what_it_does": "Hermes as a Slack app — responds in channels and DMs with Slack-native formatting and thread support.",
        "why_it_matters": "Integrate AI into your team's Slack workspace. Hermes can answer questions, run commands, and assist with workflows without leaving Slack.",
        "example_use_case": "Install Hermes in your Slack workspace and mention it in any channel to get help with coding, research, or task automation.",
    },
    "whatsapp": {
        "what_it_does": "Chat with Hermes on WhatsApp — send text, images, and voice messages through the WhatsApp Business API.",
        "why_it_matters": "Use Hermes from WhatsApp groups or individual chats. Useful when Telegram isn't available or for reaching people who prefer WhatsApp.",
        "example_use_case": "Add Hermes to a WhatsApp group to provide automated responses, run polls, or handle group management tasks.",
    },
    "signal": {
        "what_it_does": "Chat with Hermes via Signal — end-to-end encrypted messaging with full text and image support.",
        "why_it_matters": "The most private way to interact with Hermes remotely. All messages are E2E encrypted by Signal's protocol.",
        "example_use_case": "Use Signal to send sensitive queries to Hermes when privacy matters — like discussing credentials or internal infrastructure.",
    },
    "bluebubbles": {
        "what_it_does": "Chat with Hermes via iMessage — uses BlueBubbles as a bridge to Apple's messaging ecosystem.",
        "why_it_matters": "Access Hermes from iMessage on your iPhone, iPad, or Mac. Native Apple ecosystem integration without installing extra apps.",
        "example_use_case": "Text your Hermes number from iMessage to check on tasks, get quick answers, or run remote commands from your Apple devices.",
    },
    "email": {
        "what_it_does": "Hermes reads incoming emails and can compose and send replies — works with any email provider.",
        "why_it_matters": "Automate email workflows: draft responses, summarize long threads, extract action items, or auto-reply to specific patterns.",
        "example_use_case": "Forward a long email thread to Hermes and ask for a summary, or set up auto-responses for common inquiries.",
    },
    "homeassistant": {
        "what_it_does": "Control smart home devices through Home Assistant — lights, locks, thermostats, sensors, and more.",
        "why_it_matters": "Talk to your smart home in natural language. Instead of navigating Home Assistant's UI, just tell Hermes what you want.",
        "example_use_case": "Say 'turn off all the lights downstairs' or 'what's the temperature in the bedroom?' and Hermes handles it via Home Assistant.",
    },
    "mattermost": {
        "what_it_does": "Hermes as a Mattermost bot — self-hosted team chat integration with channel and DM support.",
        "why_it_matters": "For teams using Mattermost (the open-source Slack alternative), Hermes integrates natively without external dependencies.",
        "example_use_case": "Deploy Hermes in your self-hosted Mattermost for AI assistance that stays within your infrastructure.",
    },
    "matrix": {
        "what_it_does": "Hermes on Matrix — decentralized, federated messaging with E2E encryption support.",
        "why_it_matters": "For users on the Matrix/Element ecosystem. Decentralized and self-hostable — your messages don't pass through third-party servers.",
        "example_use_case": "Add Hermes to your Matrix room for AI assistance in a decentralized, privacy-respecting environment.",
    },
    "dingtalk": {
        "what_it_does": "Hermes as a DingTalk bot — enterprise messaging for Chinese and international teams.",
        "why_it_matters": "DingTalk is widely used in Chinese enterprises. This integration brings Hermes to teams that use DingTalk as their primary communication tool.",
        "example_use_case": "Add Hermes to your DingTalk group for AI-powered assistance in your team's daily workflow.",
    },
    "feishu": {
        "what_it_does": "Hermes on Feishu (Lark) — ByteDance's enterprise platform with rich card and document support.",
        "why_it_matters": "For teams using Feishu/Lark as their workspace. Deep integration with Feishu's rich messaging format and document ecosystem.",
        "example_use_case": "Use Hermes in Feishu to draft documents, answer team questions, or automate workflows within the Feishu ecosystem.",
    },
    "wecom": {
        "what_it_does": "Hermes on WeCom (WeChat Work) — enterprise WeChat with group and application message support.",
        "why_it_matters": "WeCom is the enterprise standard in China. This brings Hermes into corporate WeChat environments with native formatting.",
        "example_use_case": "Deploy Hermes as a WeCom application bot for your company's internal AI assistant.",
    },
    "wecom_callback": {
        "what_it_does": "WeCom callback mode — self-built enterprise app integration with atomic state and media handling.",
        "why_it_matters": "For custom WeCom enterprise apps that need deeper integration than the standard bot mode. Handles callbacks, media uploads, and markdown.",
        "example_use_case": "Build a custom WeCom enterprise app that routes messages through Hermes for intelligent automated responses.",
    },
    "weixin": {
        "what_it_does": "Hermes on WeChat (Weixin) — China's dominant messaging platform via iLink Bot API.",
        "why_it_matters": "WeChat has over 1 billion users. This integration makes Hermes accessible to anyone on WeChat, covering the Chinese consumer messaging ecosystem.",
        "example_use_case": "Chat with Hermes on WeChat just like any other contact — ask questions, share images, get responses in Chinese or English.",
    },
    "qqbot": {
        "what_it_does": "Hermes on QQ — Tencent's messaging platform popular with younger Chinese users and gaming communities.",
        "why_it_matters": "QQ has hundreds of millions of users, especially in gaming and youth communities. This integration reaches that audience.",
        "example_use_case": "Add Hermes to a QQ group for AI-powered chat assistance, gaming help, or community management.",
    },
    "webhook": {
        "what_it_does": "Generic webhook endpoint — any service can trigger Hermes by POSTing to a URL.",
        "why_it_matters": "The universal integration point. Connect GitHub, GitLab, Stripe, CI/CD pipelines, IoT sensors — anything that can send a webhook.",
        "example_use_case": "Set up a GitHub webhook so Hermes automatically reviews PRs, or connect Stripe to get notified about payment events.",
    },
    "api_server": {
        "what_it_does": "REST API server — programmatic access to Hermes for custom applications and automations.",
        "why_it_matters": "Build custom apps on top of Hermes. The API server lets external code send prompts and receive responses programmatically.",
        "example_use_case": "Build a custom dashboard or mobile app that talks to Hermes through its API for AI-powered features.",
    },
}

# ─── Config Enrichment ────────────────────────────────────────────────────────

CONFIG_EXPLAINERS = {
    "model": {
        "what_it_does": "The default AI model Hermes uses for conversations.",
        "why_it_matters": "Different models have different strengths — speed, cost, reasoning ability. Change this to use a faster/cheaper model for simple tasks or a stronger one for complex work.",
        "example_use_case": "Set to 'anthropic/claude-sonnet-4' for balanced performance, or a cheaper model for casual chat.",
    },
    "agent.max_turns": {
        "what_it_does": "Maximum number of back-and-forth turns Hermes will take before stopping.",
        "why_it_matters": "Prevents runaway tasks from burning through your API credits. Higher = more complex multi-step tasks. Lower = tighter cost control.",
        "example_use_case": "Increase to 120 for complex coding projects, or reduce to 30 for simple Q&A to save costs.",
    },
    "agent.gateway_timeout": {
        "what_it_does": "How long (seconds) the gateway waits for an idle agent before timing out.",
        "why_it_matters": "Prevents hung sessions from occupying resources forever. The timeout only fires when Hermes has been completely idle (not while actively working).",
        "example_use_case": "Increase to 3600 (1 hour) if you often give Hermes long tasks, or decrease if you want faster cleanup of idle sessions.",
    },
    "terminal.backend": {
        "what_it_does": "Where Hermes runs terminal commands: local, docker, ssh, modal, etc.",
        "why_it_matters": "Running in Docker or SSH keeps your local machine safe from potentially destructive commands. Modal gives GPU access for ML tasks.",
        "example_use_case": "Set to 'docker' if you want Hermes to run all commands in an isolated container instead of on your bare metal.",
    },
    "terminal.timeout": {
        "what_it_does": "Maximum seconds a single terminal command can run before being killed.",
        "why_it_matters": "Prevents commands from hanging forever. Some tasks (builds, downloads) need more time than the default 180 seconds.",
        "example_use_case": "Increase to 600 for long-running builds, or decrease to 60 for quick commands where hangs should fail fast.",
    },
    "display.personality": {
        "what_it_does": "Sets Hermes's default speaking style — concise, technical, creative, pirate, etc.",
        "why_it_matters": "Customize how Hermes communicates. 'Concise' for work, 'creative' for brainstorming, or 'pirate' for fun. Changes the system prompt.",
        "example_use_case": "Set to 'concise' for focused coding sessions, or switch to 'teacher' when learning new concepts.",
    },
    "compression.enabled": {
        "what_it_does": "Whether Hermes automatically compresses old conversation context to stay within model limits.",
        "why_it_matters": "Long conversations exceed model context windows. Compression summarizes older messages so Hermes can keep working without losing important context.",
        "example_use_case": "Keep enabled (default) for most use. Disable only if you notice Hermes forgetting important details from earlier in the conversation.",
    },
    "memory.memory_enabled": {
        "what_it_does": "Whether Hermes saves and recalls facts across different conversations.",
        "why_it_matters": "With memory on, Hermes remembers your preferences, project context, and past decisions. Without it, every conversation starts fresh.",
        "example_use_case": "Keep enabled so Hermes remembers your coding style, project architecture, and recurring tasks.",
    },
    "approvals.mode": {
        "what_it_does": "How Hermes handles potentially dangerous commands — 'manual' (ask first), 'auto' (run anyway), or 'yolo' (skip all checks).",
        "why_it_matters": "Safety net for destructive operations. 'Manual' means Hermes asks before running things like rm, git push --force, etc.",
        "example_use_case": "Keep 'manual' for safety. Switch to 'auto' during supervised sessions where speed matters more than caution.",
    },
    "checkpoints.enabled": {
        "what_it_does": "Automatically snapshot files before Hermes modifies them, so you can /rollback if something goes wrong.",
        "why_it_matters": "Your safety net for file operations. If Hermes breaks a config file or overwrites code, you can instantly restore the previous version.",
        "example_use_case": "Keep enabled (default). Use /rollback if Hermes ever makes unwanted changes to your files.",
    },
}


def _needs_enrichment(item):
    """Check if an item needs explainer text."""
    exp = item.get("explainer", {})
    return not exp.get("what_it_does")


def _enrich_tool(tool):
    """Generate explainer for a tool based on its name and description."""
    name = tool["name"]
    desc = tool.get("description", "")
    cat = tool.get("category", "")

    what = desc[:200] if desc else f"A {cat} tool called {name}."
    why = f"Adds {cat} capabilities to Hermes."
    example = f"Used automatically when your request involves {cat} operations."

    if "search" in name.lower() and "web" in name.lower():
        why = "Without web search, Hermes can only answer from its training data. This lets it look things up in real time."
        example = "Ask 'what's the latest Python version?' and Hermes will search the web for a current answer."
    elif "browser" in name.lower():
        why = "Some tasks need a real browser — JavaScript-rendered pages, logging into sites, or interacting with web apps."
        example = "Ask Hermes to check a dashboard, fill out a form, or take a screenshot of a webpage."
    elif "file" in name.lower() or name in ("read_file", "write_file", "patch", "search_files"):
        why = "File operations are core to coding, editing configs, and managing documents on your system."
        example = "Ask Hermes to read a log file, edit a config, or search for a pattern across your project."
    elif "terminal" in name.lower() or name == "process":
        why = "Terminal access lets Hermes run any shell command — install packages, check system status, run scripts."
        example = "Ask Hermes to restart a service, check disk space, or run a build command."
    elif "image" in name.lower() or "vision" in name.lower():
        why = "Visual capabilities let Hermes analyze screenshots, photos, and generate images from descriptions."
        example = "Send a screenshot and ask 'what's wrong with this UI?' or ask to generate a diagram."
    elif "memory" in name.lower():
        why = "Memory lets Hermes remember important facts across conversations — your preferences, project context, key decisions."
        example = "Tell Hermes to remember a deadline or a preferred coding style, and it'll recall it next time."
    elif "skill" in name.lower():
        why = "Skill management lets Hermes search, install, and use community-contributed or custom workflows."
        example = "Ask Hermes to find a skill for code review or install a specific skill from the hub."
    elif "todo" in name.lower():
        why = "Task tracking helps Hermes break complex requests into steps and track progress."
        example = "Ask Hermes to plan a refactoring — it creates a task list and checks items off as it works."
    elif name == "execute_code":
        why = "Runs Python, JavaScript, or other code in a sandbox without affecting your system."
        example = "Ask Hermes to calculate something or test a code snippet safely before writing it to a file."
    elif name == "delegate_task":
        why = "Spawns a sub-agent for complex sub-tasks, keeping the main conversation focused."
        example = "Ask Hermes to research something in depth while you continue with the main task."
    elif name == "send_message":
        why = "Cross-platform messaging lets Hermes send to any connected platform — great for notifications."
        example = "Ask Hermes to send a summary to your Telegram group or notify a Discord channel."
    elif "tts" in name.lower() or "speech" in name.lower():
        why = "Text-to-speech lets Hermes speak responses aloud — hands-free operation or accessibility."
        example = "Enable voice mode and Hermes will speak its responses using your TTS provider."
    elif "cronjob" in name.lower():
        why = "Create and manage scheduled tasks that run automatically on a timer."
        example = "Set up a daily backup job or a morning briefing that runs at 7 AM."
    elif "ha_" in name.lower() or "homeassistant" in name.lower():
        why = "Control your smart home in natural language — lights, locks, thermostats, sensors."
        example = "Say 'turn off the lights' or 'what's the temperature in the bedroom?' and it handles it."
    elif name == "clarify":
        why = "Lets Hermes ask you targeted questions when it needs more info before proceeding."
        example = "If your request is ambiguous, Hermes asks a clarifying question instead of guessing."
    elif "transcri" in name.lower():
        why = "Converts audio files to text — meeting notes, podcast summaries, voice memo processing."
        example = "Send an audio file and ask Hermes to transcribe it or summarize the key points."
    elif "web_extract" in name.lower():
        why = "Pulls actual content from URLs — turning web pages into clean text Hermes can analyze."
        example = "Share a URL and ask 'summarize this article' — extracts the content and gives you key points."
    elif name == "session_search":
        why = "Search across your past Hermes conversations to find what you discussed before."
        example = "Ask 'when did we set up the backup script?' and it'll find the relevant conversation."

    return {"what_it_does": what, "why_it_matters": why, "example_use_case": example}


def _enrich_command(cmd):
    """Generate explainer for a command."""
    name = cmd["name"]
    desc = cmd.get("description", "")
    cat = cmd.get("category", "").lower()

    usage = f"Type {name}"
    if cmd.get("args_hint"):
        usage += f" {cmd['args_hint']}"

    return {
        "what_it_does": desc or f"The {name} command.",
        "why_it_matters": f"Quick access to {cat} functionality without writing a full prompt.",
        "example_use_case": usage,
    }


CLI_SUBCOMMAND_EXPLAINERS = {
    "hermes dashboard": {
        "what_it_does": "Opens the Hermes web dashboard — a browser-based control panel for managing sessions, viewing logs, and monitoring agent activity.",
        "why_it_matters": "The dashboard gives you a visual overview of everything Hermes is doing. Much easier than reading terminal output for monitoring multiple sessions or checking history.",
        "example_use_case": "Run 'hermes dashboard' to open the web UI, then monitor active sessions, review conversation history, or manage cron jobs visually.",
    },
    "hermes gateway": {
        "what_it_does": "Starts the Hermes gateway server — the central hub that connects all platforms (Telegram, Discord, etc.) to the agent.",
        "why_it_matters": "The gateway is what makes Hermes accessible from messaging platforms. Without it running, only the CLI works.",
        "example_use_case": "Run 'hermes gateway' to start listening for messages from all configured platforms (Telegram, Discord, WhatsApp, etc.).",
    },
    "hermes backup": {
        "what_it_does": "Create, restore, or manage backups of your Hermes configuration, skills, and data.",
        "why_it_matters": "Protects your customizations — config, skills, memory, cron jobs — so you can restore after a bad update or migrate to a new machine.",
        "example_use_case": "Run 'hermes backup create' before a major update, or 'hermes backup restore' to roll back if something breaks.",
    },
    "hermes doctor": {
        "what_it_does": "Runs diagnostic checks on your Hermes installation — verifies dependencies, config, API keys, and system health.",
        "why_it_matters": "When something isn't working, 'hermes doctor' tells you exactly what's wrong instead of you guessing. Checks everything systematically.",
        "example_use_case": "Run 'hermes doctor' if tools stop working, API calls fail, or after an update to verify everything is healthy.",
    },
    "hermes sessions": {
        "what_it_does": "List, inspect, or manage active and past conversation sessions.",
        "why_it_matters": "See what conversations are happening across all platforms, check session history, or clean up stale sessions.",
        "example_use_case": "Run 'hermes sessions list' to see all active sessions, or 'hermes sessions inspect <id>' for conversation details.",
    },
    "hermes debug": {
        "what_it_does": "Enter debug mode — verbose logging, step-through execution, and detailed error reporting.",
        "why_it_matters": "When you need to understand exactly what Hermes is doing under the hood. Essential for troubleshooting complex issues.",
        "example_use_case": "Run 'hermes debug' to start a session with full verbose logging to diagnose why a tool or integration isn't working.",
    },
    "hermes profile": {
        "what_it_does": "Manage Hermes configuration profiles — switch between different setups for different use cases.",
        "why_it_matters": "Lets you maintain separate configurations (e.g., work vs personal, different API keys, different default models) and switch between them instantly.",
        "example_use_case": "Create a 'work' profile with your company's API keys and a 'personal' profile with your own, then switch with 'hermes profile use work'.",
    },
    "hermes mcp": {
        "what_it_does": "Manage MCP (Model Context Protocol) servers — add, remove, test, and list external tool servers.",
        "why_it_matters": "MCP servers extend Hermes with external capabilities (databases, APIs, custom tools). This command is how you manage those plugins.",
        "example_use_case": "Run 'hermes mcp add' to install a new MCP server, 'hermes mcp list' to see installed ones, or 'hermes mcp test' to verify they work.",
    },
    "hermes update": {
        "what_it_does": "Check for and install Hermes updates — pulls the latest version, runs migrations, and updates dependencies.",
        "why_it_matters": "Keeps Hermes current with new features, bug fixes, and security patches. The safest way to update — handles migrations automatically.",
        "example_use_case": "Run 'hermes update' periodically to get the latest version. It backs up your config first and shows what changed.",
    },
    "hermes config": {
        "what_it_does": "View or modify Hermes configuration settings from the command line.",
        "why_it_matters": "Quick way to check or change any setting without manually editing config.yaml. Supports dot-notation for nested values.",
        "example_use_case": "Run 'hermes config set model anthropic/claude-sonnet-4' to change the default model, or 'hermes config get terminal.backend' to check a value.",
    },
    "hermes install": {
        "what_it_does": "Install Hermes components, integrations, or skills from the skill hub.",
        "why_it_matters": "The standard way to add new capabilities to Hermes — handles dependencies, configuration, and post-install setup automatically.",
        "example_use_case": "Run 'hermes install <skill-name>' to add a skill from the hub, complete with any required configuration.",
    },
    "hermes cron": {
        "what_it_does": "Manage scheduled tasks — create, list, pause, resume, or delete cron jobs.",
        "why_it_matters": "Automate recurring tasks (daily briefings, backups, monitoring) that run on a schedule without manual intervention.",
        "example_use_case": "Run 'hermes cron list' to see all scheduled jobs, or 'hermes cron create' to set up a new automated task.",
    },
}


def _enrich_cli_subcommand(cmd):
    """Generate explainer for a CLI subcommand."""
    name = cmd.get("name", "")
    desc = cmd.get("description", "")

    if name in CLI_SUBCOMMAND_EXPLAINERS:
        return CLI_SUBCOMMAND_EXPLAINERS[name]

    pretty = name.replace("hermes ", "")
    return {
        "what_it_does": desc or f"CLI command: {name}",
        "why_it_matters": f"Provides '{pretty}' functionality from the terminal. Run '{name} --help' for detailed usage.",
        "example_use_case": f"Run '{name}' in your terminal. Use '{name} --help' to see available options and subcommands.",
    }


def _enrich_integration(integ):
    """Generate explainer for a platform integration."""
    key = integ.get("key", "")
    if key in PLATFORM_EXPLAINERS:
        return PLATFORM_EXPLAINERS[key]
    name = integ.get("name", "").strip()
    return {
        "what_it_does": f"Connects Hermes to {name} for messaging and notifications.",
        "why_it_matters": f"Access Hermes from {name} — send messages, share images, run commands.",
        "example_use_case": f"Set up the {name} integration and chat with Hermes from {name}.",
    }


def _enrich_config(opt):
    """Generate explainer for a config option."""
    key = opt.get("key", "")
    if key in CONFIG_EXPLAINERS:
        return CONFIG_EXPLAINERS[key]

    for prefix, exp in CONFIG_EXPLAINERS.items():
        if key.startswith(prefix + "."):
            parent_what = exp["what_it_does"]
            return {
                "what_it_does": f"Sub-setting of {prefix}: {key.split('.')[-1]}",
                "why_it_matters": f"Fine-tunes the {prefix} configuration. Part of: {parent_what}",
                "example_use_case": f"Edit in ~/.hermes/config.yaml under the {prefix} section.",
            }

    default = opt.get("default_value")
    default_str = f" Default: {default}" if default is not None and default != "" else ""
    section = key.split(".")[0] if "." in key else "general"
    return {
        "what_it_does": opt.get("description", "") or f"Configuration option: {key}",
        "why_it_matters": f"Controls {section} behavior.{default_str}",
        "example_use_case": f"Set via: hermes config set {key} <value> — or edit ~/.hermes/config.yaml",
    }


def _enrich_env_var(ev):
    """Generate explainer for an environment variable."""
    name = ev.get("name", "")
    desc = ev.get("description", "")

    if "API_KEY" in name or "TOKEN" in name:
        service = name.replace("_API_KEY", "").replace("_TOKEN", "").replace("_", " ").title()
        return {
            "what_it_does": desc or f"Authentication credential for {service}.",
            "why_it_matters": f"Required to use {service} with Hermes. Without it, {service} features won't work.",
            "example_use_case": f"Get your key from the {service} dashboard, then: hermes config set {name} your-key-here",
        }
    elif "BASE_URL" in name:
        service = name.replace("_BASE_URL", "").replace("_", " ").title()
        return {
            "what_it_does": desc or f"Override the API endpoint for {service}.",
            "why_it_matters": f"For self-hosted instances or regional endpoints. Most users don't need to change this.",
            "example_use_case": f"Only set this if you're using a custom/proxy {service} endpoint.",
        }
    return {
        "what_it_does": desc or f"Environment variable: {name}",
        "why_it_matters": "Configures Hermes behavior or service connectivity.",
        "example_use_case": f"Set in ~/.hermes/.env: {name}=your-value",
    }


def _enrich_skill(skill, is_user=False):
    """Generate explainer for a skill."""
    name = skill.get("name", "")
    desc = skill.get("description", "")

    if is_user:
        return {
            "what_it_does": desc[:200] if desc else f"Custom skill: {name}",
            "why_it_matters": "A skill you created or installed — tailored to your specific workflow.",
            "example_use_case": f"Hermes uses this skill when your request matches its pattern. View with: /skills inspect {name}",
        }

    pretty = name.replace("-", " ").replace("_", " ").title()
    return {
        "what_it_does": desc[:200] if desc else f"Bundled skill: {pretty}",
        "why_it_matters": f"Ships with Hermes — ready to use out of the box for {_skill_domain(name)} tasks.",
        "example_use_case": f"Hermes activates this skill automatically when relevant, or browse with /skills inspect {name}",
    }


def _skill_domain(name):
    """Guess the domain from skill name."""
    name_l = name.lower()
    if any(w in name_l for w in ("github", "git", "pr", "code-review", "code")):
        return "software development"
    if any(w in name_l for w in ("research", "arxiv", "paper")):
        return "research"
    if any(w in name_l for w in ("music", "song", "audio", "video", "media")):
        return "media and creative"
    if any(w in name_l for w in ("image", "diagram", "excalidraw", "manim", "ascii")):
        return "visual and creative"
    if any(w in name_l for w in ("mlops", "training", "fine-tuning", "llm", "model")):
        return "ML and AI"
    if any(w in name_l for w in ("docker", "devops", "deploy", "backup")):
        return "DevOps"
    if any(w in name_l for w in ("note", "obsidian", "notion", "writing")):
        return "productivity and writing"
    if any(w in name_l for w in ("game", "minecraft", "pokemon")):
        return "gaming"
    if any(w in name_l for w in ("email", "social", "x", "twitter")):
        return "communication"
    if any(w in name_l for w in ("home", "smart", "openhue")):
        return "smart home"
    if any(w in name_l for w in ("mcp", "webhook")):
        return "integration"
    return "specialized"


def _enrich_mcp(srv):
    """Generate explainer for an MCP server."""
    name = srv.get("name", "")
    cmd = srv.get("command", "")
    return {
        "what_it_does": f"MCP server '{name}' — extends Hermes with additional tools and data access.",
        "why_it_matters": "MCP servers plug in external capabilities that Hermes doesn't have built-in. Each server adds specific tools the agent can call.",
        "example_use_case": f"Manage with: hermes mcp list, hermes mcp test {name}, hermes mcp remove {name}",
    }


def _enrich_cron(job):
    """Generate explainer for a cron job."""
    name = job.get("name", "")
    schedule = job.get("schedule", "")
    deliver = job.get("deliver", "")
    return {
        "what_it_does": f"Scheduled task '{name}' running on schedule: {schedule}",
        "why_it_matters": "Automates a recurring task so you don't have to remember to run it manually.",
        "example_use_case": f"Results delivered to: {deliver}. Manage with /cron list, /cron pause {name}",
    }


def _enrich_backend(be):
    """Generate explainer for a terminal backend."""
    name = be.get("name", "")
    desc = be.get("description", "")
    return {
        "what_it_does": desc or f"Terminal execution backend: {name}",
        "why_it_matters": "Controls where and how Hermes runs shell commands — local, containerized, or remote.",
        "example_use_case": f"Switch to this backend: set terminal.backend to '{name}' in config.yaml",
    }


def enrich():
    """Enrich the manifest with section intros and explainers."""
    if not MANIFEST_PATH.exists():
        log.error("No manifest.json found — run the scanner first.")
        return

    manifest = json.loads(MANIFEST_PATH.read_text())
    enriched = 0

    manifest["section_intros"] = SECTION_INTROS

    ug = manifest["user_guide"]
    tr = manifest["technical_reference"]

    for tool in ug.get("tools", []):
        if _needs_enrichment(tool):
            tool["explainer"] = _enrich_tool(tool)
            enriched += 1

    for cmd in ug.get("commands", []):
        if _needs_enrichment(cmd):
            cmd["explainer"] = _enrich_command(cmd)
            enriched += 1

    for cmd in ug.get("cli_subcommands", []):
        if _needs_enrichment(cmd):
            cmd["explainer"] = _enrich_cli_subcommand(cmd)
            enriched += 1

    for skill in ug.get("skills", {}).get("bundled", []):
        if _needs_enrichment(skill):
            skill["explainer"] = _enrich_skill(skill, is_user=False)
            enriched += 1

    for skill in ug.get("skills", {}).get("user_created", []):
        if _needs_enrichment(skill):
            skill["explainer"] = _enrich_skill(skill, is_user=True)
            enriched += 1

    for integ in ug.get("integrations", []):
        if _needs_enrichment(integ):
            integ["explainer"] = _enrich_integration(integ)
            enriched += 1

    for opt in tr.get("config_options", []):
        if _needs_enrichment(opt):
            opt["explainer"] = _enrich_config(opt)
            enriched += 1

    for ev in tr.get("environment_variables", []):
        if _needs_enrichment(ev):
            ev["explainer"] = _enrich_env_var(ev)
            enriched += 1

    for srv in tr.get("mcp_servers", []):
        if _needs_enrichment(srv):
            srv["explainer"] = _enrich_mcp(srv)
            enriched += 1

    for job in tr.get("cron_jobs", []):
        if _needs_enrichment(job):
            job["explainer"] = _enrich_cron(job)
            enriched += 1

    for be in tr.get("terminal_backends", []):
        if _needs_enrichment(be):
            be["explainer"] = _enrich_backend(be)
            enriched += 1

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    log.info("Enriched %d items. Section intros: %d set.", enriched, len(SECTION_INTROS))


def main():
    log.info("═══ The Danual — Enricher ═══")
    log.info("")
    enrich()
    log.info("Done — manifest.json updated with explainers and section intros.")


if __name__ == "__main__":
    main()
