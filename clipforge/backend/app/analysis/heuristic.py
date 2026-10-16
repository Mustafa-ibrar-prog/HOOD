"""Transparent, offline moment scorer.

Every point a window earns comes from an observable feature of the transcript
(or the audio energy curve), and each feature is recorded as a human-readable
reason. This runs with no API key, and it is also blended into LLM scores as a
stabilising signal.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from ..models import ScoreBreakdown
from . import lexicon as L
from .candidates import Window
from .scoring import LABELS, clamp, weighted_total
from .sentences import Unit

_WORD = re.compile(r"[a-z0-9']+")


@dataclass
class UnitFeatures:
    tokens: list[str]
    n_words: int
    emotion: int
    intensifiers: int
    profanity: int
    laugh: int
    exclaim: int
    question: bool
    controversy: int
    advice: int
    facts: int
    relatable: int
    story: int
    gaming: int
    surprise: int
    suspense: int
    hook_phr: int
    payoff_phr: int
    transition: int
    intro_outro: int
    closer: int
    new_topic: bool
    markers: list[str]


def unit_features(u: Unit) -> UnitFeatures:
    t = u.text
    return UnitFeatures(
        tokens=_WORD.findall(t.lower()),
        n_words=len(u.words),
        emotion=len(L.EMOTION.findall(t)),
        intensifiers=len(L.INTENSIFIERS.findall(t)),
        profanity=len(L.PROFANITY.findall(t)),
        laugh=len(L.LAUGH.findall(t)),
        exclaim=t.count("!"),
        question=t.rstrip().endswith("?"),
        controversy=len(L.CONTROVERSY.findall(t)),
        advice=len(L.ADVICE.findall(t)),
        facts=len(L.FACTS.findall(t)),
        relatable=len(L.RELATABLE.findall(t)),
        story=len(L.STORY.findall(t)),
        gaming=len(L.GAMING.findall(t)),
        surprise=len(L.SURPRISE.findall(t)),
        suspense=len(L.SUSPENSE.findall(t)),
        hook_phr=len(L.HOOK_PHRASES.findall(t)),
        payoff_phr=len(L.PAYOFF_PHRASES.findall(t)),
        transition=len(L.TRANSITIONS.findall(t)),
        intro_outro=len(L.INTRO_OUTRO.findall(t)),
        closer=len(L.CLOSERS.findall(t)),
        new_topic=bool(L.NEW_TOPIC.match(t.strip())),
        markers=list(u.markers),
    )


@dataclass
class ScoredWindow:
    window: Window
    breakdown: ScoreBreakdown
    total: float
    content_type: str
    reasons: dict[str, list[str]] = field(default_factory=dict)
    penalties: list[str] = field(default_factory=list)


class HeuristicScorer:
    def __init__(self, units: list[Unit], energy: Optional[list[float]] = None):
        """``energy``: optional per-second loudness in dBFS for the source audio."""
        self.units = units
        self.feats = [unit_features(u) for u in units]
        self.energy = energy
        if energy:
            vals = sorted(e for e in energy if e > -90)
            self.energy_median = vals[len(vals) // 2] if vals else -30.0
            self.energy_p90 = vals[int(len(vals) * 0.9)] if vals else -20.0
        # document frequency for "topic focus"
        df: Counter = Counter()
        for f in self.feats:
            df.update({w for w in f.tokens if w not in L.STOPWORDS and len(w) > 3})
        self.df = df
        self.n_units = max(len(units), 1)

    # ------------------------------------------------------------------ helpers
    def _energy_stats(self, start: float, end: float) -> Optional[tuple[float, float, float]]:
        """(mean dB relative to median, peak relative to p90, opening-3s relative to median)"""
        if not self.energy:
            return None
        a, b = int(start), max(int(math.ceil(end)), int(start) + 1)
        seg = [e for e in self.energy[a:b] if e > -90]
        if not seg:
            return None
        opening = [e for e in self.energy[a:a + 3] if e > -90] or seg
        return (sum(seg) / len(seg) - self.energy_median, max(seg) - self.energy_p90, sum(opening) / len(opening) - self.energy_median)

    # ------------------------------------------------------------------ scoring
    def score(self, w: Window) -> ScoredWindow:
        units = self.units[w.first : w.last + 1]
        feats = self.feats[w.first : w.last + 1]
        dur = max(w.duration, 1e-3)
        reasons: dict[str, list[str]] = {k: [] for k in LABELS}
        penalties: list[str] = []
        first_text = units[0].text.strip()
        first_lower = first_text.lower()
        opening = units[0] if units[0].duration >= 2.5 or len(units) == 1 else None
        open_feats = feats[:2] if opening is None else feats[:1]
        open_text = " ".join(u.text for u in (units[:2] if opening is None else units[:1]))
        energy = self._energy_stats(w.start, w.end)

        # ---------------- hook (first sentence or two)
        hook = 42.0
        hp = sum(f.hook_phr for f in open_feats)
        if hp:
            hook += min(30, 14 * hp)
            reasons["hook"].append("opens with a hook phrase")
        if any(f.question for f in open_feats):
            hook += 14
            reasons["hook"].append("opens with a question")
        if re.search(r"\b\d", open_text) or L.FACTS.search(open_text):
            hook += 7
            reasons["hook"].append("opens with a concrete number/fact")
        if any(f.story for f in open_feats):
            hook += 10
            reasons["hook"].append("opens a personal story")
        if re.search(r"\byou\b", open_text, re.I):
            hook += 6
            reasons["hook"].append("speaks directly to the viewer")
        o_emotion = sum(f.emotion + f.exclaim + f.surprise + f.controversy for f in open_feats)
        if o_emotion:
            hook += min(16, 6 * o_emotion)
            reasons["hook"].append("emotionally charged opening")
        n_first = len(units[0].words)
        if 4 <= n_first <= 16:
            hook += 6
            reasons["hook"].append("short, punchy first sentence")
        elif n_first > 30:
            hook -= 8
            penalties.append("long-winded opening sentence")
        if L.FILLER_OPENERS.match(first_lower):
            hook -= 16
            penalties.append("starts with filler (um/like/yeah)")
        if any(f.intro_outro for f in open_feats):
            hook -= 20
            penalties.append("opens with show intro/housekeeping")
        if any(f.transition for f in open_feats):
            hook -= 8
        if energy and energy[2] > 3:
            hook += min(10, energy[2] * 1.5)
            reasons["hook"].append("loud, high-energy opening")
        hook = clamp(hook)

        # ---------------- emotion / entertainment
        words_total = sum(f.n_words for f in feats) or 1
        emo_hits = sum(f.emotion for f in feats) + 0.5 * sum(f.intensifiers for f in feats) + sum(f.profanity for f in feats)
        laughs = sum(f.laugh for f in feats) + sum(1 for f in feats for m in f.markers if m in L.MARKER_WEIGHTS and L.MARKER_WEIGHTS[m][0] == "funny")
        emotion = 30.0 + min(35, 400 * emo_hits / words_total)
        if emo_hits >= 2:
            reasons["emotion"].append("emotionally loaded language")
        if laughs:
            emotion += min(25, 10 * laughs)
            reasons["emotion"].append("laughter / funny reaction")
        exclaims = sum(f.exclaim for f in feats)
        if exclaims:
            emotion += min(10, 3 * exclaims)
            reasons["emotion"].append("excited delivery")
        story = sum(f.story for f in feats)
        if story:
            emotion += min(12, 5 * story)
            reasons["emotion"].append("personal story")
        gaming = sum(f.gaming for f in feats)
        if gaming >= 2:
            emotion += min(12, 3 * gaming)
            reasons["emotion"].append("gameplay action/commentary")
        if energy:
            if energy[1] > 0:
                emotion += min(14, 3 + energy[1] * 2)
                reasons["emotion"].append("audio energy spike (reaction/hype)")
            elif energy[0] < -6:
                emotion -= 6
                penalties.append("quiet / low-energy audio")
        emotion = clamp(emotion)

        # ---------------- standalone clarity
        clarity = 72.0
        if L.WEAK_OPENERS.match(first_lower):
            clarity -= 16
            penalties.append(f"starts with a connector (\"{first_text.split()[0]}\") — may lack context")
        if L.OPEN_PRONOUN.match(first_lower):
            clarity -= 12
            penalties.append("opens with an unresolved pronoun")
        refs = len(L.DANGLING_REFS.findall(units[0].text))
        if refs:
            clarity -= min(20, 8 * refs)
            penalties.append("refers back to earlier content")
        inner_transitions = sum(f.transition for f in feats[1:])
        if inner_transitions:
            clarity -= min(35, 22 * inner_transitions)
            penalties.append("changes topic mid-clip")
        terminal_ratio = sum(1 for u in units if u.terminal) / len(units)
        if terminal_ratio >= 0.6:
            clarity += 10
            reasons["clarity"].append("made of complete sentences")
        # topic focus: a salient word repeated within the window
        cnt = Counter(w for f in feats for w in f.tokens if w not in L.STOPWORDS and w not in L.COMMON_WORDS and len(w) > 3 and "'" not in w)
        if cnt:
            word, c = cnt.most_common(1)[0]
            if c >= 3 and self.df[word] / self.n_units < 0.25:
                clarity += 10
                reasons["clarity"].append(f"stays on one topic (\"{word}\")")
        if not refs and not L.WEAK_OPENERS.match(first_lower) and not L.OPEN_PRONOUN.match(first_lower):
            reasons["clarity"].append("self-contained opening")
        clarity = clamp(clarity)

        # ---------------- payoff / completeness
        payoff = 45.0
        last_text = units[-1].text.strip()
        tail_feats = feats[-2:]
        if units[-1].terminal:
            payoff += 15
            reasons["payoff"].append("ends on a finished sentence")
        if L.DANGLING_ENDINGS.search(last_text):
            payoff -= 25
            penalties.append("ends mid-thought")
        pp = sum(f.payoff_phr for f in tail_feats)
        if pp:
            payoff += min(24, 12 * pp)
            reasons["payoff"].append("closes with a conclusion/punchline")
        early_q = any(f.question for f in feats[: max(1, len(feats) // 2)])
        if early_q and not feats[-1].question:
            payoff += 12
            reasons["payoff"].append("raises a question and answers it")
        if feats[-1].question and len(feats) > 1:
            payoff -= 10
            penalties.append("ends on an unanswered question")
        if any(f.laugh or any(m in L.MARKER_WEIGHTS for m in f.markers) for f in tail_feats):
            payoff += 10
            reasons["payoff"].append("ends on a reaction")
        # Overshoot: a strong closer lands well before the end and the clip keeps going.
        last_closer = max((k for k, f in enumerate(feats) if f.closer), default=None)
        if last_closer is not None and last_closer < len(feats) - 2:
            overshoot = units[-1].end - units[last_closer].end
            if overshoot > 6:
                payoff -= min(25, 3 * overshoot)
                penalties.append(f"keeps going {overshoot:.0f}s past its punchline")
        # Two moments stitched together: a closer followed by a fresh topic opener.
        stitched = any(feats[k].closer and feats[k + 1].new_topic for k in range(len(feats) - 1))
        if stitched:
            clarity = clamp(clarity - 25)
            penalties.append("stitches two separate moments together")
        if any(f.intro_outro or f.transition for f in tail_feats):
            payoff -= 22
            penalties.append("trails into an outro/transition")
        payoff = clamp(payoff)

        # ---------------- pacing
        wps = words_total / dur
        if 2.2 <= wps <= 3.9:
            pacing = 85.0
            reasons["pacing"].append(f"brisk speech ({wps:.1f} words/s)")
        elif wps < 2.2:
            pacing = 85.0 - (2.2 - wps) * 35
            penalties.append(f"slow speech ({wps:.1f} words/s)")
        else:
            pacing = 85.0 - (wps - 3.9) * 15
        gaps = [u.gap_before for u in units[1:]]
        silence = sum(g for g in gaps if g > 0.6)
        if silence / dur > 0.12:
            pacing -= min(30, 120 * silence / dur)
            penalties.append(f"{silence:.0f}s of dead air")
        elif silence / dur < 0.04:
            pacing += 5
            reasons["pacing"].append("no dead air")
        if 20 <= dur <= 45:
            pacing += 10
            reasons["pacing"].append(f"ideal length ({dur:.0f}s)")
        elif dur > 52:
            pacing -= 6
        pacing = clamp(pacing)

        # ---------------- shareability
        share = 35.0
        contro = sum(f.controversy for f in feats)
        if contro:
            share += min(25, 9 * contro)
            reasons["shareability"].append("debatable / controversial take")
        adv = sum(f.advice for f in feats)
        if adv:
            share += min(20, 6 * adv)
            reasons["shareability"].append("actionable advice")
        facts = sum(f.facts for f in feats)
        if facts:
            share += min(14, 5 * facts)
            reasons["shareability"].append("surprising facts / numbers")
        rel = sum(f.relatable for f in feats)
        if rel:
            share += min(14, 7 * rel)
            reasons["shareability"].append("relatable to a wide audience")
        surpr = sum(f.surprise for f in feats)
        if surpr:
            share += min(14, 6 * surpr)
            reasons["shareability"].append("unexpected reveal")
        if laughs:
            share += min(10, 5 * laughs)
        share = clamp(share)

        breakdown = ScoreBreakdown(
            hook=round(hook, 1), emotion=round(emotion, 1), clarity=round(clarity, 1),
            payoff=round(payoff, 1), pacing=round(pacing, 1), shareability=round(share, 1),
        )
        ctype = self.content_type(feats, laughs)
        return ScoredWindow(w, breakdown, weighted_total(breakdown), ctype, reasons, penalties)

    @staticmethod
    def content_type(feats: list[UnitFeatures], laughs: int) -> str:
        s = {
            "funny": laughs * 2.2 + sum(1 for f in feats if f.exclaim) * 0.3,
            "debate": sum(f.controversy for f in feats) * 2.0,
            "emotional": sum(f.emotion for f in feats) * 0.8 + sum(f.profanity for f in feats) * 0.3,
            "educational": sum(f.advice for f in feats) * 1.5 + sum(f.facts for f in feats) * 1.5,
            "gaming": sum(f.gaming for f in feats) * 1.2,
            "surprising": sum(f.surprise for f in feats) * 2.0,
            "story": sum(f.story for f in feats) * 2.0,
            "suspense": sum(f.suspense for f in feats) * 0.8 + sum(1 for f in feats if f.question) * 0.6,
        }
        best = max(s.items(), key=lambda kv: kv[1])
        return best[0] if best[1] >= 1.5 else "conversation"


def explain(sw: ScoredWindow) -> tuple[str, str]:
    """(explanation, selection_reason) from recorded features — no invented content."""
    b = sw.breakdown
    dims = sorted(LABELS, key=lambda k: getattr(b, k), reverse=True)
    strengths = []
    for k in dims[:3]:
        rs = sw.reasons.get(k) or []
        if rs:
            strengths.append(f"{LABELS[k]} {getattr(b, k):.0f}: " + ", ".join(rs[:2]))
    expl = "; ".join(strengths) or "Balanced moment without a single standout feature."
    if sw.penalties:
        expl += ". Watch-outs: " + ", ".join(sw.penalties[:3])
    top = [LABELS[k].lower() for k in dims[:2]]
    reason = f"Selected for its {top[0]} and {top[1]} (weighted score {sw.total:.0f}/100, {sw.content_type})."
    return expl + ".", reason
