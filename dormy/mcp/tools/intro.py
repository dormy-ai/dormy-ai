"""draft_intro — personalized outreach email (mock)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from dormy.mcp.mocks import INNER_CIRCLE_CONTACTS
from dormy.memory.hooks import from_mcp_call

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


class DraftIntroResult(BaseModel):
    contact_id: str
    contact_name: str
    subject: str
    body: str
    rationale: str = Field(description="Why this opening angle was chosen")
    suggested_channel: str
    note: str


_CONTACT_INDEX = {c["id"]: c for c in INNER_CIRCLE_CONTACTS}


def register(mcp: "FastMCP") -> None:
    @mcp.tool(
        description=(
            "Draft a personalized outreach email to a specific contact. For Inner Circle "
            "contacts, the draft uses their personal_notes + warm_intro_path to maximize "
            "reply rate. [Week 2 Step 1: returns mock — Claude Sonnet drafting lands Week 4.]"
        ),
    )
    def draft_intro(
        contact_id: str = Field(
            description="Contact id from find_investors (e.g. 'alex-chen')"
        ),
        angle: str | None = Field(
            default=None,
            description="Opening angle hint, e.g. 'recent portfolio', 'OSS contribution', "
                        "'warm intro via X'. Defaults to an auto-picked angle.",
        ),
    ) -> DraftIntroResult:
        contact = _CONTACT_INDEX.get(contact_id)

        if not contact:
            result = DraftIntroResult(
                contact_id=contact_id,
                contact_name="(unknown)",
                subject="(no draft — unknown contact)",
                body="Contact not found in mock Inner Circle. Call find_investors first to discover contact ids.",
                rationale="Invalid contact_id",
                suggested_channel="n/a",
                note="⚠️ MOCK: only the 5 dummy inner circle ids are valid. See find_investors results.",
            )
            from_mcp_call(
                "draft_intro",
                {"contact_id": contact_id, "angle": angle},
                result,
            )
            return result

        chosen_angle = angle or "recent portfolio"
        name_first = contact["name"].split()[0]

        subject = f"Quick note after your {contact.get('recent_activity', 'recent investment')[:35]}..."

        warm_intro_line = (
            f"(Sending this per {contact['warm_intro_path']})"
            if contact.get("warm_intro_path")
            else ""
        )

        body = (
            f"Hi {name_first},\n\n"
            f"I noticed you {contact.get('recent_activity', 'have been active in the space').lower()}. "
            f"I'm building Dormy — an AI fundraising copilot for technical founders — and "
            f"your thesis on {', '.join(contact['sectors'])} resonated.\n\n"
            f"Would a 15-min call work next week?\n\n"
            f"{warm_intro_line}\n\n"
            f"— Bei"
        )

        rationale = (
            f"Angle: {chosen_angle}. Lead with a specific reference to their "
            f"{contact.get('recent_activity', 'activity')}, then a one-line pitch tied to "
            f"their sector focus ({', '.join(contact['sectors'])}). "
        )
        if contact.get("warm_intro_path"):
            rationale += f"Surface the warm intro path to shortcut trust."

        result = DraftIntroResult(
            contact_id=contact_id,
            contact_name=contact["name"],
            subject=subject,
            body=body,
            rationale=rationale,
            suggested_channel=f"Email ({contact.get('email', 'n/a')})",
            note="⚠️ MOCK — Claude Sonnet 4.6 (text_output route) drafts land in Week 4.",
        )
        from_mcp_call(
            "draft_intro",
            {"contact_id": contact_id, "angle": angle},
            result,
        )
        return result
