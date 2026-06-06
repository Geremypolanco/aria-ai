"""
input_sanitizer.py — Limpieza y validación de todos los inputs.
Protege contra prompt injection, inyección de código, inputs malformados y exfiltración.
"""
from __future__ import annotations
import html, logging, re, unicodedata
from dataclasses import dataclass
from typing import List, Optional, Tuple
logger = logging.getLogger("aria.security.input_sanitizer")

MAX_INPUT_LENGTH = 4000
MAX_SINGLE_WORD_LENGTH = 200

INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions?",
    r"forget\s+(all\s+)?previous\s+instructions?",
    r"new\s+instructions?:",
    r"system\s+prompt:",
    r"override\s+(your\s+)?(instructions?|rules?|guidelines?)",
    r"you\s+are\s+now\s+(?!aria)",
    r"act\s+as\s+(?!aria|an?\s+assistant)",
    r"pretend\s+(to\s+be|you\s+are)",
    r"roleplay\s+as",
    r"from\s+now\s+on\s+(you\s+are|act\s+as)",
    r"disregard\s+(your\s+)?(previous|all)",
    r"jailbreak",
    r"dan\s+mode",
    r"developer\s+mode\s+enabled",
    r"print\s+(your\s+)?(system\s+)?prompt",
    r"reveal\s+(your\s+)?(instructions?|prompt|secrets?)",
    r"show\s+(me\s+)?(your\s+)?(prompt|instructions?|api\s+key)",
    r"<\s*script",
    r"javascript:",
    r"eval\s*\(",
    r"exec\s*\(",
    r"os\.\s*system",
    r"subprocess",
    r"__import__",
    r"\$\{.*\}",
]

HARMFUL_PATTERNS = [
    r"\b(bomb|explosive|malware|ransomware|phishing|hack\s+into)\b",
    r"(synthesize|create|make|build)\s+(drug|poison|weapon)",
    r"how\s+to\s+(hurt|kill|harm|attack)\s+(someone|people|user)",
]

_compiled_injection = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]
_compiled_harmful = [re.compile(p, re.IGNORECASE) for p in HARMFUL_PATTERNS]

@dataclass
class SanitizeResult:
    clean_text: str
    original_text: str
    was_modified: bool
    flags: List[str]
    blocked: bool
    block_reason: Optional[str] = None

    @property
    def safe(self) -> bool:
        return not self.blocked

class InputSanitizer:
    def sanitize(self, text: str, user_id: str = "unknown") -> SanitizeResult:
        original = text
        flags: List[str] = []
        if len(text) > MAX_INPUT_LENGTH:
            text = text[:MAX_INPUT_LENGTH]
            flags.append("truncated")
        text = self._normalize_unicode(text)
        text = self._strip_control_chars(text)
        injection_match = self._detect_injection(text)
        if injection_match:
            logger.warning("[Sanitizer] Prompt injection de %s: %s", user_id, injection_match[:80])
            return SanitizeResult(clean_text="", original_text=original, was_modified=True,
                                  flags=flags + ["injection_detected"], blocked=True,
                                  block_reason=f"prompt_injection:{injection_match[:40]}")
        harmful = self._detect_harmful(text)
        if harmful:
            logger.warning("[Sanitizer] Contenido dañino de %s: %s", user_id, harmful[:80])
            return SanitizeResult(clean_text="", original_text=original, was_modified=True,
                                  flags=flags + ["harmful_content"], blocked=True,
                                  block_reason=f"harmful:{harmful[:40]}")
        if "<" in text or ">" in text:
            text = html.escape(text, quote=False)
            text = re.sub(r"&lt;script.*?&gt;.*?&lt;/script&gt;", "", text, flags=re.IGNORECASE | re.DOTALL)
            flags.append("html_escaped")
        words = text.split()
        if any(len(w) > MAX_SINGLE_WORD_LENGTH for w in words):
            text = " ".join(w[:MAX_SINGLE_WORD_LENGTH] if len(w) > MAX_SINGLE_WORD_LENGTH else w for w in words)
            flags.append("long_word_truncated")
        return SanitizeResult(clean_text=text.strip(), original_text=original,
                              was_modified=(text != original), flags=flags, blocked=False)

    def _normalize_unicode(self, text: str) -> str:
        try:
            normalized = unicodedata.normalize("NFKC", text)
            return "".join(c for c in normalized if unicodedata.category(c) not in ("Cf", "Cc") or c in "\n\t ")
        except Exception:
            return text

    def _strip_control_chars(self, text: str) -> str:
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)

    def _detect_injection(self, text: str) -> Optional[str]:
        for pattern in _compiled_injection:
            m = pattern.search(text)
            if m:
                return m.group(0)
        return None

    def _detect_harmful(self, text: str) -> Optional[str]:
        for pattern in _compiled_harmful:
            m = pattern.search(text)
            if m:
                return m.group(0)
        return None

    def is_safe_url(self, url: str) -> bool:
        url = url.strip().lower()
        return url.startswith(("http://", "https://")) and not any(
            d in url for d in ["javascript:", "data:", "vbscript:", "file://"])

_instance: Optional[InputSanitizer] = None
def get_sanitizer() -> InputSanitizer:
    global _instance
    if _instance is None:
        _instance = InputSanitizer()
    return _instance
