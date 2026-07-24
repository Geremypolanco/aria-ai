"""
quality_checker.py — Quality control for AI-generated articles.
Checks length, keywords, heading structure, and keyword stuffing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger("aria.quality_checker")

MIN_WORD_COUNT = 300
MAX_KEYWORD_DENSITY = 0.05  # 5% maximum


@dataclass
class QualityReport:
    passed: bool
    score: int  # 0-100
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class QualityChecker:
    """Checks the quality of articles before publishing them."""

    def check(self, article: dict, keywords: list[str] | None = None) -> QualityReport:
        """
        Evaluates an article and returns a QualityReport.
        article must have at least: 'content' and optionally 'title'.
        """
        content: str = article.get("content", "") or article.get("body", "") or ""
        title: str = article.get("title", "")
        issues: list[str] = []
        warnings: list[str] = []
        score = 100

        # 1. Minimum length
        words = content.split()
        word_count = len(words)
        if word_count < MIN_WORD_COUNT:
            issues.append(f"Insufficient length: {word_count} words (minimum {MIN_WORD_COUNT})")
            score -= 30

        # 2. Presence of target keywords
        if keywords:
            missing = []
            content_lower = content.lower()
            for kw in keywords:
                if kw.lower() not in content_lower:
                    missing.append(kw)
            if missing:
                issues.append(f"Missing keywords: {', '.join(missing)}")
                score -= 20

        # 3. Heading structure (at least one H2 or H3)
        has_headings = bool(re.search(r"^#{2,3}\s", content, re.MULTILINE))
        if not has_headings:
            warnings.append("No H2/H3 headings — weak structure for SEO")
            score -= 10

        # 4. Keyword stuffing alert
        if keywords and word_count > 0:
            for kw in keywords:
                count = len(re.findall(re.escape(kw.lower()), content.lower()))
                density = count / word_count
                if density > MAX_KEYWORD_DENSITY:
                    warnings.append(
                        f"Possible keyword stuffing: '{kw}' appears {count} times ({density:.1%})"
                    )
                    score -= 5

        score = max(0, score)
        passed = len(issues) == 0

        if passed:
            logger.info("[QualityChecker] '%s' — PASSED (score %d)", title[:60], score)
        else:
            logger.warning(
                "[QualityChecker] '%s' — REJECTED (score %d): %s",
                title[:60],
                score,
                "; ".join(issues),
            )

        return QualityReport(passed=passed, score=score, issues=issues, warnings=warnings)


_instance: QualityChecker | None = None


def get_quality_checker() -> QualityChecker:
    global _instance
    if _instance is None:
        _instance = QualityChecker()
    return _instance
