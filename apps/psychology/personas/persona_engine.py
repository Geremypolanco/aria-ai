from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

_CACHE_KEY = "psychology:personas:v1"
_CACHE_TTL = 86400 * 365  # 365 days


class PersonaArchetype(str, Enum):
    ACHIEVER = "achiever"
    EXPLORER = "explorer"
    SOCIALIZER = "socializer"
    CREATOR = "creator"
    OPTIMIZER = "optimizer"
    SKEPTIC = "skeptic"
    IMPULSE_BUYER = "impulse_buyer"
    RESEARCHER = "researcher"


_ARCHETYPE_DEFAULTS: dict[str, dict] = {
    PersonaArchetype.ACHIEVER: {
        "primary_pain": "not reaching full potential",
        "primary_desire": "recognition and results",
        "content_preferences": ["case studies", "success stories", "metrics"],
        "buying_triggers": ["limited time", "exclusive access", "competitive advantage"],
        "objections": ["is this the best option?", "will it make me look good?"],
        "platforms": ["LinkedIn", "Twitter/X", "YouTube"],
        "age_range": "28-45",
        "income_range": "$60k-$150k",
    },
    PersonaArchetype.EXPLORER: {
        "primary_pain": "boredom and sameness",
        "primary_desire": "new experiences and discovery",
        "content_preferences": ["tutorials", "behind-the-scenes", "unique perspectives"],
        "buying_triggers": ["novelty", "discovery", "first-mover access"],
        "objections": ["is this actually new?", "I've tried everything"],
        "platforms": ["YouTube", "TikTok", "Reddit"],
        "age_range": "18-35",
        "income_range": "$30k-$80k",
    },
    PersonaArchetype.SOCIALIZER: {
        "primary_pain": "feeling disconnected or irrelevant",
        "primary_desire": "belonging and social status",
        "content_preferences": ["community highlights", "testimonials", "group stories"],
        "buying_triggers": ["social proof", "peer recommendations", "community membership"],
        "objections": ["do my friends use this?", "will I fit in?"],
        "platforms": ["Instagram", "Facebook", "TikTok"],
        "age_range": "18-40",
        "income_range": "$25k-$70k",
    },
    PersonaArchetype.CREATOR: {
        "primary_pain": "creative blocks and lack of tools",
        "primary_desire": "expressing ideas and building something lasting",
        "content_preferences": ["how-to guides", "creative showcases", "tool reviews"],
        "buying_triggers": ["creative potential", "professional quality", "unique features"],
        "objections": ["will it limit my creativity?", "is it worth the learning curve?"],
        "platforms": ["YouTube", "Instagram", "Pinterest"],
        "age_range": "22-40",
        "income_range": "$35k-$100k",
    },
    PersonaArchetype.OPTIMIZER: {
        "primary_pain": "inefficiency and wasted resources",
        "primary_desire": "maximum output with minimum input",
        "content_preferences": ["comparisons", "benchmarks", "data-driven reviews"],
        "buying_triggers": ["ROI proof", "time savings", "efficiency gains"],
        "objections": ["what's the actual ROI?", "can I measure results?"],
        "platforms": ["LinkedIn", "Twitter/X", "HackerNews"],
        "age_range": "25-45",
        "income_range": "$70k-$200k",
    },
    PersonaArchetype.SKEPTIC: {
        "primary_pain": "being misled or wasting money",
        "primary_desire": "certainty and trustworthy solutions",
        "content_preferences": ["third-party reviews", "detailed specs", "transparency reports"],
        "buying_triggers": ["money-back guarantee", "free trial", "independent validation"],
        "objections": ["how do I know this works?", "what's the catch?"],
        "platforms": ["Reddit", "Google", "YouTube"],
        "age_range": "30-55",
        "income_range": "$50k-$120k",
    },
    PersonaArchetype.IMPULSE_BUYER: {
        "primary_pain": "missing out on good deals",
        "primary_desire": "instant gratification and excitement",
        "content_preferences": ["flash sales", "limited offers", "unboxing content"],
        "buying_triggers": ["scarcity", "urgency", "discount codes"],
        "objections": ["is this the lowest price?", "do I need this now?"],
        "platforms": ["Instagram", "TikTok", "Facebook"],
        "age_range": "18-35",
        "income_range": "$20k-$60k",
    },
    PersonaArchetype.RESEARCHER: {
        "primary_pain": "making the wrong decision with incomplete information",
        "primary_desire": "complete understanding before committing",
        "content_preferences": ["in-depth articles", "whitepapers", "expert interviews"],
        "buying_triggers": ["comprehensive documentation", "expert endorsement", "peer-reviewed data"],
        "objections": ["I need more information", "let me compare all options first"],
        "platforms": ["Google", "LinkedIn", "YouTube"],
        "age_range": "28-50",
        "income_range": "$55k-$130k",
    },
}


@dataclass
class AudiencePersona:
    persona_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    archetype: PersonaArchetype = PersonaArchetype.ACHIEVER
    age_range: str = ""
    income_range: str = ""
    primary_pain: str = ""
    primary_desire: str = ""
    content_preferences: list[str] = field(default_factory=list)
    buying_triggers: list[str] = field(default_factory=list)
    objections: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "persona_id": self.persona_id,
            "name": self.name,
            "archetype": self.archetype.value,
            "age_range": self.age_range,
            "income_range": self.income_range,
            "primary_pain": self.primary_pain,
            "primary_desire": self.primary_desire,
            "content_preferences": self.content_preferences,
            "buying_triggers": self.buying_triggers,
            "objections": self.objections,
            "platforms": self.platforms,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AudiencePersona:
        return cls(
            persona_id=d.get("persona_id", str(uuid.uuid4())),
            name=d.get("name", ""),
            archetype=PersonaArchetype(d.get("archetype", PersonaArchetype.ACHIEVER.value)),
            age_range=d.get("age_range", ""),
            income_range=d.get("income_range", ""),
            primary_pain=d.get("primary_pain", ""),
            primary_desire=d.get("primary_desire", ""),
            content_preferences=d.get("content_preferences", []),
            buying_triggers=d.get("buying_triggers", []),
            objections=d.get("objections", []),
            platforms=d.get("platforms", []),
            created_at=d.get("created_at", time.time()),
        )


class PersonaEngine:
    def __init__(self) -> None:
        self._personas: dict[str, dict] = {}
        self._loaded = False

    async def _load(self) -> None:
        if self._loaded:
            return
        try:
            cache = get_cache()
            data = await cache.get(_CACHE_KEY)
            if data and isinstance(data, dict):
                self._personas = data
        except Exception:
            pass
        self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(_CACHE_KEY, self._personas, ttl_seconds=_CACHE_TTL)
        except Exception:
            pass

    async def create_persona(
        self,
        niche: str,
        archetype: PersonaArchetype,
        name: str = "",
    ) -> AudiencePersona:
        await self._load()

        defaults = _ARCHETYPE_DEFAULTS.get(archetype, _ARCHETYPE_DEFAULTS[PersonaArchetype.ACHIEVER])

        # Try to generate with AI; fall back to template defaults
        persona_name = name or f"{archetype.value.replace('_', ' ').title()} in {niche}"
        primary_pain = defaults["primary_pain"]
        primary_desire = defaults["primary_desire"]

        try:
            ai = get_ai_client()
            if ai:
                prompt = (
                    f"Create a marketing persona for the '{niche}' niche with archetype '{archetype.value}'. "
                    f"Reply with a JSON object with keys: name, primary_pain, primary_desire. Be specific to the niche."
                )
                result = await ai.complete(prompt, model=AIModel.FAST, max_tokens=200)
                if result:
                    import json, re
                    match = re.search(r'\{.*\}', result, re.DOTALL)
                    if match:
                        data = json.loads(match.group())
                        persona_name = name or data.get("name", persona_name)
                        primary_pain = data.get("primary_pain", primary_pain)
                        primary_desire = data.get("primary_desire", primary_desire)
        except Exception:
            pass

        persona = AudiencePersona(
            name=persona_name,
            archetype=archetype,
            age_range=defaults["age_range"],
            income_range=defaults["income_range"],
            primary_pain=primary_pain,
            primary_desire=primary_desire,
            content_preferences=list(defaults["content_preferences"]),
            buying_triggers=list(defaults["buying_triggers"]),
            objections=list(defaults["objections"]),
            platforms=list(defaults["platforms"]),
        )

        self._personas[persona.persona_id] = persona.to_dict()
        # Tag with niche in metadata — store niche in name if not already there
        self._personas[persona.persona_id]["niche"] = niche
        await self._save()
        return persona

    async def get_persona(self, persona_id: str) -> Optional[AudiencePersona]:
        await self._load()
        data = self._personas.get(persona_id)
        if data:
            return AudiencePersona.from_dict(data)
        return None

    async def list_personas(self, niche: str = "") -> list[AudiencePersona]:
        await self._load()
        personas = []
        for data in self._personas.values():
            if niche and data.get("niche", "") != niche:
                continue
            personas.append(AudiencePersona.from_dict(data))
        return personas

    async def match_content_to_persona(self, content: str, persona_id: str) -> dict:
        persona = await self.get_persona(persona_id)
        if not persona:
            return {
                "match_score": 0.0,
                "alignment_reasons": [],
                "mismatches": ["Persona not found"],
                "suggested_tweaks": [],
            }

        content_lower = content.lower()
        alignment = []
        mismatches = []
        tweaks = []
        score = 0.0

        # Check buying triggers
        for trigger in persona.buying_triggers:
            if any(word in content_lower for word in trigger.lower().split()):
                alignment.append(f"Addresses '{trigger}' buying trigger")
                score += 0.15
            else:
                mismatches.append(f"Missing '{trigger}' appeal")
                tweaks.append(f"Add a '{trigger}' element to resonate with this persona")

        # Check pain point
        if any(word in content_lower for word in persona.primary_pain.lower().split()):
            alignment.append(f"Speaks to primary pain: {persona.primary_pain}")
            score += 0.20

        # Check desire
        if any(word in content_lower for word in persona.primary_desire.lower().split()):
            alignment.append(f"Connects to desire: {persona.primary_desire}")
            score += 0.20

        score = min(1.0, score)

        return {
            "match_score": round(score, 4),
            "alignment_reasons": alignment[:5],
            "mismatches": mismatches[:3],
            "suggested_tweaks": tweaks[:3],
        }

    async def generate_niche_personas(
        self, niche: str, count: int = 3
    ) -> list[AudiencePersona]:
        archetypes = list(PersonaArchetype)[:count]
        personas = []
        for archetype in archetypes:
            p = await self.create_persona(niche=niche, archetype=archetype)
            personas.append(p)
        return personas

    def summary(self) -> dict:
        archetypes = list({
            d.get("archetype", "") for d in self._personas.values()
        })
        return {
            "total_personas": len(self._personas),
            "archetypes": archetypes,
        }


_engine_instance: Optional[PersonaEngine] = None


def get_persona_engine() -> PersonaEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = PersonaEngine()
    return _engine_instance
