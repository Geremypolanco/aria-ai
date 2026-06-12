"""
  quality_checker.py — Control de calidad para artículos generados por IA.
  Verifica longitud, keywords, estructura de encabezados y keyword stuffing.
  """
  from __future__ import annotations

  import logging
  import re
  from dataclasses import dataclass, field
  from typing import Optional

  logger = logging.getLogger("aria.quality_checker")

  MIN_WORD_COUNT = 300
  MAX_KEYWORD_DENSITY = 0.05  # 5% máximo


  @dataclass
  class QualityReport:
      passed: bool
      score: int  # 0-100
      issues: list[str] = field(default_factory=list)
      warnings: list[str] = field(default_factory=list)


  class QualityChecker:
      """Verifica la calidad de artículos antes de publicarlos."""

      def check(self, article: dict, keywords: Optional[list[str]] = None) -> QualityReport:
          """
          Evalúa un artículo y retorna un QualityReport.
          article debe tener al menos: 'content' y opcionalmente 'title'.
          """
          content: str = article.get("content", "") or article.get("body", "") or ""
          title: str = article.get("title", "")
          issues: list[str] = []
          warnings: list[str] = []
          score = 100

          # 1. Longitud mínima
          words = content.split()
          word_count = len(words)
          if word_count < MIN_WORD_COUNT:
              issues.append(
                  f"Longitud insuficiente: {word_count} palabras (mínimo {MIN_WORD_COUNT})"
              )
              score -= 30

          # 2. Presencia de keywords objetivo
          if keywords:
              missing = []
              content_lower = content.lower()
              for kw in keywords:
                  if kw.lower() not in content_lower:
                      missing.append(kw)
              if missing:
                  issues.append(f"Keywords faltantes: {', '.join(missing)}")
                  score -= 20

          # 3. Estructura de encabezados (al menos un H2 o H3)
          has_headings = bool(re.search(r"^#{2,3}\s", content, re.MULTILINE))
          if not has_headings:
              warnings.append("Sin encabezados H2/H3 — estructura débil para SEO")
              score -= 10

          # 4. Alerta de keyword stuffing
          if keywords and word_count > 0:
              for kw in keywords:
                  count = len(re.findall(re.escape(kw.lower()), content.lower()))
                  density = count / word_count
                  if density > MAX_KEYWORD_DENSITY:
                      warnings.append(
                          f"Posible keyword stuffing: '{kw}' aparece {count} veces ({density:.1%})"
                      )
                      score -= 5

          score = max(0, score)
          passed = len(issues) == 0

          if passed:
              logger.info("[QualityChecker] '%s' — APROBADO (score %d)", title[:60], score)
          else:
              logger.warning(
                  "[QualityChecker] '%s' — RECHAZADO (score %d): %s",
                  title[:60],
                  score,
                  "; ".join(issues),
              )

          return QualityReport(passed=passed, score=score, issues=issues, warnings=warnings)


  _instance: Optional[QualityChecker] = None


  def get_quality_checker() -> QualityChecker:
      global _instance
      if _instance is None:
          _instance = QualityChecker()
      return _instance
  