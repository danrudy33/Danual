#!/usr/bin/env python3
"""
The Danual — Renderer (Phase 4)
Takes the enriched manifest.json and produces a self-contained HTML manual.

v2: Compact layout, floating back-to-top, truncated cards, full detail in modals.
"""

import json
import html
import logging
import os
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR.parent / "output"
MANIFEST_PATH = OUTPUT_DIR / "manifest.json"
HERMES_HOME = Path.home() / ".hermes"
DOCS_DIR = HERMES_HOME / "docs"

logging.basicConfig(level=logging.INFO, format="  %(message)s")
log = logging.getLogger("danual-renderer")

E = html.escape


def _atomic_write(path: Path, content: str) -> None:
    """Write via temp-file + os.replace so concurrent readers never see a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _css():
    return """
:root {
  --bg: #0f1117;
  --surface: #161922;
  --surface2: #1e2230;
  --border: #272b3d;
  --text: #e2e4ed;
  --text-muted: #7d82a0;
  --accent: #7c6ff7;
  --accent-dim: rgba(124,111,247,0.10);
  --new-bg: rgba(52,211,153,0.07);
  --new-border: rgba(52,211,153,0.30);
  --new-text: #34d399;
  --new-glow: rgba(52,211,153,0.04);
  --user-bg: rgba(96,165,250,0.06);
  --user-border: rgba(96,165,250,0.22);
  --user-text: #60a5fa;
  --tag-hermes-bg: rgba(124,111,247,0.12);
  --tag-hermes-text: #a78bfa;
  --tag-user-bg: rgba(96,165,250,0.12);
  --tag-user-text: #60a5fa;
  --tag-mcp-bg: rgba(251,191,36,0.12);
  --tag-mcp-text: #fbbf24;
  --modal-bg: rgba(0,0,0,0.65);
  --scrollbar-thumb: #3a3f5a;
}
* { margin:0; padding:0; box-sizing:border-box; }
html { scroll-behavior: smooth; font-size: 13px; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Inter, system-ui, sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.55; min-height: 100vh;
}
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--scrollbar-thumb); border-radius: 3px; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
.container { max-width: 920px; margin: 0 auto; padding: 0 20px; }

/* ─── Header ─── */
header {
  background: linear-gradient(135deg, var(--surface) 0%, var(--surface2) 100%);
  border-bottom: 1px solid var(--border); padding: 28px 0 24px;
}
header h1 { font-size: 1.6rem; font-weight: 700; letter-spacing: -0.5px; margin-bottom: 2px; }
header h1 span { color: var(--accent); }
.header-meta { color: var(--text-muted); font-size: 0.85rem; margin-bottom: 16px; }
.search-wrap { position: relative; max-width: 520px; }
.search-wrap svg { position:absolute; left:12px; top:50%; transform:translateY(-50%); color:var(--text-muted); }
#search {
  width:100%; padding:10px 14px 10px 36px; background:var(--bg);
  border:1px solid var(--border); border-radius:8px; color:var(--text);
  font-size:0.9rem; outline:none; transition:border-color .2s;
}
#search:focus { border-color:var(--accent); }
#search::placeholder { color:var(--text-muted); }
.search-clear {
  position:absolute; right:10px; top:50%; transform:translateY(-50%);
  background:none; border:none; color:var(--text-muted); cursor:pointer;
  font-size:1rem; display:none; padding:2px 4px;
}

/* ─── What's New ─── */
.whats-new {
  background: var(--new-glow); border:1px solid var(--new-border);
  border-radius:10px; padding:14px 18px; margin:20px 0;
}
.whats-new h2 { color:var(--new-text); font-size:1rem; margin-bottom:8px; }
.whats-new ul { list-style:none; display:flex; flex-wrap:wrap; gap:6px 18px; }
.whats-new li { font-size:0.85rem; color:var(--text-muted); }
.whats-new li a { color:var(--new-text); }
.whats-new-hidden { display:none; }

/* ─── Recent User Additions ─── */
.recent-additions {
  background: rgba(96,165,250,0.04); border:1px solid var(--user-border);
  border-radius:10px; padding:14px 18px; margin:0 0 20px;
}
.recent-additions h2 { color:var(--user-text); font-size:1rem; margin-bottom:8px; }
.recent-additions ul { list-style:none; display:flex; flex-wrap:wrap; gap:6px 18px; }
.recent-additions li { font-size:0.85rem; color:var(--text-muted); }
.recent-additions li a { color:var(--user-text); }
.recent-additions-hidden { display:none; }

/* ─── Audit Summary ─── */
.audit-summary {
  background: rgba(239,68,68,0.04); border:1px solid rgba(239,68,68,0.22);
  border-radius:10px; padding:14px 18px; margin:0 0 20px;
}
.audit-summary h2 { color:#f87171; font-size:1rem; margin-bottom:8px; }
.audit-summary ul { list-style:none; display:flex; flex-wrap:wrap; gap:6px 18px; margin-bottom:6px; }
.audit-summary li { font-size:0.85rem; color:var(--text-muted); }
.audit-summary li a { color:#f87171; }
.audit-summary li.audit-ok a { color:#34d399; }
.audit-summary li.audit-suspect a { color:#fbbf24; }
.audit-summary .audit-note { font-size:0.78rem; color:var(--text-muted); margin-top:6px; }
.audit-summary-hidden { display:none; }

/* ─── Audit Badges ─── */
.audit-badge {
  font-size:0.6rem; font-weight:600; text-transform:uppercase; letter-spacing:0.4px;
  padding:1px 6px; border-radius:4px; flex-shrink:0; cursor:pointer; white-space:nowrap;
  border:1px solid transparent;
}
.audit-badge.audit-likely_junk { background:rgba(239,68,68,0.14); color:#f87171; border-color:rgba(239,68,68,0.32); }
.audit-badge.audit-suspect    { background:rgba(251,191,36,0.14); color:#fbbf24; border-color:rgba(251,191,36,0.32); }
.audit-badge.audit-legitimate { background:rgba(52,211,153,0.12); color:#34d399; border-color:rgba(52,211,153,0.28); }
.audit-badge.audit-exempt     { background:rgba(125,130,160,0.14); color:var(--text-muted); border-color:var(--border); }
.audit-badge:hover { filter:brightness(1.15); }

.audit-flags-list { margin:8px 0 0 0; padding-left:18px; }
.audit-flags-list li { color:var(--text); font-size:0.86rem; margin:4px 0; line-height:1.5; }
.audit-flags-list li strong { color:var(--accent); }
.audit-modal-score { font-size:0.85rem; color:var(--text-muted); margin-bottom:10px; }

/* ─── Junk Diagnosis Banner (modal) ─── */
.junk-banner {
  border-radius:10px; padding:14px 16px; margin:10px 0 16px;
  border:1px solid; line-height:1.55;
}
.junk-banner.junk-likely_junk {
  background:rgba(239,68,68,0.09); border-color:rgba(239,68,68,0.32); color:#fecaca;
}
.junk-banner.junk-suspect {
  background:rgba(251,191,36,0.08); border-color:rgba(251,191,36,0.32); color:#fde68a;
}
.junk-banner .junk-title {
  font-size:0.95rem; font-weight:700; margin-bottom:6px; display:flex; align-items:center; gap:6px;
}
.junk-banner .junk-score {
  font-size:0.72rem; font-weight:600; opacity:0.7; margin-left:auto;
  letter-spacing:0.4px;
}
.junk-banner .junk-verdict { font-size:0.88rem; margin-bottom:10px; }
.junk-banner .junk-reasons-title {
  font-size:0.7rem; text-transform:uppercase; letter-spacing:0.8px;
  opacity:0.75; margin:8px 0 4px;
}
.junk-banner ul.junk-reasons { list-style:none; padding:0; margin:0; }
.junk-banner ul.junk-reasons li {
  font-size:0.84rem; padding:4px 0 4px 18px; position:relative; line-height:1.5;
}
.junk-banner ul.junk-reasons li::before {
  content:"✗"; position:absolute; left:0; top:4px; font-weight:700; opacity:0.7;
}
.junk-banner .junk-action {
  margin-top:12px; padding-top:10px; border-top:1px solid rgba(255,255,255,0.08);
  font-size:0.82rem;
}
.junk-banner .junk-action code {
  display:block; background:rgba(0,0,0,0.35); padding:6px 10px; border-radius:6px;
  font-family:ui-monospace, SFMono-Regular, Menlo, monospace; font-size:0.8rem;
  margin-top:6px; color:#e2e4ed; overflow-x:auto; white-space:nowrap;
}
.modal-suppressed-note {
  font-size:0.78rem; color:var(--text-muted); font-style:italic;
  padding:8px 12px; background:var(--surface2); border-radius:6px;
  margin-bottom:12px;
}

/* ─── TOC ─── */
.toc {
  background:var(--surface); border:1px solid var(--border);
  border-radius:10px; padding:18px 20px; margin:16px 0 28px;
}
.toc h2 { font-size:0.85rem; color:var(--text); font-weight:700; text-transform:uppercase; letter-spacing:1px; margin-bottom:14px; }
.toc-group { margin-bottom:12px; }
.toc-group-title {
  font-size:0.76rem; color:var(--accent); text-transform:uppercase; letter-spacing:0.6px;
  margin-bottom:6px; font-weight:600; border-bottom:1px solid var(--border); padding-bottom:4px;
}
.toc ol { list-style:none; padding:0; display:grid; grid-template-columns:1fr 1fr 1fr; gap:2px 16px; }
.toc li a { font-size:0.88rem; display:inline-flex; align-items:center; gap:6px; padding:2px 0; }
.toc li a .ct { font-size:0.72rem; color:var(--text-muted); }
.toc-sub { padding-left:14px; margin-top:2px; display:flex; flex-direction:column; gap:1px; }
.toc-sub a { font-size:0.8rem; color:var(--text-muted); display:block; padding:1px 0; text-decoration:none; }
.toc-sub a::before { content:'— '; opacity:0.4; }
.toc-sub a:hover { color:var(--accent); }

/* ─── Sections ─── */
.section { margin-bottom:36px; }
.section-header {
  display:flex; align-items:center; gap:10px;
  margin-bottom:6px; padding-bottom:10px; border-bottom:1px solid var(--border);
}
.section-header h2 { font-size:1.2rem; font-weight:600; }
.section-count {
  font-size:0.72rem; color:var(--text-muted); background:var(--surface2);
  padding:1px 8px; border-radius:10px;
}
.section-intro { color:var(--text-muted); font-size:0.84rem; margin-bottom:14px; line-height:1.65; }

/* ─── Item Grid ─── */
.items-grid { display:grid; grid-template-columns:1fr 1fr; gap:6px; }
.items-grid.single-col { grid-template-columns:1fr; }

/* ─── Item Cards (compact) ─── */
.item {
  background:var(--surface); border:1px solid var(--border); border-radius:8px;
  padding:10px 14px; cursor:pointer; transition:border-color .12s, background .12s;
  display:flex; flex-direction:column; min-height:0;
}
.item:hover { border-color:var(--accent); background:var(--surface2); }
.item-header { display:flex; align-items:center; gap:6px; flex-wrap:nowrap; min-width:0; }
.item-name { font-weight:600; font-size:0.88rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.item-tag {
  font-size:0.6rem; font-weight:600; text-transform:uppercase; letter-spacing:0.4px;
  padding:1px 6px; border-radius:4px; flex-shrink:0;
}
.tag-hermes { background:var(--tag-hermes-bg); color:var(--tag-hermes-text); }
.tag-user { background:var(--tag-user-bg); color:var(--tag-user-text); }
.tag-mcp { background:var(--tag-mcp-bg); color:var(--tag-mcp-text); }
.item-new-badge {
  font-size:0.6rem; font-weight:600; color:var(--new-text);
  background:var(--new-bg); border:1px solid var(--new-border);
  padding:1px 6px; border-radius:4px; flex-shrink:0; white-space:nowrap;
}
.item-recent-badge {
  font-size:0.6rem; font-weight:600; color:var(--user-text);
  background:var(--tag-user-bg); border:1px solid var(--user-border);
  padding:1px 6px; border-radius:4px; flex-shrink:0; white-space:nowrap;
}
.item-desc {
  color:var(--text-muted); font-size:0.8rem; margin-top:3px;
  overflow:hidden; text-overflow:ellipsis; display:-webkit-box;
  -webkit-line-clamp:1; -webkit-box-orient:vertical;
}
.item-info { margin-left:auto; color:var(--text-muted); font-size:0.75rem; opacity:0.3; flex-shrink:0; }
.item:hover .item-info { opacity:0.8; }

.item.is-new { background:var(--new-bg); border-color:var(--new-border); }
.item.is-recent { background:var(--user-bg); border-color:var(--user-border); }
.item.is-user { background:var(--user-bg); border-color:var(--user-border); }

/* ─── Subsections ─── */
.subsection-title {
  font-size:0.85rem; font-weight:600; color:var(--text-muted);
  margin:16px 0 8px; text-transform:uppercase; letter-spacing:0.4px;
  grid-column:1/-1;
}

/* ─── Modal ─── */
.modal-overlay {
  position:fixed; inset:0; background:var(--modal-bg);
  display:none; align-items:center; justify-content:center;
  z-index:1000; padding:20px;
}
.modal-overlay.active { display:flex; }
.modal {
  background:var(--surface); border:1px solid var(--border); border-radius:14px;
  max-width:600px; width:100%; max-height:85vh; overflow-y:auto; padding:28px;
  position:relative;
}
.modal-close {
  position:absolute; top:12px; right:14px; background:none; border:none;
  color:var(--text-muted); font-size:1.2rem; cursor:pointer; padding:4px 8px; border-radius:6px;
}
.modal-close:hover { color:var(--text); background:var(--surface2); }
.modal h3 { font-size:1.1rem; margin-bottom:6px; padding-right:32px; }
.modal-desc { color:var(--text-muted); font-size:0.88rem; margin-bottom:16px; line-height:1.6; }
.modal-section { margin-bottom:14px; }
.modal-section h4 {
  font-size:0.7rem; text-transform:uppercase; letter-spacing:0.8px;
  color:var(--accent); margin-bottom:4px;
}
.modal-section p { color:var(--text); font-size:0.88rem; line-height:1.65; }
.modal-badges { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:12px; }
.modal-meta {
  font-size:0.78rem; color:var(--text-muted); margin-top:14px;
  padding-top:12px; border-top:1px solid var(--border);
}

/* ─── Floating Back to Top ─── */
.back-to-top {
  position:fixed; bottom:28px; right:28px; z-index:900;
  background:var(--accent); color:#fff; border:none; border-radius:50%;
  width:42px; height:42px; font-size:1.1rem; cursor:pointer;
  box-shadow:0 4px 16px rgba(0,0,0,0.4); display:none;
  align-items:center; justify-content:center; transition:opacity .2s, transform .2s;
}
.back-to-top:hover { transform:scale(1.1); }
.back-to-top.visible { display:flex; }

/* ─── Search ─── */
.hidden-by-search { display:none !important; }
.no-results { text-align:center; padding:32px; color:var(--text-muted); font-size:0.9rem; }

/* ─── Release Cards ─── */
.release-card {
  background:var(--surface); border:1px solid var(--border); border-radius:8px;
  padding:12px 16px; margin-bottom:8px; cursor:pointer;
  transition:border-color .12s, background .12s;
}
.release-card:hover { border-color:var(--accent); background:var(--surface2); }
.release-card h3 { font-size:0.95rem; margin-bottom:2px; display:flex; align-items:center; gap:8px; }
.release-card .click-hint { font-size:0.7rem; color:var(--text-muted); font-weight:400; opacity:0.5; }
.release-card:hover .click-hint { opacity:1; color:var(--accent); }
.release-card .date { color:var(--text-muted); font-size:0.78rem; margin-bottom:6px; }
.release-card ul { padding-left:18px; margin:0; }
.release-card li { color:var(--text-muted); font-size:0.82rem; margin:2px 0; }
.release-card li strong { color:var(--text); }
.release-modal-section { margin-bottom:16px; }
.release-modal-section h4 {
  font-size:0.78rem; text-transform:uppercase; letter-spacing:0.6px;
  color:var(--accent); margin-bottom:6px; padding-bottom:4px; border-bottom:1px solid var(--border);
}
.release-modal-section ul { padding-left:16px; margin:0; }
.release-modal-section li { color:var(--text-muted); font-size:0.84rem; margin:3px 0; line-height:1.55; }
.release-modal-section li strong { color:var(--text); }
.release-modal-section .subtitle { color:var(--text); font-size:0.82rem; font-weight:600; margin:8px 0 4px; }
.release-stats { color:var(--text-muted); font-size:0.78rem; margin-bottom:14px; }

/* ─── Footer ─── */
footer {
  border-top:1px solid var(--border); padding:20px 0; margin-top:36px;
  color:var(--text-muted); font-size:0.78rem; text-align:center;
}

/* ─── Responsive ─── */
@media (max-width:700px) {
  html { font-size:12px; }
  .items-grid { grid-template-columns:1fr; }
  .toc ol { grid-template-columns:1fr; }
  .container { padding:0 14px; }
  .back-to-top { bottom:16px; right:16px; width:36px; height:36px; font-size:0.9rem; }
}
"""


def _js():
    return """
document.addEventListener('DOMContentLoaded', () => {
  const searchInput = document.getElementById('search');
  const clearBtn = document.querySelector('.search-clear');
  const sections = document.querySelectorAll('.section');
  const allItems = document.querySelectorAll('.item');
  const noResults = document.getElementById('no-results');
  const backBtn = document.getElementById('back-to-top');

  // Search
  searchInput.addEventListener('input', () => {
    const q = searchInput.value.trim().toLowerCase();
    clearBtn.style.display = q ? 'block' : 'none';
    if (!q) {
      allItems.forEach(el => el.classList.remove('hidden-by-search'));
      sections.forEach(s => s.classList.remove('hidden-by-search'));
      noResults.classList.add('hidden-by-search');
      return;
    }
    let anyVisible = false;
    sections.forEach(sec => {
      const items = sec.querySelectorAll('.item');
      let sectionHasMatch = false;
      items.forEach(item => {
        const text = item.dataset.search || '';
        if (text.includes(q)) {
          item.classList.remove('hidden-by-search');
          sectionHasMatch = true;
          anyVisible = true;
        } else {
          item.classList.add('hidden-by-search');
        }
      });
      sec.classList.toggle('hidden-by-search', !sectionHasMatch);
    });
    noResults.classList.toggle('hidden-by-search', anyVisible);
  });

  clearBtn.addEventListener('click', () => {
    searchInput.value = '';
    searchInput.dispatchEvent(new Event('input'));
    searchInput.focus();
  });

  // Modal
  const overlay = document.getElementById('modal-overlay');
  const modal = document.getElementById('modal');

  const SOURCE_LABELS = {hermes: 'Hermes', user: 'You', mcp: 'MCP'};
  function renderBadges(data) {
    if (!data || typeof data !== 'object') return '';
    let h = '';
    if (data.source && SOURCE_LABELS[data.source]) {
      h += '<span class="item-tag tag-' + data.source + '">' + SOURCE_LABELS[data.source] + '</span>';
    }
    if (data.badge === 'new') {
      h += '<span class="item-new-badge">✨ NEW</span>';
    } else if (data.badge === 'recent') {
      h += '<span class="item-recent-badge">🆕 Recently Added</span>';
    }
    return h;
  }
  function renderMeta(items) {
    if (!Array.isArray(items) || !items.length) return '';
    return items.map(m => {
      const val = esc(String(m.value || ''));
      return m.label ? esc(m.label) + ': ' + val : val;
    }).join(' \u00B7 ');
  }
  function safeParse(s, fallback) {
    try { return JSON.parse(s); } catch (e) { return fallback; }
  }

  const AUDIT_TITLES = {
    likely_junk: '🔴 Likely Junk',
    suspect: '🟡 Suspect',
    legitimate: '🟢 Legitimate',
    exempt: '⚪ Exempt (whitelisted)',
  };

  // Plain-English translations for audit flag codes + the evidence the auditor
  // recorded. These are what the user actually reads in the diagnosis banner —
  // not the machine codes ("no_workflow_structure") or raw regex snippets.
  const FLAG_EXPLANATIONS = {
    narrative_phrase:        "Written like a diary entry ('we found', 'turns out', 'today'), not a reusable procedure.",
    dated_fact:              "Contains specific dates or times — this skill is locked to one moment rather than being evergreen.",
    dated_fact_in_commands:  "Dates are hard-coded inside shell commands — the commands will go stale.",
    no_workflow_structure:   "No numbered steps, no Workflow/Usage/Steps section — this isn't a procedure, it's prose.",
    no_commands:             "No code blocks, file paths, or commands — there's nothing here to actually run.",
    no_trigger_conditions:   "No 'When to use' section — there's no clear signal for when this skill should activate.",
    opinion_summary:         "Contains verdict/opinion language ('key finding', 'my take', 'bottom line') — this is an observation, not instructions.",
    short_body:              "Too short to be a real procedure (under 500 chars).",
    static_observations:     "Contains specific numbers (counts, dollar amounts, percentages) that are frozen snapshots of one moment.",
    narrative_headings:      "Uses descriptive headings like 'Problem', 'Symptoms', 'The Fix', 'Key Finding' — this is a troubleshooting writeup, not a playbook.",
    comparison_table:        "Structured as a comparison table — informational content, not actionable steps.",
  };

  const JUNK_VERDICTS = {
    likely_junk: "This looks like a session narrative that got saved as a skill — a one-time troubleshooting note, not a reusable procedure. Reading it won't help Hermes do anything next time; it'll just pollute context.",
    suspect:     "This has mixed signals. It might be a real procedure with some narrative quirks, or it might be a dressed-up session note. Open the SKILL.md and judge for yourself before trusting it.",
  };

  function explainFlag(flag) {
    // Prefer the plain-English explanation; fall back to the raw evidence
    // so we never hide information the auditor surfaced.
    const plain = FLAG_EXPLANATIONS[flag.type];
    if (plain) return plain;
    return (flag.evidence || flag.type || '').toString();
  }

  function renderJunkBanner(audit, skillName) {
    if (!audit || (audit.status !== 'likely_junk' && audit.status !== 'suspect')) return '';
    const title = AUDIT_TITLES[audit.status] || audit.status;
    const verdict = JUNK_VERDICTS[audit.status] || '';
    const flags = audit.flags || [];
    let h = '<div class="junk-banner junk-' + esc(audit.status) + '">';
    h += '<div class="junk-title">' + esc(title);
    h += '<span class="junk-score">Score ' + (audit.score | 0) + '/100</span></div>';
    if (verdict) h += '<div class="junk-verdict">' + esc(verdict) + '</div>';
    if (flags.length) {
      h += '<div class="junk-reasons-title">Why it was flagged</div>';
      h += '<ul class="junk-reasons">';
      for (const f of flags) {
        h += '<li>' + esc(explainFlag(f)) + '</li>';
      }
      h += '</ul>';
    }
    if (audit.status === 'likely_junk') {
      // Give the user an exact command they can run to nuke it.
      const safeName = (skillName || '').replace(/[^a-zA-Z0-9._-]/g, '');
      h += '<div class="junk-action">';
      h += 'If you agree this is junk, find and delete it:';
      h += '<code>find ~/.hermes/skills -type d -name ' + esc(safeName) + ' -exec rm -rf {} +</code>';
      h += '</div>';
    }
    h += '</div>';
    return h;
  }

  function openAuditModal(audit, skillName) {
    const title = AUDIT_TITLES[audit.status] || audit.status;
    let h = '<h3>' + esc(skillName) + '</h3>';
    // For flagged skills, show the plain-English diagnosis banner as the
    // whole body — clicking a 🔴/🟡 badge should explain why, period.
    if (audit.status === 'likely_junk' || audit.status === 'suspect') {
      h += renderJunkBanner(audit, skillName);
    } else {
      h += '<div class="audit-modal-score">' + esc(title) + ' &middot; Score: ' + (audit.score | 0) + '</div>';
      if (audit.status === 'exempt') {
        h += '<p>This skill is whitelisted via <code>do_not_audit: true</code> in its frontmatter.</p>';
      } else if (!audit.flags || !audit.flags.length) {
        h += '<p>No junk signals detected — this skill looks like a legitimate procedure.</p>';
      } else {
        h += '<div class="modal-section"><h4>Minor signals (did not trip the threshold)</h4><ul class="audit-flags-list">';
        for (const f of audit.flags) {
          h += '<li>' + esc(explainFlag(f)) + '</li>';
        }
        h += '</ul></div>';
      }
    }
    modal.innerHTML = '<button class="modal-close" aria-label="Close">&times;</button>' + h;
    overlay.classList.add('active');
    modal.querySelector('.modal-close').addEventListener('click', closeModal);
  }

  document.querySelectorAll('.audit-badge').forEach(badge => {
    badge.addEventListener('click', e => {
      e.stopPropagation();
      const audit = safeParse(badge.dataset.audit, {});
      const name = badge.dataset.itemName || '';
      openAuditModal(audit, name);
    });
  });

  allItems.forEach(item => {
    item.addEventListener('click', () => {
      const data = safeParse(item.dataset.explainer, {});
      const name = item.dataset.itemName || '';
      const desc = item.dataset.fullDesc || '';
      const badgesData = safeParse(item.dataset.badges, {});
      const metaData = safeParse(item.dataset.modalMeta, []);
      const auditData = safeParse(item.dataset.audit, null);
      const badgesHtml = renderBadges(badgesData);
      const metaHtml = renderMeta(metaData);
      const isFlagged = auditData && (auditData.status === 'likely_junk' || auditData.status === 'suspect');

      let h = '<h3>' + esc(name) + '</h3>';
      if (badgesHtml) h += '<div class="modal-badges">' + badgesHtml + '</div>';

      if (isFlagged) {
        // Lead with the diagnosis — the whole point of clicking a flagged
        // skill is to decide whether to delete it, not to read AI-generated
        // "what it does" fluff that dresses up garbage as legit.
        h += renderJunkBanner(auditData, name);
        // Show the raw description (from the skill's own frontmatter) but
        // suppress the enricher's misleading what_it_does/why_it_matters/example
        // blocks. Those are AI-generated polish that makes junk look real.
        if (desc) {
          h += '<div class="modal-section"><h4>Description (from the skill itself)</h4>';
          h += '<p style="color:var(--text-muted);font-size:0.85rem">' + esc(desc) + '</p></div>';
        }
        h += '<div class="modal-suppressed-note">The auto-generated \"What it does / Why it matters / Example\" section is hidden for flagged skills — it tends to make low-quality skills look legitimate.</div>';
      } else {
        if (desc) h += '<div class="modal-desc">' + esc(desc) + '</div>';
        if (data.what_it_does) {
          h += '<div class="modal-section"><h4>What it does</h4><p>' + esc(data.what_it_does) + '</p></div>';
        }
        if (data.why_it_matters) {
          h += '<div class="modal-section"><h4>Why it matters</h4><p>' + esc(data.why_it_matters) + '</p></div>';
        }
        if (data.example_use_case) {
          h += '<div class="modal-section"><h4>Example</h4><p>' + esc(data.example_use_case) + '</p></div>';
        }
        if (auditData && auditData.status) {
          const title = AUDIT_TITLES[auditData.status] || auditData.status;
          h += '<div class="modal-section"><h4>Audit</h4>';
          h += '<p>' + esc(title) + ' &middot; Score: ' + (auditData.score | 0) + '</p>';
          if (auditData.flags && auditData.flags.length) {
            h += '<ul class="audit-flags-list">';
            for (const f of auditData.flags) {
              h += '<li>' + esc(explainFlag(f)) + '</li>';
            }
            h += '</ul>';
          }
          h += '</div>';
        }
      }

      if (metaHtml) h += '<div class="modal-meta">' + metaHtml + '</div>';
      modal.innerHTML = '<button class="modal-close" aria-label="Close">&times;</button>' + h;
      overlay.classList.add('active');
      modal.querySelector('.modal-close').addEventListener('click', closeModal);
    });
  });

  overlay.addEventListener('click', e => { if (e.target === overlay) closeModal(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
  function closeModal() { overlay.classList.remove('active'); }
  function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  // Release note modals
  document.querySelectorAll('.release-card').forEach(card => {
    card.addEventListener('click', () => {
      const data = safeParse(card.dataset.release, {});
      let h = '<h3>Hermes v' + esc(data.version || '?') + ' Release Notes</h3>';
      if (data.date) h += '<div class="release-stats">' + esc(data.date) + '</div>';
      if (data.stats) h += '<div class="release-stats">' + esc(data.stats) + '</div>';
      const sections = data.sections || [];
      for (const sec of sections) {
        if (!sec.items || sec.items.length === 0) continue;
        h += '<div class="release-modal-section"><h4>' + esc(sec.title || '') + '</h4><ul>';
        for (const item of sec.items) {
          if (item.subtitle) {
            h += '</ul><div class="subtitle">' + esc(item.subtitle) + '</div><ul>';
          } else {
            h += '<li><strong>' + esc(item.title || '') + '</strong>';
            if (item.summary) h += ' — ' + esc(item.summary);
            h += '</li>';
          }
        }
        h += '</ul></div>';
      }
      modal.innerHTML = '<button class="modal-close" aria-label="Close">&times;</button>' + h;
      overlay.classList.add('active');
      modal.querySelector('.modal-close').addEventListener('click', closeModal);
    });
  });

  // Back to top
  window.addEventListener('scroll', () => {
    backBtn.classList.toggle('visible', window.scrollY > 400);
  });
  backBtn.addEventListener('click', () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
});
"""


def _source_tag(source):
    if source == "user":
        return '<span class="item-tag tag-user">You</span>'
    if source == "mcp":
        return '<span class="item-tag tag-mcp">MCP</span>'
    return '<span class="item-tag tag-hermes">Hermes</span>'


def _item_classes(item):
    cls = ["item"]
    if item.get("is_new"):
        cls.append("is-new")
    elif item.get("recently_added"):
        cls.append("is-recent")
    if item.get("source") == "user":
        cls.append("is-user")
    return " ".join(cls)


def _search_text(item):
    parts = [
        item.get("name", ""), item.get("key", ""), item.get("description", ""),
        item.get("category", ""), item.get("context", ""),
    ]
    for a in item.get("aliases", []):
        parts.append(a)
    exp = item.get("explainer", {})
    parts.append(exp.get("what_it_does", ""))
    parts.append(exp.get("why_it_matters", ""))
    return " ".join(p for p in parts if p).lower()


def _modal_meta_fields(item):
    """Return structured [{label, value}] list for the modal footer metadata.

    JS escapes each value before insertion, so raw strings (no pre-escaping) here.
    """
    parts = []
    if item.get("category"):
        parts.append({"label": "Category", "value": item["category"]})
    if item.get("context") and item["context"] != "both":
        parts.append({"label": "", "value": f"{item['context']} only"})
    if item.get("source"):
        parts.append({"label": "Source", "value": item["source"]})
    if item.get("added_in_version"):
        parts.append({"label": "", "value": f"Added in v{item['added_in_version']}"})
    if item.get("recently_added"):
        added_at = item.get("added_at", "")
        try:
            ts = datetime.fromisoformat(added_at.replace("Z", "+00:00"))
            parts.append({"label": "", "value": f"Recently added ({ts.strftime('%b %d, %Y')})"})
        except Exception:
            parts.append({"label": "", "value": "Recently added"})
    if item.get("parameters"):
        parts.append({"label": "Params", "value": ", ".join(item["parameters"])})
    if item.get("aliases"):
        parts.append({"label": "Aliases", "value": ", ".join(item["aliases"])})
    if item.get("default_toolset"):
        parts.append({"label": "Toolset", "value": item["default_toolset"]})
    if item.get("schedule"):
        parts.append({"label": "Schedule", "value": item["schedule"]})
    dv = item.get("default_value")
    if dv is not None and dv != "" and dv != []:
        ds = json.dumps(dv) if not isinstance(dv, str) else dv
        parts.append({"label": "Default", "value": str(ds)[:100]})
    return parts


def _badges_data(item):
    """Return structured badge info for the modal. JS maps source → display label."""
    data = {"source": item.get("source", "hermes")}
    if item.get("is_new"):
        data["badge"] = "new"
    elif item.get("recently_added"):
        data["badge"] = "recent"
    return data


def _truncate(text, max_len=90):
    if not text or len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "…"


_AUDIT_LABELS = {
    "likely_junk": ("🔴", "Likely Junk"),
    "suspect": ("🟡", "Suspect"),
    "legitimate": ("🟢", "Legitimate"),
    "exempt": ("⚪", "Exempt"),
}


def _audit_badge_html(item):
    """Render the audit badge for a user skill, or empty string if none."""
    audit = item.get("audit")
    if not audit or not audit.get("status"):
        return ""
    status = audit["status"]
    label = _AUDIT_LABELS.get(status, ("", status.title()))[1]
    audit_json = E(json.dumps(audit))
    name = E(item.get("name", ""))
    return (
        f'<span class="audit-badge audit-{E(status)}" '
        f'data-audit="{audit_json}" data-item-name="{name}" '
        f'title="Click for audit details">{E(label)}</span>'
    )


def _render_item(item, name_field="name", show_desc=True, max_desc=90):
    name = item.get(name_field, "")
    desc = item.get("description", "")
    full_desc = desc
    short_desc = _truncate(desc, max_desc) if show_desc else ""

    marker = ""
    if item.get("is_new"):
        marker = "✨ "
    elif item.get("recently_added"):
        marker = "🆕 "
    elif item.get("source") == "user":
        marker = "👤 "

    exp_json = E(json.dumps(item.get("explainer", {})))
    search = E(_search_text(item))
    badges_json = E(json.dumps(_badges_data(item)))
    meta_json = E(json.dumps(_modal_meta_fields(item)))
    audit = item.get("audit")
    audit_attr = f' data-audit="{E(json.dumps(audit))}"' if audit else ""

    h = f'<div class="{_item_classes(item)}" data-search="{search}" '
    h += f'data-explainer="{exp_json}" data-item-name="{E(name)}" '
    h += f'data-full-desc="{E(full_desc)}" data-badges="{badges_json}" '
    h += f'data-modal-meta="{meta_json}"{audit_attr}>'
    h += '<div class="item-header">'
    h += f'<span class="item-name">{marker}{E(name)}</span>'
    h += _source_tag(item.get("source", "hermes"))
    if item.get("is_new"):
        h += '<span class="item-new-badge">✨ NEW</span>'
    elif item.get("recently_added"):
        h += '<span class="item-recent-badge">🆕 Recently Added</span>'
    h += _audit_badge_html(item)
    h += '<span class="item-info">ℹ</span>'
    h += '</div>'
    if short_desc:
        h += f'<div class="item-desc">{E(short_desc)}</div>'
    return h + '</div>\n'


def _render_whats_new(manifest):
    ug = manifest["user_guide"]
    tr = manifest["technical_reference"]
    counts = {}
    for label, anchor, items in [
        ("tools", "tools", ug.get("tools", [])),
        ("commands", "commands", ug.get("commands", [])),
        ("CLI commands", "cli-subcommands", ug.get("cli_subcommands", [])),
        ("skills", "skills", ug.get("skills", {}).get("bundled", [])),
        ("integrations", "integrations", ug.get("integrations", [])),
        ("config options", "config-options", tr.get("config_options", [])),
        ("env vars", "environment-variables", tr.get("environment_variables", [])),
    ]:
        n = sum(1 for i in items if i.get("is_new"))
        if n:
            counts[label] = (n, anchor)

    if not counts:
        return '<div class="whats-new whats-new-hidden"></div>'

    version = manifest.get("version", "?")
    prev = manifest.get("previous_version", "")
    h = '<div class="whats-new">'
    h += f'<h2>✨ What\'s New in v{E(version)}</h2>'
    if prev:
        h += f'<p style="color:var(--text-muted);font-size:0.8rem;margin-bottom:8px">Updated from v{E(prev)}</p>'
    h += '<ul>'
    for label, (count, anchor) in counts.items():
        h += f'<li><a href="#{anchor}">{count} new {label}</a></li>'
    h += '</ul></div>'
    return h


def _render_audit_summary(manifest):
    """Audit summary lists junk/suspect/legitimate/exempt counts and links to user skills."""
    user_skills = manifest.get("user_guide", {}).get("skills", {}).get("user_created", [])
    if not user_skills:
        return '<div class="audit-summary audit-summary-hidden"></div>'

    counts = {"likely_junk": 0, "suspect": 0, "legitimate": 0, "exempt": 0}
    for s in user_skills:
        status = (s.get("audit") or {}).get("status")
        if status in counts:
            counts[status] += 1
    if not any(counts.values()):
        return '<div class="audit-summary audit-summary-hidden"></div>'

    h = '<div class="audit-summary">'
    h += '<h2>🔍 Skill Audit</h2>'
    h += '<ul>'
    if counts["likely_junk"]:
        h += f'<li><a href="#skills-user">🔴 {counts["likely_junk"]} likely junk</a></li>'
    if counts["suspect"]:
        h += f'<li class="audit-suspect"><a href="#skills-user">🟡 {counts["suspect"]} suspect</a></li>'
    if counts["legitimate"]:
        h += f'<li class="audit-ok"><a href="#skills-user">🟢 {counts["legitimate"]} legitimate</a></li>'
    if counts["exempt"]:
        h += f'<li>⚪ {counts["exempt"]} exempt (whitelisted)</li>'
    h += '</ul>'
    if counts["likely_junk"] or counts["suspect"]:
        h += '<p class="audit-note">Click a badge on any user skill to see why it was flagged. A future quarantine tool can move junk skills without deleting them.</p>'
    h += '</div>'
    return h


def _audit_sort_key(skill):
    """Sort order for user skills: likely_junk → suspect → legitimate → exempt → unaudited."""
    order = {"likely_junk": 0, "suspect": 1, "legitimate": 2, "exempt": 3}
    status = (skill.get("audit") or {}).get("status")
    return (order.get(status, 4), -(skill.get("audit") or {}).get("score", 0), skill.get("name", ""))


def _render_recent_additions(manifest):
    ug = manifest["user_guide"]
    tr = manifest["technical_reference"]
    counts = {}
    for label, anchor, items in [
        ("bundled skills", "skills-bundled", ug.get("skills", {}).get("bundled", [])),
        ("user skills", "skills-user", ug.get("skills", {}).get("user_created", [])),
        ("tools", "tools", ug.get("tools", [])),
        ("commands", "commands", ug.get("commands", [])),
        ("CLI commands", "cli-subcommands", ug.get("cli_subcommands", [])),
        ("integrations", "integrations", ug.get("integrations", [])),
        ("config options", "config-options", tr.get("config_options", [])),
        ("env vars", "environment-variables", tr.get("environment_variables", [])),
        ("MCP servers", "mcp-servers", tr.get("mcp_servers", [])),
        ("cron jobs", "cron-jobs", tr.get("cron_jobs", [])),
    ]:
        n = sum(1 for i in items if i.get("recently_added"))
        if n:
            counts[label] = (n, anchor)

    if not counts:
        return '<div class="recent-additions recent-additions-hidden"></div>'

    h = '<div class="recent-additions">'
    h += '<h2>🆕 Recent User Additions</h2>'
    h += '<ul>'
    for label, (count, anchor) in counts.items():
        h += f'<li><a href="#{anchor}">{count} {label}</a></li>'
    h += '</ul></div>'
    return h


def render(manifest):
    version = manifest.get("version", "unknown")
    gen_at = manifest.get("generated_at", "")
    try:
        dt = datetime.fromisoformat(gen_at.replace("Z", "+00:00"))
        gen_display = dt.strftime("%B %d, %Y at %H:%M UTC")
    except Exception:
        gen_display = gen_at

    ug = manifest["user_guide"]
    tr = manifest["technical_reference"]
    intros = manifest.get("section_intros", {})
    release_notes = manifest.get("release_notes", [])

    skills_bundled = ug.get("skills", {}).get("bundled", [])
    skills_user = ug.get("skills", {}).get("user_created", [])

    cli_subcommands = ug.get("cli_subcommands", [])

    toc_entries = [
        ("User Guide", [
            ("Tools", "tools", len(ug.get("tools", []))),
            ("Commands", "commands", len(ug.get("commands", []))),
            ("CLI Commands", "cli-subcommands", len(cli_subcommands)),
            ("Skills", "skills", len(skills_bundled) + len(skills_user), [
                ("Bundled Skills", "skills-bundled", len(skills_bundled)),
                ("Your Skills", "skills-user", len(skills_user)),
            ]),
            ("Platform Integrations", "integrations", len(ug.get("integrations", []))),
        ]),
        ("Technical Reference", [
            ("Configuration", "config-options", len(tr.get("config_options", []))),
            ("Environment Variables", "environment-variables", len(tr.get("environment_variables", []))),
            ("MCP Servers", "mcp-servers", len(tr.get("mcp_servers", []))),
            ("Cron Jobs", "cron-jobs", len(tr.get("cron_jobs", []))),
            ("Terminal Backends", "terminal-backends", len(tr.get("terminal_backends", []))),
        ]),
    ]
    if release_notes:
        toc_entries.append(("Appendix", [
            ("Release History", "release-history", len(release_notes)),
        ]))

    parts = []
    parts.append(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Danual — Dan's Dynamic-Manual for Hermes</title>
<style>{_css()}</style>
</head>
<body>

<header>
<div class="container">
  <h1>The <span>Danual</span></h1>
  <div class="header-meta">Dan's Dynamic-Manual for Hermes &middot; v{E(version)} &middot; {E(gen_display)}</div>
  <div class="search-wrap">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
    <input type="text" id="search" placeholder="Search tools, commands, skills..." autocomplete="off">
    <button class="search-clear" aria-label="Clear">&times;</button>
  </div>
</div>
</header>

<main class="container">
""")

    # What's New
    parts.append(_render_whats_new(manifest))
    parts.append(_render_recent_additions(manifest))
    parts.append(_render_audit_summary(manifest))

    # TOC
    parts.append('<nav class="toc" id="toc"><h2>Contents</h2>')
    for group_title, entries in toc_entries:
        parts.append(f'<div class="toc-group"><div class="toc-group-title">{E(group_title)}</div><ol>')
        for entry in entries:
            title, anchor, count = entry[0], entry[1], entry[2]
            subs = entry[3] if len(entry) > 3 else None
            parts.append(f'<li><a href="#{anchor}">{E(title)} <span class="ct">{count}</span></a>')
            if subs:
                parts.append('<div class="toc-sub">')
                for st, sa, sc in subs:
                    parts.append(f'<a href="#{sa}">{E(st)} <span class="ct">{sc}</span></a>')
                parts.append('</div>')
            parts.append('</li>')
        parts.append('</ol></div>')
    parts.append('</nav>')

    # ── Tools ──
    tools = ug.get("tools", [])
    parts.append(_sec("tools", "Tools", len(tools), intros.get("tools", "")))
    parts.append('<div class="items-grid">')
    for t in tools:
        parts.append(_render_item(t, max_desc=70))
    parts.append('</div></div>')

    # ── Commands ──
    commands = ug.get("commands", [])
    parts.append(_sec("commands", "Commands", len(commands), intros.get("commands", "")))
    parts.append('<div class="items-grid">')
    by_cat = {}
    for c in commands:
        by_cat.setdefault(c.get("category", "Other"), []).append(c)
    for cat in ["Session", "Configuration", "Tools & Skills", "Info", "Exit"]:
        cmds = by_cat.pop(cat, [])
        if not cmds:
            continue
        parts.append(f'<div class="subsection-title">{E(cat)}</div>')
        for c in cmds:
            parts.append(_render_item(c, max_desc=70))
    for cat, cmds in by_cat.items():
        if cmds:
            parts.append(f'<div class="subsection-title">{E(cat)}</div>')
            for c in cmds:
                parts.append(_render_item(c, max_desc=70))
    parts.append('</div></div>')

    # ── CLI Commands ──
    if cli_subcommands:
        parts.append(_sec("cli-subcommands", "CLI Commands", len(cli_subcommands), intros.get("cli_subcommands", "")))
        parts.append('<div class="items-grid">')
        for cmd in cli_subcommands:
            parts.append(_render_item(cmd, max_desc=70))
        parts.append('</div></div>')

    # ── Skills ──
    parts.append(_sec("skills", "Skills", len(skills_bundled) + len(skills_user), intros.get("skills", "")))
    parts.append(f'<div class="subsection-title" id="skills-bundled">Bundled Skills ({len(skills_bundled)})</div>')
    parts.append('<div class="items-grid">')
    for s in skills_bundled:
        parts.append(_render_item(s, max_desc=60))
    parts.append('</div>')
    if skills_user:
        parts.append(f'<div class="subsection-title" id="skills-user">Your Skills ({len(skills_user)})</div>')
        parts.append('<div class="items-grid">')
        # Show flagged skills first so users see problems before scanning.
        for s in sorted(skills_user, key=_audit_sort_key):
            parts.append(_render_item(s, max_desc=60))
        parts.append('</div>')
    parts.append('</div>')

    # ── Integrations ──
    integrations = ug.get("integrations", [])
    parts.append(_sec("integrations", "Platform Integrations", len(integrations), intros.get("integrations", "")))
    parts.append('<div class="items-grid">')
    for i in integrations:
        parts.append(_render_item(i, max_desc=80))
    parts.append('</div></div>')

    # ── Config ──
    config_opts = tr.get("config_options", [])
    parts.append(_sec("config-options", "Configuration", len(config_opts), intros.get("config_options", "")))
    parts.append('<div class="items-grid">')
    for opt in config_opts:
        item = {**opt, "name": opt.get("key", ""), "source": opt.get("source", "hermes")}
        parts.append(_render_item(item, max_desc=60))
    parts.append('</div></div>')

    # ── Env Vars ──
    env_vars = tr.get("environment_variables", [])
    parts.append(_sec("environment-variables", "Environment Variables", len(env_vars), intros.get("environment_variables", "")))
    parts.append('<div class="items-grid">')
    for ev in env_vars:
        parts.append(_render_item(ev, max_desc=60))
    parts.append('</div></div>')

    # ── MCP Servers ──
    mcp_servers = tr.get("mcp_servers", [])
    parts.append(_sec("mcp-servers", "MCP Servers", len(mcp_servers), intros.get("mcp_servers", "")))
    parts.append('<div class="items-grid single-col">')
    for srv in mcp_servers:
        parts.append(_render_item(srv))
    parts.append('</div></div>')

    # ── Cron Jobs ──
    cron_jobs = tr.get("cron_jobs", [])
    parts.append(_sec("cron-jobs", "Cron Jobs", len(cron_jobs), intros.get("cron_jobs", "")))
    parts.append('<div class="items-grid single-col">')
    for job in cron_jobs:
        parts.append(_render_item(job))
    parts.append('</div></div>')

    # ── Terminal Backends ──
    backends = tr.get("terminal_backends", [])
    parts.append(_sec("terminal-backends", "Terminal Backends", len(backends), intros.get("terminal_backends", "")))
    parts.append('<div class="items-grid">')
    for b in backends:
        parts.append(_render_item(b))
    parts.append('</div></div>')

    # ── Release History ──
    if release_notes:
        parts.append(_sec("release-history", "Release History", len(release_notes), ""))
        for rel in release_notes:
            rel_json = E(json.dumps(rel))
            parts.append(f'<div class="release-card" data-release="{rel_json}">')
            parts.append(f'<h3>v{E(rel["version"])} <span class="click-hint">click for full notes</span></h3>')
            if rel.get("date"):
                parts.append(f'<div class="date">{E(rel["date"])}</div>')
            if rel.get("highlights"):
                parts.append('<ul>')
                for hl in rel["highlights"][:4]:
                    parts.append(f'<li><strong>{E(hl["title"])}</strong> — {E(_truncate(hl["summary"], 80))}</li>')
                remaining = len(rel["highlights"]) - 4
                if remaining > 0:
                    parts.append(f'<li style="color:var(--accent)">+ {remaining} more highlights…</li>')
                parts.append('</ul>')
            parts.append('</div>')
        parts.append('</div>')

    parts.append('<div id="no-results" class="no-results hidden-by-search">No items match your search.</div>')

    parts.append(f"""
</main>

<button id="back-to-top" class="back-to-top" aria-label="Back to top">↑</button>

<footer>
<div class="container">
  The Danual &middot; Dan's Dynamic-Manual for Hermes &middot; v{E(version)} &middot; {E(gen_display)}
</div>
</footer>

<div id="modal-overlay" class="modal-overlay">
  <div id="modal" class="modal"></div>
</div>

<script>{_js()}</script>
</body>
</html>""")

    return "\n".join(parts)


def _sec(anchor, title, count, intro):
    h = f'<div class="section" id="{anchor}">'
    h += f'<div class="section-header"><h2>{E(title)}</h2><span class="section-count">{count}</span></div>'
    if intro:
        h += f'<p class="section-intro">{E(intro)}</p>'
    return h


def main():
    log.info("═══ The Danual — Renderer ═══")
    if not MANIFEST_PATH.exists():
        log.error("No manifest.json found.")
        return

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    html_content = render(manifest)

    output_path = DOCS_DIR / "Hermes_Manual.html"
    _atomic_write(output_path, html_content)

    danual_path = DOCS_DIR / "Danual.html"
    # Recreate symlink if missing OR broken (is_symlink but target gone)
    if danual_path.is_symlink() and not danual_path.exists():
        try:
            danual_path.unlink()
        except OSError:
            pass
    if not danual_path.exists() and not danual_path.is_symlink():
        try:
            danual_path.symlink_to(output_path.name)
        except OSError:
            pass

    size_kb = output_path.stat().st_size / 1024
    log.info("Manual: %s (%.0f KB)", output_path, size_kb)
    log.info("View: file://%s", output_path)


if __name__ == "__main__":
    main()
