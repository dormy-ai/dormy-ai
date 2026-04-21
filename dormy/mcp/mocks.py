"""Mock data for MCP tools (Week 2 Step 1).

Replace each constant with real queries in Week 3+ when we wire up the
Supabase `contacts` / `knowledge_chunks` tables and MiroThinker.

The 5 contacts mirror real `Dormy/Network/Investors/*.md` files so the
mock/real transition is invisible to Claude Code clients.
"""

from __future__ import annotations

# Five Inner Circle contacts (subset of the 15 dummy seeds in dormy-knowledge).
INNER_CIRCLE_CONTACTS: list[dict] = [
    {
        "id": "alex-chen",
        "name": "Alex Chen",
        "firm": "Horizon Labs",
        "role": "vc",
        "tier": "inner",
        "sectors": ["ai-infra", "dev-tools"],
        "stages": ["pre-seed", "seed"],
        "email": "zhangbei510@gmail.com",
        "linkedin_url": "https://linkedin.com/in/alex-chen-dummy",
        "personal_notes": (
            "Fast DM responder (<2h). Asks about dev adoption numbers in first meeting. "
            "Strong opinions on OSS licensing — prefers Apache 2.0 over AGPL."
        ),
        "warm_intro_path": "Primary: Mark Chen (YC W22 classmate) → Alex.  Backup: OpenClaw founder network.",
        "recent_activity": "Led W&B-style seed 2026-01; co-led Modal-style Series A 2025-11",
        "red_flags": "Passes on pure consumer AI; won't back non-technical teams",
    },
    {
        "id": "maya-rodriguez",
        "name": "Maya Rodriguez",
        "firm": "Vertex Capital",
        "role": "vc",
        "tier": "inner",
        "sectors": ["ai-apps", "vertical-ai"],
        "stages": ["seed", "A"],
        "email": "beizhangbill@gmail.com",
        "linkedin_url": "https://linkedin.com/in/maya-rodriguez-dummy",
        "personal_notes": (
            "Decisive — often gives verdict in first meeting. "
            "Values domain expertise; asks 'why you specifically?' a lot."
        ),
        "warm_intro_path": "Primary: Jenny Liu (ex-colleague at Vertex). Backup: LinkedIn cold.",
        "recent_activity": "Led LegalCo seed 2026-02; participated in MedAI Series A 2026-01",
        "red_flags": "Avoid horizontal AI platforms; prefers narrow vertical focus",
    },
    {
        "id": "priya-patel",
        "name": "Priya Patel",
        "firm": "Bloom Partners",
        "role": "vc",
        "tier": "inner",
        "sectors": ["consumer", "d2c"],
        "stages": ["pre-seed", "seed"],
        "email": "zhangbei510@hotmail.com",
        "linkedin_url": "https://linkedin.com/in/priya-patel-dummy",
        "personal_notes": (
            "Very active on Twitter; discovers many deals there. "
            "Loves memeable brands and strong founder storytelling."
        ),
        "warm_intro_path": "Primary: Twitter DM with a portfolio founder's endorsement.",
        "recent_activity": "Led GlowCo pre-seed 2026-02; angel in BrandX 2025-12",
        "red_flags": "Skips B2B SaaS; wants consumer-first founders",
    },
    {
        "id": "elena-volkova",
        "name": "Elena Volkova",
        "firm": "Quantum Capital",
        "role": "vc",
        "tier": "inner",
        "sectors": ["enterprise-saas", "vertical-saas", "b2b"],
        "stages": ["A", "B"],
        "email": "zhangbei510@gmail.com",
        "linkedin_url": "https://linkedin.com/in/elena-volkova-dummy",
        "personal_notes": (
            "Hard bar: wants $1M+ ARR for Series A. Process-oriented. "
            "Expects cohort retention spreadsheet and deep sales funnel analysis."
        ),
        "warm_intro_path": "Primary: Tom Anderson (mutual angel) → Elena.",
        "recent_activity": "Led WorkflowCo Series A 2026-01; led SaaSify Series B 2025-10",
        "red_flags": "Under $1M ARR = pass unless truly novel category; avoid horizontal CRM",
    },
    {
        "id": "tom-anderson",
        "name": "Tom Anderson",
        "firm": "Independent (angel)",
        "role": "angel",
        "tier": "inner",
        "sectors": ["ai-infra", "dev-tools"],
        "stages": ["pre-seed", "seed"],
        "email": "zhangbei510@hotmail.com",
        "linkedin_url": "https://linkedin.com/in/tom-anderson-dummy",
        "personal_notes": (
            "Technical angel ($25-100k checks). Ex-CTO at fictional InfraCo. "
            "Super connected in dev-tools circle; often the first intro source for VCs."
        ),
        "warm_intro_path": "Primary: direct LinkedIn after a code contribution to one of his portfolio OSS.",
        "recent_activity": "12 angel checks in 2025 across infra/devtools",
        "red_flags": "Expects quarterly updates; won't sign follow-on unless metrics improved",
    },
]


# External VCs (not in Inner Circle) that are "actively deploying" — plausible-sounding
# made-up firms. Replace with startups.gallery / Tavily results in Week 3.
EXTERNAL_ACTIVE_VCS: list[dict] = [
    {
        "id": "foo-partners",
        "name": "Foo Partners",
        "firm": "Foo Partners",
        "role": "vc",
        "sectors": ["ai-infra", "dev-tools"],
        "stages": ["seed", "A"],
        "recent_activity": "Led 3 AI infra seeds in Q1 2026 (ModelHub, PromptDB, EvalCo)",
    },
    {
        "id": "northwind-ventures",
        "name": "Northwind Ventures",
        "firm": "Northwind Ventures",
        "role": "vc",
        "sectors": ["ai-apps", "vertical-ai", "b2b"],
        "stages": ["seed", "A"],
        "recent_activity": "Deployed $45M across 6 AI deals in past 90 days",
    },
    {
        "id": "southstar-capital",
        "name": "Southstar Capital",
        "firm": "Southstar Capital",
        "role": "vc",
        "sectors": ["fintech", "consumer"],
        "stages": ["pre-seed", "seed"],
        "recent_activity": "Led PayFlow pre-seed 2026-03, GlowCo seed 2026-02",
    },
]


# Template for `dormy_scan_product` mock return
SCAN_TEMPLATE: dict = {
    "product": {
        "name": "Dormy AI",
        "category": "AI agent infrastructure",
        "one_liner": "Fundraising copilot exposed as MCP + CLI",
        "tech_stack": ["Python", "Next.js", "Supabase Postgres", "pgvector", "MCP"],
    },
    "market": {
        "tam_hint": "Agent-native B2B dev tools — nascent but fast-growing",
        "ideal_customer": "Technical founders raising pre-seed/seed who use Claude Code or Cursor",
    },
    "differentiators": [
        "Vertical Fundraising IQ (not a generic gateway)",
        "Inner Circle × Active VC playbook (time-sensitive matching)",
        "MiroThinker deep research workflow integrated",
        "Proactive daily watchers → Email / Telegram",
    ],
    "risks": [
        "Dependent on nanobot-ai upstream release cadence",
        "MiroThinker deep research latency (1-5 min) → MCP UX tradeoff",
        "LinkedIn / NFX Signal intentionally excluded for compliance",
    ],
}


# Mock knowledge chunks for `dormy_memory_recall`
KNOWLEDGE_CHUNKS: list[dict] = [
    {
        "source": "fletch_pmm",
        "title": "3 things great B2B landing pages always do",
        "excerpt": (
            "Strong B2B landing pages pass the '5-second test': the visitor instantly grasps "
            "who it's for, what it does, and what makes it distinctive. Use customer language, not yours."
        ),
        "score": 0.89,
        "tags": ["gtm", "positioning", "landing-page"],
    },
    {
        "source": "not_boring",
        "title": "Why 'Why Now' matters more than 'Why Us'",
        "excerpt": (
            "Seed investors invest in timing first, team second. If your 'why now' is weak, "
            "even a great team won't close the round. Prepare three timing arguments, ranked by conviction."
        ),
        "score": 0.83,
        "tags": ["fundraising", "pitch"],
    },
    {
        "source": "lennys_newsletter",
        "title": "PLG → enterprise upsell playbook",
        "excerpt": (
            "When individual users adopt your product at work, the transition to team/enterprise "
            "contracts is gated by one question: who owns the budget? Map that buyer early."
        ),
        "score": 0.76,
        "tags": ["gtm", "plg", "enterprise"],
    },
]
