"""Sentence units, candidate windows, scoring, dedup and the detector (heuristic + mocked LLM)."""
import pytest

from app.analysis.candidates import generate_windows, window_bounds
from app.analysis.detector import detect_moments, fit_unit_range
from app.analysis.heuristic import HeuristicScorer
from app.analysis.llm import AnalysisError, LLMAnalyzer, LLMMoment, chunk_units, parse_moments
from app.analysis.scoring import WEIGHTS, blend, weighted_total
from app.analysis.selection import jaccard, content_words, select_diverse, temporal_iou
from app.analysis.sentences import build_units
from app.models import JobOptions, ScoreBreakdown, Segment, Transcript

from .conftest import make_transcript

LINES = [
    "Welcome back to the show.",
    "Here's the thing nobody tells you about saving money.",
    "It's not about earning more, it's about the small leaks.",
    "I remember when I checked my bank statement and found nine subscriptions I forgot about.",
    "Nine subscriptions!",
    "That's why I audit everything every month now.",
    "Anyway, let's talk about something else.",
    "Unpopular opinion: credit cards are not the enemy.",
    "No, I disagree, that's absolutely wrong.",
    "Hear me out, if you pay the full balance every month you earn rewards for free.",
    "But most people don't pay the full balance, that's the problem.",
    "So the answer is: use them only if you're disciplined.",
    "Okay.",
    "Um, so, yeah.",
    "That's all for today, thanks for listening, see you next week.",
]


@pytest.fixture
def units():
    return build_units(make_transcript(LINES))


# ---------------------------------------------------------------- scoring formula
def test_weights_match_spec():
    assert WEIGHTS == {"hook": 0.25, "emotion": 0.20, "clarity": 0.20, "payoff": 0.15, "pacing": 0.10, "shareability": 0.10}
    assert abs(sum(WEIGHTS.values()) - 1) < 1e-9


def test_weighted_total():
    b = ScoreBreakdown(hook=100, emotion=0, clarity=0, payoff=0, pacing=0, shareability=0)
    assert weighted_total(b) == 25.0
    b = ScoreBreakdown(hook=80, emotion=60, clarity=70, payoff=50, pacing=90, shareability=40)
    assert weighted_total(b) == pytest.approx(80 * .25 + 60 * .2 + 70 * .2 + 50 * .15 + 90 * .1 + 40 * .1, abs=0.05)


def test_blend():
    a = ScoreBreakdown(hook=100, emotion=100, clarity=100, payoff=100, pacing=100, shareability=100)
    b = ScoreBreakdown()
    out = blend(a, b, 0.7)
    assert out.hook == 70 and out.shareability == 70


# ---------------------------------------------------------------- units / windows
def test_units_split_on_sentences(units):
    assert len(units) == len(LINES)
    assert units[1].text.startswith("Here's the thing")
    assert all(u.terminal for u in units)


def test_units_without_punctuation_split_on_pauses():
    t = make_transcript(["this has no punctuation at all", "and neither does this one", "or this"], gap=0.8)
    for s in t.segments:
        s.text = s.text.lower()
    us = build_units(t)
    assert len(us) == 3


def test_units_handle_segment_without_words():
    t = Transcript(source="x", segments=[Segment(start=0, end=3, text="Hello there friend."), Segment(start=3.5, end=5, text="Bye now.")])
    us = build_units(t)
    assert [u.text for u in us] == ["Hello there friend.", "Bye now."]
    assert us[0].words[0].start == 0 and us[0].words[-1].end <= 3.0 + 1e-6


def test_windows_respect_limits_and_boundaries(units):
    ws = generate_windows(units, min_seconds=10, max_seconds=60)
    assert ws, "expected candidates"
    for w in ws:
        assert 10 <= w.duration <= 60
        # clip never starts after the first word of its first unit, nor ends before the last word of its last unit
        assert w.start <= units[w.first].start + 1e-6
        assert w.end >= units[w.last].end - 1e-6
        # and never cuts into neighbouring speech
        if w.first > 0:
            assert w.start >= units[w.first - 1].end - 1e-6
        if w.last + 1 < len(units):
            assert w.end <= units[w.last + 1].start + 1e-6


def test_windows_never_exceed_60_even_with_long_speech():
    long_lines = [" ".join(["word"] * 60) + "." for _ in range(6)]  # ~21 s per sentence
    us = build_units(make_transcript(long_lines))
    ws = generate_windows(us, min_seconds=15, max_seconds=60)
    assert all(w.duration <= 60 for w in ws)


def test_windows_do_not_span_long_silence():
    t = make_transcript(["First thought here is long enough to matter a lot okay.", "Second part continues the thought nicely."] * 3, gap=6.0)
    us = build_units(t)
    ws = generate_windows(us, min_seconds=3, max_seconds=60, max_internal_gap=4.0)
    for w in ws:
        assert all(us[k].gap_before <= 4.0 for k in range(w.first + 1, w.last + 1))


def test_window_bounds_padding_capped(units):
    s, e = window_bounds(units, 1, 3, 60)
    assert s < units[1].start and e > units[3].end
    assert e - s <= 60


# ---------------------------------------------------------------- heuristic ranking
def test_heuristic_prefers_hooky_complete_moment(units):
    scorer = HeuristicScorer(units)
    good = fit_unit_range(units, 1, 5, 5, 60, None)  # hook ... "That's why I audit"
    bad = fit_unit_range(units, 12, 14, 1, 60, None)  # "Okay. Um, so, yeah. That's all for today"
    g, b = scorer.score(good), scorer.score(bad)
    assert g.total > b.total + 15
    assert any("hook" in r for r in g.reasons["hook"])
    assert any("outro" in p or "filler" in p for p in b.penalties)


def test_heuristic_penalises_topic_change(units):
    scorer = HeuristicScorer(units)
    clean = scorer.score(fit_unit_range(units, 7, 11, 5, 60, None))
    stitched = scorer.score(fit_unit_range(units, 4, 11, 5, 60, None))
    assert clean.breakdown.clarity > stitched.breakdown.clarity
    assert any("topic" in p for p in stitched.penalties)


def test_content_type_debate(units):
    sw = HeuristicScorer(units).score(fit_unit_range(units, 7, 11, 5, 60, None))
    assert sw.content_type == "debate"


# ---------------------------------------------------------------- dedup
def test_temporal_iou_and_jaccard():
    assert temporal_iou((0, 10), (5, 15)) == pytest.approx(5 / 15)
    assert temporal_iou((0, 10), (10, 20)) == 0
    assert jaccard(content_words("saving money matters"), content_words("money saving tips")) > 0.3


def test_select_diverse_removes_overlaps_and_repeats():
    items = [
        ("a", 90, (0, 30), "credit cards rewards balance"),
        ("b", 85, (10, 40), "totally different words"),  # overlaps a
        ("c", 80, (50, 80), "credit cards rewards balance"),  # same idea as a
        ("d", 70, (100, 130), "subscriptions bank statement"),
        ("e", 20, (200, 230), "low score unrelated"),
    ]
    out = select_diverse(items, score=lambda x: x[1], span=lambda x: x[2], text=lambda x: x[3], max_items=5, min_score=35)
    assert [x[0] for x in out] == ["a", "d"]


def test_detect_moments_heuristic(units):
    warnings: list[str] = []
    clips, analyzer = detect_moments(units, options=JobOptions(min_clip_seconds=8), title="t", media_duration=None,
                                     warnings=warnings, use_llm=False)
    assert analyzer == "heuristic"
    assert clips and [c.rank for c in clips] == list(range(1, len(clips) + 1))
    assert all(clips[i].score >= clips[i + 1].score for i in range(len(clips) - 1))
    for c in clips:
        assert c.end - c.start <= 60
        assert c.hook in " ".join(LINES)  # verbatim
        assert c.transcript in " ".join(LINES)
        assert set(c.platforms) == {"youtube_shorts", "tiktok", "instagram_reels"}
    # no two clips overlap by more than 2 s
    for i, a in enumerate(clips):
        for b in clips[i + 1:]:
            assert min(a.end, b.end) - max(a.start, b.start) <= 2.0


# ---------------------------------------------------------------- LLM layer (mocked)
class FakeAnalyzer(LLMAnalyzer):
    name, model = "fake", "fake-1"

    def __init__(self, moments=None, error=None):
        self.moments, self.error, self.calls = moments or [], error, 0

    def find_moments(self, units, **kw):
        self.calls += 1
        if self.error:
            raise self.error
        return self.moments


def _m(s, e, quote="", hook=90):
    return LLMMoment(start_id=s, end_id=e, content_type="debate", hook_quote=quote,
                     scores=ScoreBreakdown(hook=hook, emotion=80, clarity=80, payoff=80, pacing=80, shareability=80),
                     explanation="why", selection_reason="because")


def test_detector_uses_llm_and_verifies_quotes(units):
    fake = FakeAnalyzer([
        _m(7, 11, quote="Unpopular opinion: credit cards are not the enemy."),
        _m(1, 5, quote="An invented quote that is not in the transcript"),
        _m(999, 1000),  # out of range ids get clamped, not crash
    ])
    clips, analyzer = detect_moments(units, options=JobOptions(min_clip_seconds=8), title="t", media_duration=None,
                                     warnings=[], analyzer=fake)
    assert analyzer == "fake:fake-1"
    by_start = {round(c.start): c for c in clips}
    hooks = [c.hook for c in clips]
    assert "Unpopular opinion: credit cards are not the enemy." in hooks
    assert "An invented quote that is not in the transcript" not in hooks
    assert units[1].text in hooks  # replaced by the verbatim first sentence
    assert all(c.end - c.start <= 60 for c in clips)
    assert by_start


def test_detector_falls_back_when_llm_fails(units):
    warnings: list[str] = []
    clips, analyzer = detect_moments(units, options=JobOptions(min_clip_seconds=8), title="t", media_duration=None,
                                     warnings=warnings, analyzer=FakeAnalyzer(error=AnalysisError("boom")))
    assert analyzer == "heuristic" and clips
    assert any("boom" in w for w in warnings)


def test_fit_unit_range_clamps_long_ranges():
    long_lines = [" ".join(["word"] * 40) + "." for _ in range(8)]  # ~14 s each
    us = build_units(make_transcript(long_lines))
    w = fit_unit_range(us, 0, 7, 15, 60, None)
    assert w and w.duration <= 60 and w.last < 7
    w2 = fit_unit_range(us, 3, 3, 20, 60, None)  # too short: extended
    assert w2 and w2.duration >= 20


def test_parse_moments_validates_and_cleans():
    payload = {"moments": [
        {"start_id": 1, "end_id": 4, "content_type": "nonsense", "hook_quote": "x",
         "scores": {"hook": 150, "emotion": -5, "clarity": 50, "payoff": 50, "pacing": 50, "shareability": 50},
         "explanation": "e", "selection_reason": "r",
         "platforms": {"tiktok": {"title": "T", "description": "D", "hashtags": ["fyp", "#Fun Times", "#fyp", "!!"]}}},
        {"start_id": "bad"},
    ]}
    ms = parse_moments(payload)
    assert len(ms) == 1
    m = ms[0]
    assert m.scores.hook == 100 and m.scores.emotion == 0
    assert m.content_type == "conversation"
    assert m.platforms["tiktok"].hashtags == ["#fyp", "#FunTimes"]


def test_chunking_overlaps(units):
    chunks = chunk_units(units, max_chars=300, overlap=2)
    assert len(chunks) > 1
    assert chunks[1][0].id <= chunks[0][-1].id  # overlap
    assert {u.id for c in chunks for u in c} == {u.id for u in units}
