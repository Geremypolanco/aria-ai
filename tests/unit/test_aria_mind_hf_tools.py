"""Regression test: 4 HuggingFaceSuite capabilities (remove_background,
classify_image, document_qa, create_product_content_pack) had complete,
working implementations in huggingface_suite.py but were never wired into
aria_mind.py's tool dispatcher — ARIA could never actually call them, no
matter what the user asked. This verifies the new "remove_background",
"classify_image", "document_qa" and "create_product_pack" dispatch entries
call the right HuggingFaceSuite methods and shape the result correctly.

Also covers a real bug found while wiring create_product_pack: the suite's
create_product_content_pack() used to truncate the generated image's base64
to 100 chars + "..." before returning it (`img.get("image_b64","")[:100] +
"..."`), which produces undecodable garbage — not a preview, just corrupted
data. It now returns the actual image bytes/b64 untouched.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.core.cognition.aria_mind import AriaMind

pytestmark = pytest.mark.asyncio


async def _run(tool: str, args: dict, hf_method: str, hf_return: dict, fetch_return: bytes = b"fakeimgbytes"):
    with (
        patch("apps.core.cognition.aria_mind._fetch_image_bytes", AsyncMock(return_value=fetch_return)),
        patch("apps.core.tools.huggingface_suite.HuggingFaceSuite") as mock_suite_cls,
    ):
        mock_suite = AsyncMock()
        setattr(mock_suite, hf_method, AsyncMock(return_value=hf_return))
        mock_suite_cls.return_value = mock_suite
        mind = AriaMind()
        obs, media = await mind._execute_tool(tool, args)
        return obs, media, mock_suite


async def test_remove_background_returns_image_bytes_as_media():
    obs, media, suite = await _run(
        "remove_background",
        {"url": "https://example.com/product.jpg"},
        "remove_background",
        {"success": True, "image_bytes": b"png-bytes", "format": "png"},
    )
    suite.remove_background.assert_awaited_once_with(b"fakeimgbytes")
    assert media == {"image_bytes": b"png-bytes"}
    assert "Fondo eliminado" in obs


async def test_remove_background_reports_error_without_media():
    obs, media, _ = await _run(
        "remove_background",
        {"url": "https://example.com/product.jpg"},
        "remove_background",
        {"success": False, "error": "Sin resultado del Space"},
    )
    assert media == {}
    assert "Sin resultado del Space" in obs


async def test_remove_background_requires_url():
    mind = AriaMind()
    obs, media = await mind._execute_tool("remove_background", {})
    assert media == {}
    assert "URL" in obs


async def test_classify_image_formats_top_and_secondary_labels():
    obs, media, suite = await _run(
        "classify_image",
        {"url": "https://example.com/cat.jpg"},
        "classify_image",
        {
            "success": True,
            "top_label": "tabby cat",
            "top_score": 0.9123,
            "all": [
                {"label": "tabby cat", "score": 0.9123},
                {"label": "tiger cat", "score": 0.05},
            ],
        },
    )
    suite.classify_image.assert_awaited_once_with(b"fakeimgbytes")
    assert media == {}
    assert "tabby cat" in obs
    assert "91.2%" in obs
    assert "tiger cat" in obs


async def test_document_qa_includes_confidence():
    obs, media, suite = await _run(
        "document_qa",
        {"url": "https://example.com/invoice.png", "question": "What is the total?"},
        "document_qa",
        {"success": True, "answer": "$120.00", "confidence": 0.87, "question": "What is the total?"},
    )
    suite.document_qa.assert_awaited_once_with(b"fakeimgbytes", "What is the total?")
    assert media == {}
    assert "$120.00" in obs
    assert "87%" in obs


async def test_document_qa_requires_url_and_question():
    mind = AriaMind()
    obs, media = await mind._execute_tool("document_qa", {"url": "https://example.com/x.png"})
    assert media == {}
    assert "pregunta" in obs


async def test_create_product_pack_wires_main_image_into_media():
    with patch("apps.core.tools.huggingface_suite.HuggingFaceSuite") as mock_suite_cls:
        mock_suite = AsyncMock()
        mock_suite.create_product_content_pack = AsyncMock(
            return_value={
                "success": True,
                "product_name": "Widget",
                "niche": "gadgets",
                "product_image": {"bytes": b"real-product-bytes", "b64": "aGVsbG8="},
                "social_image": {"bytes": b"real-social-bytes", "b64": "aGk="},
                "blog_thumbnail": {"bytes": None, "b64": None},
                "summary": "A great widget.",
                "niche_classification": "gadgets",
                "market_sentiment": "positive",
                "translations": {"en": {}, "fr": {}},
            }
        )
        mock_suite_cls.return_value = mock_suite

        mind = AriaMind()
        obs, media = await mind._execute_tool(
            "create_product_pack",
            {"product_name": "Widget", "product_description": "desc", "niche": "gadgets"},
        )

    # The main product image bytes are NOT truncated garbage — they're the
    # real generated bytes, wired straight into the media dict.
    assert media == {"image_bytes": b"real-product-bytes"}
    assert "Widget" in obs
    assert "A great widget." in obs
    assert "en, fr" in obs
    assert "social" in obs


async def test_create_product_content_pack_no_longer_truncates_image_b64():
    """Direct regression test on the suite method itself: the old code did
    img.get("image_b64", "")[:100] + "..." which corrupts the base64 payload
    (undecodable, and useless as a "preview" since it's not human-readable).
    """
    from apps.core.tools.huggingface_suite import HuggingFaceSuite

    long_b64 = "A" * 500
    long_bytes = b"x" * 500
    img_result = {"success": True, "image_bytes": long_bytes, "image_b64": long_b64}

    suite = HuggingFaceSuite()
    with (
        patch.object(suite, "generate_product_image", AsyncMock(return_value=img_result)),
        patch.object(suite, "generate_social_media_image", AsyncMock(return_value=img_result)),
        patch.object(suite, "generate_blog_thumbnail", AsyncMock(return_value=img_result)),
        patch.object(suite, "summarize", AsyncMock(return_value={"summary": "s"})),
        patch.object(suite, "classify_product_niche", AsyncMock(return_value={"best_label": "n"})),
        patch.object(suite, "analyze_sentiment", AsyncMock(return_value={"sentiment": "pos"})),
        patch.object(
            suite, "translate_product_listing", AsyncMock(return_value={"listings": {"en": {}}})
        ),
    ):
        result = await suite.create_product_content_pack("Widget", "desc", "gadgets")

    assert result["product_image"]["bytes"] == long_bytes
    assert result["product_image"]["b64"] == long_b64
    assert not result["product_image"]["b64"].endswith("...")
