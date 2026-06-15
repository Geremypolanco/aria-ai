"""
Phase 10 tests — Design Division.

Covers:
  - DesignDivision: ui_design_task, ad_creative_task, brand_kit_task,
    video_script_task, figma_design_task, motion_design_task
  - design_stats: aggregate statistics
  - brand_assets: filtered list
  - recent_designs: list retrieval
  - design_system: full design system spec
  - DesignAsset: dataclass contract
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ── Shared mock helpers ────────────────────────────────────────────────────────

_RICH_CONTENT = (
    "Primary color: #3B82F6 (blue-500)\n"
    "Secondary: #10B981 (green-500)\n"
    "Font: Inter, weight 400/600/700\n"
    "Spacing base: 4px\n"
    "Border radius: 4px, 8px, 16px\n"
    "Colors: primary, secondary, accent, neutral\n"
    "Typography: heading, body, mono\n"
    "Shadows: sm, md, lg, xl\n"
    "Components: Button, Input, Card, Modal, Table\n"
    "Motion: fade-in 200ms, slide-up 300ms, spring 400ms\n"
    "Breakpoints: sm 640px, md 768px, lg 1024px, xl 1280px\n"
) * 15   # ~330 words — enough for quality score


def _mock_cache():
    c = MagicMock()
    c.get = AsyncMock(return_value=None)
    c.set = AsyncMock(return_value=True)
    return c


def _mock_ai(content: str = _RICH_CONTENT):
    ai = MagicMock()
    r = MagicMock()
    r.success = True
    r.content = content
    ai.complete = AsyncMock(return_value=r)
    return ai


def _mock_ai_failed():
    ai = MagicMock()
    r = MagicMock()
    r.success = False
    r.content = ""
    ai.complete = AsyncMock(return_value=r)
    return ai


# ══════════════════════════════════════════════════════════════════════════════
# DesignAsset dataclass
# ══════════════════════════════════════════════════════════════════════════════

class TestDesignAsset:
    """3 tests for the DesignAsset dataclass."""

    def test_designasset_defaults(self):
        from apps.workforce.design.design_division import DesignAsset
        a = DesignAsset()
        assert a.asset_id
        assert len(a.asset_id) == 8
        assert a.quality_score == 0.0
        assert a.specs == {}
        assert a.figma_url is None

    def test_designasset_to_dict_has_all_keys(self):
        from apps.workforce.design.design_division import DesignAsset
        a = DesignAsset(asset_type="ui_component", title="My Component")
        d = a.to_dict()
        for key in ("asset_id", "asset_type", "agent_type", "title", "description",
                    "specs", "ai_prompt", "output_description", "figma_url",
                    "quality_score", "created_at"):
            assert key in d, f"Missing key: {key}"

    def test_designasset_to_dict_values_match(self):
        from apps.workforce.design.design_division import DesignAsset
        a = DesignAsset(title="Ad Creative", asset_type="ad_creative", quality_score=0.8)
        d = a.to_dict()
        assert d["title"] == "Ad Creative"
        assert d["asset_type"] == "ad_creative"
        assert d["quality_score"] == 0.8


# ══════════════════════════════════════════════════════════════════════════════
# DesignDivision — ui_design_task
# ══════════════════════════════════════════════════════════════════════════════

class TestUIDesignTask:
    """4 tests for ui_design_task."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        import apps.workforce.design.design_division as m
        m._instance = None
        with patch("apps.workforce.design.design_division.get_cache", return_value=_mock_cache()), \
             patch("apps.workforce.design.design_division.get_ai_client", return_value=_mock_ai()):
            yield
        m._instance = None

    async def test_ui_design_task_returns_design_asset(self):
        from apps.workforce.design.design_division import DesignAsset, DesignDivision
        div = DesignDivision()
        asset = await div.ui_design_task("Dashboard Layout", {"grid": "12col"})
        assert isinstance(asset, DesignAsset)
        assert asset.asset_id

    async def test_ui_design_task_output_description_non_empty(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        asset = await div.ui_design_task("Login Page", {"fields": ["email", "password"]})
        assert asset.output_description
        assert len(asset.output_description) > 0

    async def test_ui_design_task_quality_score_in_range(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        asset = await div.ui_design_task("Product Card", {"image": True, "cta": True})
        assert 0.0 <= asset.quality_score <= 1.0

    async def test_ui_design_task_correct_agent_type(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        asset = await div.ui_design_task("Nav Menu", {"links": 5}, platform="mobile")
        assert asset.agent_type == "uiux_designer"


# ══════════════════════════════════════════════════════════════════════════════
# DesignDivision — ad_creative_task
# ══════════════════════════════════════════════════════════════════════════════

class TestAdCreativeTask:
    """4 tests for ad_creative_task."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        import apps.workforce.design.design_division as m
        m._instance = None
        with patch("apps.workforce.design.design_division.get_cache", return_value=_mock_cache()), \
             patch("apps.workforce.design.design_division.get_ai_client", return_value=_mock_ai()):
            yield
        m._instance = None

    async def test_ad_creative_task_returns_design_asset(self):
        from apps.workforce.design.design_division import DesignAsset, DesignDivision
        div = DesignDivision()
        asset = await div.ad_creative_task("Summer Sale", "Sunglasses", "18-35 outdoors")
        assert isinstance(asset, DesignAsset)

    async def test_ad_creative_task_output_non_empty(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        asset = await div.ad_creative_task("Black Friday", "Shoes", "Millennials", "1200x628")
        assert asset.output_description

    async def test_ad_creative_task_asset_type(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        asset = await div.ad_creative_task("Campaign X", "Software", "B2B")
        assert asset.asset_type == "ad_creative"

    async def test_ad_creative_task_specs_stored(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        asset = await div.ad_creative_task("Promo", "Widget", "Gen Z", "1080x1920")
        assert "product" in asset.specs
        assert asset.specs["product"] == "Widget"


# ══════════════════════════════════════════════════════════════════════════════
# DesignDivision — brand_kit_task
# ══════════════════════════════════════════════════════════════════════════════

class TestBrandKitTask:
    """3 tests for brand_kit_task."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        import apps.workforce.design.design_division as m
        m._instance = None
        with patch("apps.workforce.design.design_division.get_cache", return_value=_mock_cache()), \
             patch("apps.workforce.design.design_division.get_ai_client", return_value=_mock_ai()):
            yield
        m._instance = None

    async def test_brand_kit_task_returns_design_asset(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        asset = await div.brand_kit_task("AcmeCo", "SaaS", {"style": "modern"})
        assert asset.asset_id
        assert asset.output_description

    async def test_brand_kit_task_asset_type(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        asset = await div.brand_kit_task("TechStart", "Fintech", {})
        assert asset.asset_type == "brand_kit"

    async def test_brand_kit_task_quality_score(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        asset = await div.brand_kit_task("GreenCo", "Sustainability", {"color": "green"})
        assert 0.0 <= asset.quality_score <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# DesignDivision — video_script_task
# ══════════════════════════════════════════════════════════════════════════════

class TestVideoScriptTask:
    """3 tests for video_script_task."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        import apps.workforce.design.design_division as m
        m._instance = None
        with patch("apps.workforce.design.design_division.get_cache", return_value=_mock_cache()), \
             patch("apps.workforce.design.design_division.get_ai_client", return_value=_mock_ai()):
            yield
        m._instance = None

    async def test_video_script_task_returns_design_asset(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        asset = await div.video_script_task("Product Demo", "AI software tour", 60, "youtube")
        assert asset.asset_id
        assert asset.output_description

    async def test_video_script_task_asset_type(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        asset = await div.video_script_task("Viral Hook", "10 tips", 30, "tiktok")
        assert asset.asset_type == "video_script"

    async def test_video_script_task_specs_include_platform(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        asset = await div.video_script_task("Instagram Reel", "Brand story", 15, "instagram")
        assert asset.specs.get("platform") == "instagram"


# ══════════════════════════════════════════════════════════════════════════════
# DesignDivision — figma_design_task
# ══════════════════════════════════════════════════════════════════════════════

class TestFigmaDesignTask:
    """3 tests for figma_design_task."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        import apps.workforce.design.design_division as m
        m._instance = None
        with patch("apps.workforce.design.design_division.get_cache", return_value=_mock_cache()), \
             patch("apps.workforce.design.design_division.get_ai_client", return_value=_mock_ai()):
            yield
        m._instance = None

    async def test_figma_design_task_returns_design_asset(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        asset = await div.figma_design_task("Button Component", {"variant": ["primary", "ghost"]})
        assert asset.asset_id
        assert asset.output_description

    async def test_figma_design_task_has_figma_url(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        asset = await div.figma_design_task("Input Field", {"type": "text"})
        assert asset.figma_url is not None
        assert "figma.com" in asset.figma_url

    async def test_figma_design_task_quality_score(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        asset = await div.figma_design_task("Modal Dialog", {"closeable": True})
        assert 0.0 <= asset.quality_score <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# DesignDivision — motion_design_task
# ══════════════════════════════════════════════════════════════════════════════

class TestMotionDesignTask:
    """3 tests for motion_design_task."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        import apps.workforce.design.design_division as m
        m._instance = None
        with patch("apps.workforce.design.design_division.get_cache", return_value=_mock_cache()), \
             patch("apps.workforce.design.design_division.get_ai_client", return_value=_mock_ai()):
            yield
        m._instance = None

    async def test_motion_design_task_returns_design_asset(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        asset = await div.motion_design_task("Hero Animation", {"elements": ["title", "cta"]})
        assert asset.asset_id
        assert asset.output_description

    async def test_motion_design_task_asset_type(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        asset = await div.motion_design_task("Page Transition", {"type": "slide"})
        assert asset.asset_type == "motion_design"

    async def test_motion_design_task_agent_type(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        asset = await div.motion_design_task("Scroll Animation", {"trigger": "viewport"})
        assert asset.agent_type == "motion_designer"


# ══════════════════════════════════════════════════════════════════════════════
# DesignDivision — stats and queries
# ══════════════════════════════════════════════════════════════════════════════

class TestDesignStats:
    """5 tests for design_stats, brand_assets, recent_designs."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        import apps.workforce.design.design_division as m
        m._instance = None
        with patch("apps.workforce.design.design_division.get_cache", return_value=_mock_cache()), \
             patch("apps.workforce.design.design_division.get_ai_client", return_value=_mock_ai()):
            yield
        m._instance = None

    async def test_design_stats_has_required_keys(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        await div.ui_design_task("Dashboard", {})
        stats = div.design_stats()
        assert "total_assets" in stats
        assert "by_type" in stats
        assert "avg_quality_score" in stats

    async def test_design_stats_counts_assets(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        await div.ui_design_task("A", {})
        await div.ad_creative_task("B", "Prod", "Audience")
        stats = div.design_stats()
        assert stats["total_assets"] == 2

    def test_design_stats_empty(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        stats = div.design_stats()
        assert stats["total_assets"] == 0
        assert stats["avg_quality_score"] == 0.0

    async def test_brand_assets_returns_brand_kits(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        await div.brand_kit_task("BrandX", "Tech", {})
        await div.ui_design_task("UI", {})   # not a brand_kit
        brand = div.brand_assets()
        assert isinstance(brand, list)
        assert len(brand) == 1
        assert brand[0]["asset_type"] == "brand_kit"

    async def test_recent_designs_returns_list(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        await div.video_script_task("Video", "Topic", 30, "tiktok")
        recent = div.recent_designs(limit=5)
        assert isinstance(recent, list)
        assert len(recent) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# DesignDivision — design_system
# ══════════════════════════════════════════════════════════════════════════════

class TestDesignSystem:
    """4 tests for design_system."""

    @pytest.fixture(autouse=True)
    def _patch(self):
        import apps.workforce.design.design_division as m
        m._instance = None
        with patch("apps.workforce.design.design_division.get_cache", return_value=_mock_cache()), \
             patch("apps.workforce.design.design_division.get_ai_client", return_value=_mock_ai()):
            yield
        m._instance = None

    async def test_design_system_returns_dict(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        ds = await div.design_system("AcmeCo")
        assert isinstance(ds, dict)

    async def test_design_system_has_colors_key(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        ds = await div.design_system("TechStart")
        assert "colors" in ds

    async def test_design_system_has_typography_key(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        ds = await div.design_system("BrandY")
        assert "typography" in ds

    async def test_design_system_brand_name_stored(self):
        from apps.workforce.design.design_division import DesignDivision
        div = DesignDivision()
        ds = await div.design_system("FutureCo")
        assert ds.get("brand_name") == "FutureCo"


# ══════════════════════════════════════════════════════════════════════════════
# Singleton
# ══════════════════════════════════════════════════════════════════════════════

class TestDesignSingleton:
    """2 tests for get_design_division singleton."""

    def test_singleton_returns_same_instance(self):
        import apps.workforce.design.design_division as m
        m._instance = None
        from apps.workforce.design.design_division import get_design_division
        a = get_design_division()
        b = get_design_division()
        assert a is b
        m._instance = None

    def test_singleton_is_design_division(self):
        import apps.workforce.design.design_division as m
        m._instance = None
        from apps.workforce.design.design_division import (
            DesignDivision, get_design_division
        )
        div = get_design_division()
        assert isinstance(div, DesignDivision)
        m._instance = None
