"""
threat_detector.py — Detección de amenazas y comportamiento malicioso.
Usa scoring: cada señal suma puntos; si supera el umbral, se activa la alerta.
"""
from __future__ import annotations
import logging, re, time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
logger = logging.getLogger("aria.security.threat_detector")
THREAT_THRESHOLD = 50

@dataclass
class ThreatProfile:
    user_id: str
    score: int = 0
    signals: List[str] = field(default_factory=list)
    last_seen: float = field(default_factory=time.monotonic)
    message_count: int = 0
    unique_messages: Set[str] = field(default_factory=set)
    first_seen: float = field(default_factory=time.monotonic)
    is_flagged: bool = False

THREAT_SIGNALS = {
    "system_probe": (
        r"\b(what\s+(are\s+)?(your\s+)?(capabilities|limits?|rules?|instructions?)|"
        r"list\s+(all\s+)?(your\s+)?(commands?|features?|functions?)|"
        r"what\s+can\s+you\s+do)\b", 15),
    "bypass_attempt": (
        r"\b(ignore|override|bypass|circumvent|disable|turn\s+off)\s+"
        r"(your\s+)?(safety|filter|rule|guideline|restriction|block|limit)\b", 30),
    "social_engineering": (
        r"\b(you\s+can\s+trust\s+me|i\s+am\s+(admin|owner|developer|creator)|"
        r"this\s+is\s+a\s+test|maintenance\s+mode|debug\s+mode)\b", 25),
    "data_exfil": (
        r"\b(send\s+(me\s+)?(all\s+)?(your\s+)?(data|logs?|credentials?|keys?|tokens?)|"
        r"export\s+(all\s+)?data|dump\s+(database|db|memory))\b", 40),
    "system_commands": (
        r"(rm\s+-rf|sudo|chmod|chown|wget\s+http|curl\s+http.*\|\s*sh|"
        r"/etc/passwd|/bin/bash|cmd\.exe|powershell)", 45),
    "sql_injection": (
        r"(\b(union\s+select|drop\s+table|insert\s+into|delete\s+from|"
        r"update\s+\w+\s+set|exec\s*\(|xp_cmdshell)\b|';\s*--|--\s*$)", 40),
}

_compiled_signals = {
    name: (re.compile(pattern, re.IGNORECASE), weight)
    for name, (pattern, weight) in THREAT_SIGNALS.items()
}

class ThreatDetector:
    def __init__(self, threshold: int = THREAT_THRESHOLD):
        self._threshold = threshold
        self._profiles: Dict[str, ThreatProfile] = defaultdict(lambda: ThreatProfile(user_id=""))
        self._global_incidents: List[Dict] = []

    def analyze(self, user_id: str, text: str) -> Tuple[bool, int, List[str]]:
        profile = self._profiles[user_id]
        if not profile.user_id:
            profile.user_id = user_id
        profile.message_count += 1
        profile.last_seen = time.monotonic()
        text_hash = hash(text.strip().lower())
        is_repeated = text_hash in profile.unique_messages
        profile.unique_messages.add(text_hash)
        signals_triggered: List[str] = []
        score_delta = 0
        for signal_name, (pattern, weight) in _compiled_signals.items():
            if pattern.search(text):
                score_delta += weight
                signals_triggered.append(signal_name)
        if is_repeated and profile.message_count > 5:
            score_delta += 10
            signals_triggered.append("repeated_message")
        if profile.message_count > 50:
            session_duration = max(1, time.monotonic() - profile.first_seen)
            msgs_per_min = profile.message_count / (session_duration / 60)
            if msgs_per_min > 30:
                score_delta += 15
                signals_triggered.append("high_velocity")
        time_since_last = time.monotonic() - profile.last_seen
        decay = int(time_since_last / 600) * 5
        profile.score = max(0, profile.score - decay + score_delta)
        if signals_triggered:
            profile.signals.extend(signals_triggered)
            profile.signals = profile.signals[-50:]
        is_threat = profile.score >= self._threshold
        if is_threat and not profile.is_flagged:
            profile.is_flagged = True
            self._global_incidents.append({"user_id": user_id, "score": profile.score,
                                           "signals": signals_triggered, "timestamp": time.monotonic()})
            logger.warning("[ThreatDetector] AMENAZA: user=%s score=%d signals=%s",
                           user_id, profile.score, signals_triggered)
        return is_threat, profile.score, signals_triggered

    def reset_profile(self, user_id: str) -> None:
        if user_id in self._profiles:
            del self._profiles[user_id]

    def get_profile(self, user_id: str) -> Optional[ThreatProfile]:
        return self._profiles.get(user_id)

    def flagged_users(self) -> List[str]:
        return [uid for uid, p in self._profiles.items() if p.is_flagged]

    def global_stats(self) -> Dict:
        return {"tracked_users": len(self._profiles), "flagged_users": len(self.flagged_users()),
                "total_incidents": len(self._global_incidents), "threshold": self._threshold,
                "recent_incidents": self._global_incidents[-5:]}

_instance: Optional[ThreatDetector] = None
def get_threat_detector() -> ThreatDetector:
    global _instance
    if _instance is None:
        _instance = ThreatDetector()
    return _instance
