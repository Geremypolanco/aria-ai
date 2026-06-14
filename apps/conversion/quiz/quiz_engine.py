"""
Quiz Engine — Interactive product quiz system for lead capture and segmentation.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from apps.core.memory.redis_client import get_cache
from apps.core.tools.ai_client import get_ai_client, AIModel

_QUIZ_KEY = "conversion:quizzes:v1"
_QUIZ_TTL = 86400 * 90  # 90 days


@dataclass
class QuizQuestion:
    question_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    text: str = ""
    options: list[str] = field(default_factory=list)
    question_type: str = "single"  # "single"|"multi"|"scale"
    tag: str = ""  # which persona/segment this reveals

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "text": self.text,
            "options": self.options,
            "question_type": self.question_type,
            "tag": self.tag,
        }


@dataclass
class QuizResult:
    result_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    answers: dict = field(default_factory=dict)
    segment: str = "beginner"  # "beginner"|"advanced"|"professional"|"budget"|"premium"|"impulse"|"researcher"
    archetype_scores: dict = field(default_factory=dict)
    recommended_products: list[str] = field(default_factory=list)
    lead_score: float = 0.0
    email: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "result_id": self.result_id,
            "session_id": self.session_id,
            "answers": self.answers,
            "segment": self.segment,
            "archetype_scores": self.archetype_scores,
            "recommended_products": self.recommended_products,
            "lead_score": self.lead_score,
            "email": self.email,
            "created_at": self.created_at,
        }


@dataclass
class ProductQuiz:
    quiz_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    niche: str = ""
    questions: list[QuizQuestion] = field(default_factory=list)
    intro_text: str = ""
    result_segments: dict = field(default_factory=dict)  # segment → {description, recommended_products, cta}

    def to_dict(self) -> dict:
        return {
            "quiz_id": self.quiz_id,
            "name": self.name,
            "niche": self.niche,
            "questions": [q.to_dict() for q in self.questions],
            "intro_text": self.intro_text,
            "result_segments": self.result_segments,
        }


def _template_quiz(niche: str, product_names: list[str]) -> list[QuizQuestion]:
    """Fallback template quiz when AI is unavailable."""
    return [
        QuizQuestion(
            text=f"What is your budget for {niche} products?",
            options=["Under $50", "$50-$150", "$150-$300", "$300+"],
            question_type="single",
            tag="budget",
        ),
        QuizQuestion(
            text=f"What is your experience level with {niche}?",
            options=["Complete beginner", "Some experience", "Intermediate", "Advanced/Professional"],
            question_type="single",
            tag="experience",
        ),
        QuizQuestion(
            text=f"What is your primary goal with {niche}?",
            options=["Learn the basics", "Improve results", "Optimize performance", "Achieve mastery"],
            question_type="single",
            tag="goal",
        ),
        QuizQuestion(
            text=f"How often do you use {niche} products?",
            options=["Rarely", "Monthly", "Weekly", "Daily"],
            question_type="single",
            tag="frequency",
        ),
        QuizQuestion(
            text=f"What is your biggest challenge with {niche}?",
            options=["Not knowing where to start", "Consistency", "Finding the right products", "Budget constraints"],
            question_type="single",
            tag="pain_point",
        ),
    ]


def _build_result_segments(product_names: list[str]) -> dict:
    """Build default result segments mapping."""
    products = product_names if product_names else ["starter pack", "pro bundle", "value kit", "premium collection"]
    return {
        "beginner": {
            "description": "You're just getting started — we've got the perfect entry-level solution for you.",
            "recommended_products": products[:1] if products else ["starter pack"],
            "cta": "Start Your Journey",
        },
        "advanced": {
            "description": "You have solid experience — time to take your results to the next level.",
            "recommended_products": products[1:2] if len(products) > 1 else [products[0]],
            "cta": "Level Up Now",
        },
        "professional": {
            "description": "You're a pro — you need professional-grade tools to match your skills.",
            "recommended_products": products[-1:] if products else ["pro bundle"],
            "cta": "Go Pro Today",
        },
        "budget": {
            "description": "We believe in getting maximum value. Here are our best budget-friendly options.",
            "recommended_products": products[:1] if products else ["value kit"],
            "cta": "Get Best Value",
        },
        "premium": {
            "description": "You deserve the best. Here are our top-tier premium offerings.",
            "recommended_products": products[-1:] if products else ["premium collection"],
            "cta": "Experience Premium",
        },
        "impulse": {
            "description": "You know what you want. Here's our most popular pick — order today!",
            "recommended_products": products[:1] if products else ["best seller"],
            "cta": "Order Now",
        },
        "researcher": {
            "description": "You like to make informed decisions. Here's our most reviewed product.",
            "recommended_products": products[1:2] if len(products) > 1 else products[:1],
            "cta": "See Full Details",
        },
    }


def _parse_ai_questions(ai_content: str, niche: str) -> list[QuizQuestion]:
    """Parse AI-generated quiz questions from formatted response."""
    questions: list[QuizQuestion] = []
    lines = ai_content.strip().split("\n")
    i = 0
    while i < len(lines) and len(questions) < 5:
        line = lines[i].strip()
        # Detect question line: starts with Q1:, 1., QUESTION:, or similar
        q_text = ""
        if line and (
            (len(line) > 2 and line[0].isdigit() and line[1] in (".", ")"))
            or line.upper().startswith("Q")
            or line.upper().startswith("QUESTION")
        ):
            # Extract question text
            for prefix in ("QUESTION:", "Q1:", "Q2:", "Q3:", "Q4:", "Q5:"):
                if line.upper().startswith(prefix):
                    q_text = line[len(prefix):].strip()
                    break
            if not q_text and line and line[0].isdigit():
                q_text = line[2:].strip() if len(line) > 2 else ""
            if not q_text:
                q_text = line

        if q_text:
            options: list[str] = []
            tag = "general"
            # Look ahead for options and tag
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                if next_line.upper().startswith("OPTIONS:") or next_line.upper().startswith("OPTION:"):
                    opts_str = next_line[next_line.index(":") + 1:].strip()
                    # Parse A) ... B) ... C) ... style
                    import re
                    opts = re.split(r"\s+[A-D]\)", " " + opts_str)
                    options = [o.strip() for o in opts if o.strip()]
                elif next_line.upper().startswith("TAG:"):
                    tag = next_line[4:].strip().lower()
                elif next_line and next_line[0] in ("A", "B", "C", "D") and len(next_line) > 1 and next_line[1] in (".", ")"):
                    options.append(next_line[2:].strip())
                elif next_line and next_line[0].isdigit() and next_line[1] in (".", ")"):
                    # Start of next question
                    break
                elif next_line.upper().startswith("Q") and any(
                    next_line.upper().startswith(p) for p in ("Q1:", "Q2:", "Q3:", "Q4:", "Q5:", "QUESTION")
                ):
                    break
                j += 1

            if not options:
                options = ["Option A", "Option B", "Option C", "Option D"]

            questions.append(QuizQuestion(
                text=q_text,
                options=options[:4],
                question_type="single",
                tag=tag,
            ))
            i = j
            continue
        i += 1

    return questions


def _determine_segment(answers: dict, questions: list[dict]) -> tuple[str, dict]:
    """Score answers to determine segment and compute archetype_scores."""
    tag_counts: dict[str, int] = {}
    # Build question lookup
    q_by_id = {q["question_id"]: q for q in questions}

    for q_id, answer in answers.items():
        q = q_by_id.get(q_id)
        if not q:
            continue
        tag = q.get("tag", "general")
        # Determine value based on answer position (later options = more advanced/premium)
        opts = q.get("options", [])
        ans_list = answer if isinstance(answer, list) else [answer]
        for ans in ans_list:
            if ans in opts:
                idx = opts.index(ans)
                if tag == "budget":
                    if idx >= 2:
                        tag_counts["premium"] = tag_counts.get("premium", 0) + 1
                    else:
                        tag_counts["budget"] = tag_counts.get("budget", 0) + 1
                elif tag == "experience":
                    if idx == 0:
                        tag_counts["beginner"] = tag_counts.get("beginner", 0) + 1
                    elif idx >= 3:
                        tag_counts["professional"] = tag_counts.get("professional", 0) + 1
                    else:
                        tag_counts["advanced"] = tag_counts.get("advanced", 0) + 1
                elif tag == "frequency":
                    if idx >= 3:
                        tag_counts["impulse"] = tag_counts.get("impulse", 0) + 1
                elif tag == "pain_point":
                    if idx == 3:
                        tag_counts["budget"] = tag_counts.get("budget", 0) + 1
                    elif idx == 2:
                        tag_counts["researcher"] = tag_counts.get("researcher", 0) + 1
                else:
                    tag_counts["beginner"] = tag_counts.get("beginner", 0) + 1

    # Determine dominant segment
    if not tag_counts:
        segment = "beginner"
    else:
        segment = max(tag_counts, key=lambda k: tag_counts[k])

    return segment, tag_counts


class QuizEngine:
    def __init__(self) -> None:
        self._quizzes: dict[str, dict] = {}
        self._results: list[dict] = []
        self._loaded = False
        self._ai = get_ai_client()

    async def _load(self) -> None:
        if not self._loaded:
            try:
                cache = get_cache()
                data = await cache.get(_QUIZ_KEY)
                if isinstance(data, dict):
                    self._quizzes = data.get("quizzes", {})
                    self._results = data.get("results", [])
            except Exception:
                pass
            self._loaded = True

    async def _save(self) -> None:
        try:
            cache = get_cache()
            await cache.set(
                _QUIZ_KEY,
                {"quizzes": self._quizzes, "results": self._results[-500:]},
                ttl_seconds=_QUIZ_TTL,
            )
        except Exception:
            pass

    async def create_quiz(self, niche: str, product_names: list[str] = []) -> ProductQuiz:
        await self._load()

        questions: list[QuizQuestion] = []

        try:
            if self._ai:
                product_list = ", ".join(product_names) if product_names else niche
                response = await self._ai.complete(
                    system=(
                        "You are a conversion optimization expert. "
                        "Create a 5-question product quiz to help customers find the right product. "
                        "Each question should reveal: budget range, experience level, primary goal, "
                        "frequency of use, or key pain point. "
                        "Format each question as:\n"
                        "Q1: [question text]\n"
                        "Options: A) ... B) ... C) ... D) ...\n"
                        "Tag: budget\n\n"
                        "Use tags: budget, experience, goal, frequency, pain_point"
                    ),
                    user=(
                        f"Create a 5-question product quiz for the niche: {niche}\n"
                        f"Products to recommend: {product_list}\n"
                        "Make it engaging and conversational."
                    ),
                    model=AIModel.CREATIVE,
                    max_tokens=800,
                )
                if response.success and response.content:
                    questions = _parse_ai_questions(response.content, niche)
        except Exception:
            pass

        if len(questions) < 5:
            questions = _template_quiz(niche, product_names)

        result_segments = _build_result_segments(product_names)

        quiz = ProductQuiz(
            name=f"{niche.title()} Product Finder Quiz",
            niche=niche,
            questions=questions[:5],
            intro_text=(
                f"Answer 5 quick questions and we'll find the perfect {niche} product for you. "
                "Takes less than 60 seconds!"
            ),
            result_segments=result_segments,
        )

        self._quizzes[quiz.quiz_id] = quiz.to_dict()
        await self._save()
        return quiz

    async def process_response(
        self,
        quiz_id: str,
        session_id: str,
        answers: dict,
        email: str = "",
    ) -> QuizResult:
        await self._load()

        quiz_data = self._quizzes.get(quiz_id, {})
        questions = quiz_data.get("questions", [])
        result_segments = quiz_data.get("result_segments", {})

        segment, archetype_scores = _determine_segment(answers, questions)

        # Calculate lead_score
        lead_score = 0.3  # base
        if email:
            lead_score += 0.3
        if segment == "premium":
            lead_score += 0.2
        # Multi-answer engagement
        multi_answers = sum(1 for v in answers.values() if isinstance(v, list) and len(v) > 1)
        if multi_answers > 0:
            lead_score += 0.2
        lead_score = min(1.0, lead_score)

        # Get recommended products from segment
        seg_data = result_segments.get(segment, {})
        recommended_products = seg_data.get("recommended_products", [])

        result = QuizResult(
            session_id=session_id,
            answers=answers,
            segment=segment,
            archetype_scores=archetype_scores,
            recommended_products=recommended_products,
            lead_score=lead_score,
            email=email,
        )

        self._results.append(result.to_dict())
        await self._save()
        return result

    async def get_quiz(self, quiz_id: str) -> Optional[dict]:
        await self._load()
        return self._quizzes.get(quiz_id)

    def quiz_analytics(self, quiz_id: str) -> dict:
        results = [r for r in self._results if r.get("session_id", "").startswith(quiz_id[:8]) or True]
        # Filter by quiz (approximation — we store all results together)
        total = len(results)
        if total == 0:
            return {
                "total_responses": 0,
                "segment_distribution": {},
                "avg_lead_score": 0.0,
                "email_capture_rate": 0.0,
                "top_recommended_products": [],
            }

        segment_dist: dict[str, int] = {}
        scores: list[float] = []
        emails_captured = 0
        product_counts: dict[str, int] = {}

        for r in results:
            seg = r.get("segment", "unknown")
            segment_dist[seg] = segment_dist.get(seg, 0) + 1
            scores.append(r.get("lead_score", 0.0))
            if r.get("email"):
                emails_captured += 1
            for p in r.get("recommended_products", []):
                product_counts[p] = product_counts.get(p, 0) + 1

        top_products = sorted(product_counts, key=lambda k: product_counts[k], reverse=True)[:5]

        return {
            "total_responses": total,
            "segment_distribution": segment_dist,
            "avg_lead_score": sum(scores) / len(scores) if scores else 0.0,
            "email_capture_rate": emails_captured / total if total > 0 else 0.0,
            "top_recommended_products": top_products,
        }

    def list_quizzes(self) -> list[dict]:
        return list(self._quizzes.values())


_quiz_engine_instance: Optional[QuizEngine] = None


def get_quiz_engine() -> QuizEngine:
    global _quiz_engine_instance
    if _quiz_engine_instance is None:
        _quiz_engine_instance = QuizEngine()
    return _quiz_engine_instance
