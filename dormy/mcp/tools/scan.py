"""dormy_scan_product — structured product profile from a URL (mock)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from dormy.mcp.mocks import SCAN_TEMPLATE

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


class ProductInfo(BaseModel):
    name: str
    category: str
    one_liner: str
    tech_stack: list[str]


class MarketInfo(BaseModel):
    tam_hint: str
    ideal_customer: str


class ScanResult(BaseModel):
    product: ProductInfo
    market: MarketInfo
    differentiators: list[str]
    risks: list[str]
    note: str = Field(description="Mock warning (remove in Week 3)")


def register(mcp: "FastMCP") -> None:
    @mcp.tool(
        description=(
            "Scan a product URL and return a structured profile: product / market / "
            "differentiators / risks. Useful as input to dormy_find_investors for "
            "sector matching. [Week 2 Step 1: returns mock — Playwright + vision lands Week 3.]"
        ),
    )
    def dormy_scan_product(
        url: str = Field(description="URL of the product landing page, GitHub repo, or pitch page"),
    ) -> ScanResult:
        data = SCAN_TEMPLATE
        return ScanResult(
            product=ProductInfo(**data["product"]),
            market=MarketInfo(**data["market"]),
            differentiators=data["differentiators"],
            risks=data["risks"],
            note=f"⚠️ MOCK DATA (ignoring input URL: {url}). Real scanner lands Week 3.",
        )
