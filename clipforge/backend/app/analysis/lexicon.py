"""Word lists and phrase patterns used by the transparent heuristic scorer.

These are deliberately readable so the scoring is explainable and tunable.
"""
from __future__ import annotations

import re

STOPWORDS = set(
    """a an the and or but so to of in on at for with from by is are was were be been being am i you he she it we they
    me him her us them my your his its our their this that these those there here what which who whom whose when where
    why how not no yes do does did done have has had just like really very can could would should will shall may might
    must about into over under again then than too also only own same such as if because while until out up down off
    all any both each few more most other some nor now get got gonna wanna kind sort thing things yeah okay ok um uh
    oh know mean right well actually literally basically lot go going went say said see one two""".split()
)


def rx(*phrases: str) -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(phrases) + r")\b", re.IGNORECASE)


HOOK_PHRASES = rx(
    r"you won'?t believe", r"nobody (?:talks|tells you|knows)", r"the truth (?:is|about)", r"here'?s (?:the thing|why|what|how)",
    r"the (?:biggest|worst|best|craziest|scariest|weirdest|number one|first|only) ", r"secret", r"mistakes?", r"never",
    r"stop (?:doing|using|buying)", r"why (?:you|do|does|is|are|did)", r"what if", r"imagine", r"i was wrong",
    r"let me tell you", r"this is (?:why|how|the|what)", r"the reason", r"did you know", r"most people", r"everyone thinks",
    r"wait", r"hold on", r"no way", r"oh my god", r"what happened", r"how to", r"i can'?t believe", r"i have to (?:tell|admit)",
    r"true story", r"unpopular opinion", r"hot take", r"plot twist", r"listen", r"guess what", r"the problem (?:is|with)",
    r"i quit", r"i got (?:fired|banned|arrested|scammed)", r"million", r"billion",
)
WEAK_OPENERS = rx(r"and", r"but", r"so", r"because", r"or", r"also", r"then", r"which", r"plus", r"anyway")
FILLER_OPENERS = rx(r"um+", r"uh+", r"like", r"you know", r"yeah", r"okay", r"ok", r"right", r"mm+", r"hmm+", r"i mean")
DANGLING_REFS = rx(r"as i said", r"like i (?:said|mentioned)", r"as we discussed", r"earlier", r"that guy", r"this one",
                   r"the other one", r"he said", r"she said", r"they said", r"going back to")
OPEN_PRONOUN = re.compile(r"^(?:he|she|they|it|this|that|those|these|him|her|them)\b", re.IGNORECASE)

EMOTION = rx(
    r"love", r"hate", r"scared", r"terrified", r"terrifying", r"cried", r"crying", r"tears", r"amazing", r"insane", r"crazy",
    r"angry", r"furious", r"heartbreaking", r"heartbroken", r"beautiful", r"shocked", r"shocking", r"hilarious", r"funny",
    r"incredible", r"unbelievable", r"devastated", r"proud", r"embarrass\w*", r"awkward", r"worst", r"best", r"wow", r"omg",
    r"oh my god", r"holy", r"wild", r"nuts", r"brutal", r"painful", r"happiest", r"saddest", r"miss (?:her|him|them)",
    r"panic\w*", r"nightmare", r"wish(?:ed)?", r"regret\w*", r"changed my life", r"went quiet", r"scar(?:y|ed)", r"dream", r"ridiculous", r"disgusting", r"obsessed", r"hurt", r"lonely", r"grateful",
)
INTENSIFIERS = rx(r"so", r"really", r"literally", r"absolutely", r"totally", r"completely", r"extremely", r"super", r"insanely")
PROFANITY = rx(r"damn", r"hell", r"shit\w*", r"fuck\w*", r"crap", r"wtf", r"bullshit")
LAUGH = rx(r"haha\w*", r"hahaha\w*", r"lol", r"lmao", r"i'?m dying", r"that'?s hilarious", r"you'?re kidding", r"i'?m crying")

PAYOFF_PHRASES = rx(
    r"that'?s why", r"that'?s how", r"and that'?s", r"so the lesson", r"the lesson", r"the point is", r"turns out",
    r"it turned out", r"in the end", r"finally", r"which means", r"bottom line", r"and it worked", r"we won", r"i won",
    r"and that was it", r"never again", r"changed my life", r"the answer is", r"the key is", r"so yeah", r"and boom",
    r"that'?s the secret", r"that'?s what", r"moral of the story", r"lesson learned", r"trust me", r"and guess what",
)
# Strong closers: when one lands mid-clip, what follows is usually a new moment.
CLOSERS = rx(r"that'?s why", r"that'?s how", r"so the lesson", r"the lesson is", r"the point is", r"bottom line",
             r"that'?s the secret", r"moral of the story", r"lesson learned", r"changed my life", r"the answer is",
             r"and that was it", r"never again", r"in the end", r"turns out")
# Openers that typically start a new topic/story/segment.
NEW_TOPIC = re.compile(
    r"^(?:did you know|here'?s (?:the thing|how|why|what)|unpopular opinion|my (?:dad|mom|mother|father|wife|husband|"
    r"brother|sister|friend|boss)\b|when i was|one day|so (?:the )?(?:next|other) (?:thing|question)|let me tell you|"
    r"true story|the (?:first|second|next) (?:thing|question)|alright|okay so|anyway)",
    re.IGNORECASE,
)

DANGLING_ENDINGS = re.compile(r"(?:\b(?:and|but|so|because|or|the|a|an|to|of|with|that|which|like|um|uh)|,)$", re.IGNORECASE)

CONTROVERSY = rx(
    r"disagree", r"wrong", r"argue", r"argument", r"debate", r"controversial", r"unpopular opinion", r"overrated",
    r"underrated", r"that'?s not true", r"bullshit", r"no no", r"absolutely not", r"you'?re wrong", r"i don'?t (?:agree|buy)",
    r"hot take", r"scam", r"lie", r"lying", r"fake", r"should be illegal", r"nobody wants to hear",
)
ADVICE = rx(
    r"how to", r"tips?", r"steps?", r"you should", r"you need to", r"don'?t ever", r"mistakes?", r"learn\w*", r"the key",
    r"here'?s how", r"the trick", r"the secret", r"if you want", r"make sure", r"the best way", r"pro tip", r"hack",
    r"strategy", r"framework", r"rule",
)
FACTS = rx(r"\d+(?:\.\d+)?\s?(?:%|percent)", r"\w+ percent", r"survey", r"study", r"research", r"data", r"statistic\w*", r"scientists?", r"according to",
           r"million", r"billion", r"thousand", r"\$\d[\d,]*", r"years? ago", r"fact")
RELATABLE = rx(r"everyone", r"everybody", r"we all", r"all of us", r"be honest", r"admit it", r"nobody tells you",
               r"relatable", r"every single time", r"you know when", r"tell me (?:i'?m not|you)", r"raise your hand")
STORY = rx(r"when i was", r"i remember", r"my (?:mom|dad|mother|father|wife|husband|brother|sister|friend|son|daughter|grandma|grandpa|boss)",
           r"years ago", r"one day", r"passed away", r"hospital", r"story", r"growing up", r"the first time", r"i was \d+")
GAMING = rx(r"clutch", r"headshot", r"boss", r"level", r"gg", r"let'?s go+", r"ranked", r"squad", r"respawn", r"loot",
            r"snip\w*", r"kills?", r"one[- ]tap", r"speedrun", r"glitch", r"spawn", r"noob", r"pro", r"combo", r"ult\w*",
            r"no scope", r"victory royale", r"wipe", r"aggro", r"nerf\w*", r"buff\w*", r"gameplay", r"controller", r"lobby")
SURPRISE = rx(r"turns out", r"plot twist", r"secret", r"never knew", r"shocking", r"revealed", r"the truth", r"nobody knows",
              r"surpris\w*", r"no idea", r"out of nowhere", r"suddenly", r"i couldn'?t believe", r"mind ?blown", r"what the")
SUSPENSE = rx(r"wait", r"guess", r"what happens", r"and then", r"all of a sudden", r"you'?ll never", r"stay with me",
              r"here'?s where it gets", r"but then", r"until")

# Topic changes inside a clip mean it stitches two ideas together.
TRANSITIONS = rx(r"anyway", r"let'?s talk about", r"moving on", r"quick break", r"next question", r"speaking of",
                 r"let'?s get into it", r"before we (?:get into|start)", r"on another note", r"changing (?:the )?subject",
                 r"let'?s move on", r"that being said")
INTRO_OUTRO = rx(r"welcome (?:back|to)", r"that'?s all for today", r"see you (?:next|in the next)", r"thanks for (?:watching|listening)",
                 r"don'?t forget to (?:like|subscribe)", r"smash that", r"hit the bell", r"link in (?:the )?description",
                 r"this (?:video|episode) is sponsored", r"today'?s sponsor", r"subscribe")
COMMON_WORDS = set("""people first real matters thing things time times really actually want need think make good great
    would could about always never every something someone everyone anything nothing still even back much many little
    pretty maybe guess sure feel felt look looking come came take took give gave know knew said says tell told year years
    today right point work working""".split())

MARKER_WEIGHTS = {"laughter": ("funny", 3.0), "laughs": ("funny", 3.0), "laughing": ("funny", 3.0),
                  "applause": ("emotional", 2.0), "cheering": ("emotional", 2.0), "gasps": ("surprising", 2.0)}

CONTENT_TYPES = ["funny", "debate", "emotional", "educational", "gaming", "surprising", "story", "suspense"]
