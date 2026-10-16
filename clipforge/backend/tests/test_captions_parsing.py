from app.transcribe.captions import parse_json3, parse_vtt


def test_json3_auto_captions_word_timing():
    data = {
        "events": [
            {"tStartMs": 0, "dDurationMs": 5000, "id": 1},
            {"tStartMs": 1000, "dDurationMs": 3000, "segs": [
                {"utf8": "hello"}, {"utf8": " world", "tOffsetMs": 400}, {"utf8": " again", "tOffsetMs": 900}]},
            {"tStartMs": 2500, "dDurationMs": 10, "aAppend": 1, "segs": [{"utf8": "\n"}]},
            {"tStartMs": 3000, "dDurationMs": 2000, "segs": [{"utf8": "next"}, {"utf8": " line", "tOffsetMs": 300}]},
        ]
    }
    segs = parse_json3(data)
    assert [s.text for s in segs] == ["hello world again", "next line"]
    words = segs[0].words
    assert [w.text for w in words] == ["hello", "world", "again"]
    assert words[0].start == 1.0 and words[1].start == 1.4 and words[2].start == 1.9
    assert all(w.end > w.start for w in words)
    # event overlapping the next one is clamped
    assert segs[0].end <= 3.0 + 1e-6


def test_json3_manual_captions_no_offsets():
    data = {"events": [{"tStartMs": 500, "dDurationMs": 2000, "segs": [{"utf8": "A full &amp; proper sentence."}]}]}
    segs = parse_json3(data)
    assert segs[0].text == "A full & proper sentence."
    assert segs[0].start == 0.5 and segs[0].end == 2.5
    assert segs[0].words == []


def test_vtt_manual():
    vtt = """WEBVTT

00:00:01.000 --> 00:00:03.500
Hello <b>there</b>.

00:00:04.000 --> 00:00:06.000
Second cue
on two lines
"""
    segs = parse_vtt(vtt)
    assert [s.text for s in segs] == ["Hello there.", "Second cue on two lines"]
    assert segs[1].start == 4.0 and segs[1].end == 6.0


def test_vtt_youtube_auto_rolling():
    vtt = """WEBVTT
Kind: captions

00:00:00.320 --> 00:00:02.510 align:start position:0%
{SP}
so<00:00:00.640><c> today</c><00:00:01.040><c> we're</c><00:00:01.360><c> testing</c>

00:00:02.510 --> 00:00:02.520 align:start position:0%
so today we're testing
{SP}

00:00:02.520 --> 00:00:05.000 align:start position:0%
so today we're testing
captions<00:00:03.000><c> right</c><00:00:03.500><c> now</c>
""".replace("{SP}", " ")  # YouTube puts single-space lines inside cues
    segs = parse_vtt(vtt)
    texts = [s.text for s in segs]
    assert texts == ["so today we're testing", "captions right now"]
    assert segs[0].words[1].text == "today" and segs[0].words[1].start == 0.64
    assert segs[1].words[0].start == 2.52
