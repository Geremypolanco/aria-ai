"""
pdf_generator.py — Genera PDFs estructurados usando fpdf2 (puro Python, sin deps de sistema).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("aria.pdf_generator")


class PDFGenerator:
    """Genera PDFs con título, secciones y contenido de texto."""

    def generate(
        self,
        title: str,
        content: str = "",
        sections: list[dict] | None = None,
        author: str = "ARIA AI",
    ) -> bytes:
        """
        Genera un PDF y devuelve los bytes.

        sections: lista de dicts con {"title": str, "body": str}
        content: texto plano si no hay secciones estructuradas
        """
        from fpdf import FPDF

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_creator(author)

        # Portada / Título
        pdf.set_font("Helvetica", "B", 22)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 12, title, align="C")
        pdf.ln(4)

        # Línea separadora
        pdf.set_draw_color(180, 180, 180)
        pdf.line(15, pdf.get_y(), 195, pdf.get_y())
        pdf.ln(6)

        if sections:
            for sec in sections:
                sec_title = sec.get("title", "")
                sec_body = sec.get("body", "")

                if sec_title:
                    pdf.set_font("Helvetica", "B", 14)
                    pdf.set_text_color(50, 80, 150)
                    pdf.multi_cell(0, 8, sec_title)
                    pdf.ln(2)

                if sec_body:
                    pdf.set_font("Helvetica", "", 11)
                    pdf.set_text_color(40, 40, 40)
                    # Split lines manually to handle \n in body text
                    for line in sec_body.split("\n"):
                        pdf.multi_cell(0, 6, line if line else " ")
                    pdf.ln(4)
        elif content:
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(40, 40, 40)
            for line in content.split("\n"):
                pdf.multi_cell(0, 6, line if line else " ")

        # Footer
        pdf.set_y(-20)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(150, 150, 150)
        pdf.cell(0, 10, f"Generado por {author}", align="C")

        return bytes(pdf.output())


async def generate_pdf(
    title: str,
    content: str = "",
    sections: list[dict] | None = None,
) -> dict[str, Any]:
    """Async wrapper — fpdf2 es síncrono pero rápido."""
    try:
        gen = PDFGenerator()
        pdf_bytes = gen.generate(title=title, content=content, sections=sections)
        return {
            "success": True,
            "pdf_bytes": pdf_bytes,
            "filename": f"{title[:40].replace(' ', '_')}.pdf",
            "size_kb": len(pdf_bytes) // 1024,
        }
    except Exception as exc:
        logger.error("[PDFGenerator] %s", exc, exc_info=True)
        return {"success": False, "error": str(exc)}
