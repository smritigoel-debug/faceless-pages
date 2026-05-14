#!/usr/bin/env python3
"""
InvestwithIshan — Automated AI Influencer Pipeline
===================================================
Full pipeline: Claude (script) → pronunciation fix → ElevenLabs (voice) → Higgsfield (video).
The finance reel uses Marketing Studio UGC so Ishan looks naturally office-recorded, not AI.

Setup:
    pip install -r requirements.txt
    cp .env.example .env   # fill in your keys

Usage:
    python investwithishan.py                          # interactive menu
    python investwithishan.py --pillar finance         # generate finance batch
    python investwithishan.py --pillar biohack         # generate biohack batch
    python investwithishan.py --pillar books           # generate book summary batch
    python investwithishan.py --pillar psych           # generate psychology batch
    python investwithishan.py --all                    # generate all pillars
    python investwithishan.py --topic "SIP delay"      # one-shot: AI writes + generates
    python investwithishan.py --voice "your script"    # voice-only for a given script
    python investwithishan.py --review "your script"   # pronunciation review only
"""

import os
import re
import sys
import json
import time
import argparse
import requests
from pathlib import Path
from datetime import datetime

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import anthropic

# ─── CONFIG ──────────────────────────────────────────────────────────────────

HIGGSFIELD_BASE    = "https://mcp.higgsfield.ai"
ELEVENLABS_BASE    = "https://api.elevenlabs.io/v1"

HIGGSFIELD_API_KEY  = os.getenv("HIGGSFIELD_API_KEY", "")
ELEVENLABS_API_KEY  = os.getenv("ELEVENLABS_API_KEY", "")
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "")

ISHAN_AVATAR_ID  = os.getenv("ISHAN_AVATAR_ID",  "ab91de35-7b32-456e-a677-9d2ba023bb20")
ISHAN_SOURCE_JOB = os.getenv("ISHAN_SOURCE_JOB", "a64faa64-3ac3-4ce4-a434-8a6a2658d818")

OUT_DIR = Path("./output/investwithishan")
for sub in ("finance", "biohack", "books", "psych", "voice", "scripts"):
    (OUT_DIR / sub).mkdir(parents=True, exist_ok=True)

# ─── ISHAN VOICE SETTINGS ────────────────────────────────────────────────────

ISHAN_VOICE_SETTINGS = {
    "stability":         0.55,
    "similarity_boost":  0.75,
    "style":             0.20,
    "use_speaker_boost": True,
    "speed":             0.90,
}

# ─── CONTENT STRATEGY CONTEXT ────────────────────────────────────────────────
# Compact version fed to Claude when generating scripts.

ISHAN_CHARACTER = """
Character: Ishan — Indian male, late 20s, MBA, quiet luxury aesthetic.
Voice: calm, authoritative, neutral Mumbai/Delhi educated English. Speaks like the
smartest friend in the room who happens to know finance — warm but never hype.
Audience: 22–26, India-first, Instagram Reels.

Script writing rules (STRICT):
- Write spoken English only — no bullet points, no headers, no markdown
- Short sentences. Hard max 15 words per sentence.
- Pause markers: use comma or em dash (—) where Ishan would breathe
- Never use the ₹ symbol — write "rupees" instead
- Write all numbers as words: "twenty thousand" not "20,000"
- Write percentages as words: "twelve percent" not "12%"
- Write "crore" and "lakh" as words (not abbreviated)
- Never use exclamation marks — keeps the calm tone
- End with a quiet revelation or a question, never a shout-out CTA
- Max script length: 90 words for a 30s reel, 150 words for a 60s reel
"""

PILLAR_CONTEXTS = {
    "finance": """
Finance pillar context:
- Hook formats: "5 ways you can…", "How your X turns into Y", big life goals
- Key data points: SIP, compounding, term insurance, emergency fund, FD vs equity
- Reference books: The Psychology of Money, Let's Talk Money, I Will Teach You to Be Rich
- Hook library: "Most 22-year-olds don't know this.", "Here's the math nobody showed you.",
  "Your parents' advice is costing you money.", "The three-year delay that costs thirty-two lakh."
- Format: talking head reel, Marketing Studio UGC (looks naturally recorded in an office)
""",
    "biohack": """
Biohack pillar context:
- Series: "Your body on…", "Hack your…", "What nobody tells you about…"
- Visual-first content: no talking head — dark cinematic macro biology animations
- Key topics: cold exposure (dopamine plus two-fifty percent), circadian rhythm,
  intermittent fasting autophagy at hour sixteen, mitochondria energy crash, HRV, gut-brain axis
- Format: Cinema Studio 3.0 cinematic, bioluminescent visuals + ambient audio
""",
    "books": """
Book summary pillar context:
- Format: cinematic open-world landscape + narration audio (no talking head)
- Books: The Alchemist, Atomic Habits, Can't Hurt Me, Man's Search for Meaning,
  The Midnight Library, They Both Die at the End, Normal People
- Narration style: warm, measured — reads the key lesson or opening hook of the book
- Visual: Kling 3.0 Pro — fantasy/open-world landscape, no characters
""",
    "psych": """
Psychology pillar context:
- Format: abstract animated metaphor + ambient voiceover
- Top facts: Spotlight Effect, Dopamine anticipation, Baader-Meinhof, Mere Exposure,
  Decision Fatigue, Zeigarnik Effect, Imposter Syndrome, Dunning-Kruger, Confirmation Bias
- Visual model: Wan 2.7 audio-sync — dark particle system animations
- Each video = fact title card + calm voiceover explaining it + abstract visual metaphor
""",
}

# ─── SCRIPT LIBRARY (pre-written, used as fallback) ──────────────────────────

FINANCE_SCRIPTS = {
    "sip_delay": {
        "title": "3-year SIP delay",
        "hook": "Most people in their twenties are doing SIPs wrong. Not because they invested too little — but because they started too late. Here is what a three-year delay actually costs you. Let me show you the math.",
        "series": "B"
    },
    "twenty_k_sip": {
        "title": "₹20k → ₹2Cr compounding",
        "hook": "Twenty thousand a month, starting at twenty-two. By the time you are forty-two — that is two crore. Not a typo. Not a trick. Just compounding, doing its thing for twenty years while you lived your life. The only variable — you had to start.",
        "series": "B"
    },
    "five_ways_save": {
        "title": "5 ways to save ₹5,000/month",
        "hook": "Five ways you can save five thousand rupees a month without feeling broke. Number one: automate your SIP before the salary even hits your account. Out of sight, out of temptation. This one move changes everything.",
        "series": "A"
    },
    "car_sip": {
        "title": "Buy a car using SIP (no EMI)",
        "hook": "You want a car at twenty-six. Most people take an EMI and pay interest for five years. Here is a different move. Start an eight thousand rupee SIP today. In four years, you own the car outright. No EMI. No interest. Just patience.",
        "series": "B"
    },
    "fd_losing_money": {
        "title": "Your parents' FD is losing money",
        "hook": "FD rate: seven percent. Inflation: six-and-a-half percent. Real return: zero-point-five. The same one lakh rupees in an equity mutual fund over ten years — two-point-six lakh. Nobody taught you this. That is the problem.",
        "series": "B"
    },
    "first_job_moves": {
        "title": "5 money moves — first job",
        "hook": "Five money moves to make the day you get your first job. Number one: start a one thousand rupee SIP. Any amount — the habit is what matters. Number two: buy term insurance today, while you are young and healthy. The premium will never be this cheap again.",
        "series": "A"
    }
}

PSYCH_FACTS = {
    "dopamine_anticipation": {
        "title": "Dopamine is about wanting, not having",
        "script": "Dopamine is not about pleasure. It is about anticipation. It spikes when you are about to get something — not when you get it. The scroll, the notification buzz, the unopened message. That is the hit. The moment you open it — the dopamine is already gone.",
        "visual": "Abstract animation: a glowing humanoid figure reaches toward a golden orb in dark void. Brain lights up brilliantly on approach. Contact — the light dims. Particles scatter. Dark ambient, particle system, 9:16."
    },
    "spotlight_effect": {
        "title": "The Spotlight Effect",
        "script": "You think everyone notices your mistakes. Research shows they barely do. You are the main character in your own film — not anyone else's. They are too busy being the main character in theirs.",
        "visual": "Character stands on a stage under a spotlight. As crowd's attention wanders to their phones, the spotlight shrinks. Character realizes — nobody was really watching. Dark ambient, minimal, 9:16."
    },
    "zeigarnik_effect": {
        "title": "The Zeigarnik Effect",
        "script": "Your brain obsesses over unfinished tasks. Completed things get filed and forgotten. Incomplete things stay active — running in the background, pulling your attention. Netflix uses this on you every single night. One more episode is not a choice. It is your brain refusing to file an open loop.",
        "visual": "Abstract: completed tasks dissolve and disappear. Incomplete ones glow and pulse, multiplying. Brain overwhelmed with glowing incomplete loops. Dark, particle system, 9:16."
    },
    "imposter_syndrome": {
        "title": "Imposter Syndrome",
        "script": "Imposter syndrome hits hardest at the beginning of every new level. The people who feel it are usually the most qualified. The people who do not feel it often stopped growing. If you feel like you do not belong — that might be exactly where you need to be.",
        "visual": "Figure climbing stairs, their shadow cast behind looks much larger and more capable. At each new level, the gap between figure and shadow widens. Minimal, cinematic, dark bg, 9:16."
    },
    "confirmation_bias": {
        "title": "Confirmation Bias",
        "script": "Your brain filters out anything that contradicts what you already believe — automatically, invisibly, constantly. You are not changing your mind. You are collecting evidence for what you already think. The algorithm amplifies this. Your feed is not the world. It is a mirror.",
        "visual": "A diverse feed of information gradually narrows to one single perspective. Frames around contradicting info close off one by one. Abstract, dark, particle, 9:16."
    },
    "dunning_kruger": {
        "title": "The Dunning-Kruger Effect",
        "script": "The less you know about something, the more confident you feel. The more you know, the more aware you become of how much you do not know. Expertise looks like doubt. Beginners sound like experts. Experts sound like beginners.",
        "visual": "Confidence curve animation — peaks sharply at beginner stage, crashes on contact with depth, slowly climbs across a long plateau of mastery. Minimal graph aesthetic, dark bg, 9:16."
    }
}

BIOHACK_PROMPTS = {
    "cold_exposure": {
        "title": "Cold exposure + dopamine",
        "prompt": "Macro close-up animation of glowing bioluminescent neurons firing in a dark brain. Bright electric blue and purple synaptic connections lighting up in a cascade, particles of norepinephrine and dopamine flooding neural pathways. Cinematic slow motion, ultra-detailed cellular biology, dark background, premium science documentary aesthetic. Text: Cold shower. 3 minutes. Dopamine plus two-fifty percent.",
        "genre": "drama"
    },
    "circadian_rhythm": {
        "title": "Circadian rhythm animation",
        "prompt": "Animated circadian rhythm visualization. A sinusoidal wave of light and dark cycles. Cortisol shown as warm amber wave peaking at 7am. Melatonin as cool blue wave peaking at 2am. Body clock as central glowing mechanism. Dark background, minimal, cinematic. Text: Your body has an alarm. You keep snoozing it.",
        "genre": "drama"
    },
    "intermittent_fasting": {
        "title": "IF hour-by-hour cellular animation",
        "prompt": "Hour-by-hour cellular animation of intermittent fasting. At hour 12: fat burning begins, cells shown consuming lipid droplets. At hour 16: autophagy activated, cells dismantling and recycling damaged organelles, glowing blue. At hour 24: deep cellular repair, mitochondria multiplying. Dark bioluminescent aesthetic, cinematic slow-mo, premium biology documentary. Text: Hour 16 is where the magic starts.",
        "genre": "epic"
    },
    "mitochondria": {
        "title": "Mitochondria energy factory",
        "prompt": "Macro cinematic animation of mitochondria — the energy factory inside a cell. ATP molecules being produced in glowing amber chains. Cristae structures visible in hyper-detail. Dark background with warm amber and orange bioluminescence. Cinematic slow motion, premium nature documentary aesthetic. Text: Your 3pm crash is not about coffee. It is about this.",
        "genre": "drama"
    },
    "gut_brain_axis": {
        "title": "Gut-brain serotonin axis",
        "prompt": "Animated gut-brain axis visualization. The vagus nerve shown as a glowing pathway connecting stomach and brain. Serotonin molecules — shown as warm golden particles — produced in gut lining and traveling upward through the nerve. Brain lighting up in warm gold. Text: 90 percent of your serotonin is made here. Not in your brain. Dark ambient, bioluminescent, 9:16.",
        "genre": "drama"
    }
}

BOOK_LANDSCAPES = {
    "the_alchemist": {
        "title": "The Alchemist",
        "visual_prompt": "Cinematic open-world desert landscape at sunset. Slow aerial drift over vast golden sand dunes, ancient ruins glowing warm amber, mystical atmosphere. No characters. Warm golden hour light, dramatic sky with stars emerging, Zelda BOTW desert vibes. Hyper-cinematic, ultra-detailed. 9:16 vertical.",
        "narration": "There is one great truth on this planet. Whoever you are, or whatever it is that you do — when you really want something, it is because that desire originated in the soul of the universe. And when you want something, all the universe conspires in helping you to achieve it."
    },
    "atomic_habits": {
        "title": "Atomic Habits",
        "visual_prompt": "Cinematic timelapse of a small plant growing into a massive tree in a beautiful forest clearing. Then a wide aerial shot of a thriving civilization built from scratch. Fantasy game aesthetic, warm golden light, Minecraft timelapse energy but photorealistic. No characters. Epic and meditative. 9:16.",
        "narration": "You do not rise to the level of your goals. You fall to the level of your systems. Your goal is not the point. The system is. A one percent improvement every single day — by the end of a year, you are thirty-seven times better. Not two percent better. Thirty-seven times."
    },
    "midnight_library": {
        "title": "The Midnight Library",
        "visual_prompt": "Cinematic open-world exploration at dusk. Vast library visible through a misty forest — glowing warm light from infinite shelves of books through tall windows. Slow dreamy camera drift. Soft magical atmosphere, no characters, ethereal. Gris game aesthetic meets Studio Ghibli. 9:16.",
        "narration": "Between life and death there is a library. And within that library, the shelves go on forever. Every book provides a chance to try another life you could have lived. To see how things would be different if you had made other choices."
    },
    "cant_hurt_me": {
        "title": "Can't Hurt Me",
        "visual_prompt": "Cinematic action game environment — a lone warrior approaching an impossible mountain peak in a storm. Dark dramatic sky, lightning, brutal but beautiful. No character visible — just the path ahead, rocks, wind, scale of the climb. God of War / Dark Souls aesthetic. Epic, raw. 9:16.",
        "narration": "The most dangerous thing you can do is to feel comfortable. When you think you are done — you are only at forty percent of your actual capacity. Your mind will quit on you a thousand times before your body does. The forty percent rule. That is where most people stop. That is exactly where you have to start."
    },
    "man_search_meaning": {
        "title": "Man's Search for Meaning",
        "visual_prompt": "Slow cinematic journey through a vast, quiet open landscape. Dawn breaking over mountains. A single winding path stretching to the horizon. Contemplative, meditative, beautiful in its emptiness. Journey game aesthetic, soft warm light. No characters. 9:16.",
        "narration": "Everything can be taken from a person but one thing. The last of human freedoms — to choose one's attitude in any given set of circumstances. To choose one's own way. He who has a why to live can bear almost any how."
    }
}

# ─── PRONUNCIATION RULES ─────────────────────────────────────────────────────
# Applied before sending text to ElevenLabs.

_PRONUN_REPLACEMENTS = [
    # ₹ + number + crore/lakh must come FIRST (most specific)
    (r"₹\s*(\d[\d,]*(?:\.\d+)?)\s*[cC]r(?:ore)?",
     lambda m: _decimal_to_words(m.group(1).replace(",", "")) + " crore"),
    (r"₹\s*(\d[\d,]*(?:\.\d+)?)\s*[lL](?:akh)?",
     lambda m: _decimal_to_words(m.group(1).replace(",", "")) + " lakh"),
    # ₹ + plain number
    (r"₹\s*(\d[\d,]*(?:\.\d+)?)",
     lambda m: _decimal_to_words(m.group(1).replace(",", "")) + " rupees"),
    # INR
    (r"\bINR\b", "rupees"),
    # Percentages
    (r"(\d+(?:\.\d+)?)\s*%", lambda m: _decimal_to_words(m.group(1)) + " percent"),
    # Bare number + crore/lakh (no ₹)
    (r"\b(\d+(?:\.\d+)?)\s*[cC]r(?:ore)?",
     lambda m: _decimal_to_words(m.group(1)) + " crore"),
    (r"\b(\d+(?:\.\d+)?)\s*[lL](?:akh)?",
     lambda m: _decimal_to_words(m.group(1)) + " lakh"),
    # Comma-separated numbers like 20,000
    (r"\b(\d{1,3}(?:,\d{3})+)\b", lambda m: _num_to_words(m.group(1).replace(",", ""))),
    # Exclamation marks → period
    (r"!", "."),
    # Catch any remaining ₹
    (r"₹", "rupees "),
]


def _decimal_to_words(s: str) -> str:
    """Convert a decimal string like '2.6' to 'two-point-six'."""
    if "." in s:
        integer_part, decimal_part = s.split(".", 1)
        words_int = _num_to_words(integer_part) if integer_part else "zero"
        digit_words = [_single_digit(d) for d in decimal_part]
        return words_int + "-point-" + "-".join(digit_words)
    return _num_to_words(s)


def _single_digit(d: str) -> str:
    digits = ["zero","one","two","three","four","five","six","seven","eight","nine"]
    return digits[int(d)] if d.isdigit() else d


def _num_to_words(n: str) -> str:
    """Convert an integer string to English words (up to crores)."""
    try:
        num = int(n)
    except ValueError:
        return n

    if num == 0:
        return "zero"

    ones = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
            "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
            "seventeen", "eighteen", "nineteen"]
    tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

    def _below_hundred(n):
        if n < 20:
            return ones[n]
        return tens[n // 10] + ("-" + ones[n % 10] if n % 10 else "")

    def _below_thousand(n):
        if n < 100:
            return _below_hundred(n)
        h = ones[n // 100] + " hundred"
        rem = n % 100
        return h + (" " + _below_hundred(rem) if rem else "")

    if num < 1000:
        return _below_thousand(num)
    if num < 100_000:
        return _below_thousand(num // 1000) + " thousand" + (" " + _below_thousand(num % 1000) if num % 1000 else "")
    if num < 10_000_000:
        return _below_thousand(num // 100_000) + " lakh" + (" " + _below_thousand(num % 100_000) if num % 100_000 else "")
    return _below_thousand(num // 10_000_000) + " crore" + (" " + _num_to_words(str(num % 10_000_000)) if num % 10_000_000 else "")


def fix_pronunciation(text: str) -> str:
    """Apply rule-based pronunciation fixes for ElevenLabs."""
    for pattern, replacement in _PRONUN_REPLACEMENTS:
        if callable(replacement):
            text = re.sub(pattern, replacement, text)
        else:
            text = re.sub(pattern, replacement, text)
    # Collapse multiple spaces
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


# ─── CLAUDE API — SCRIPT GENERATION & REVIEW ─────────────────────────────────

def _claude_client() -> anthropic.Anthropic:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set. Add it to your .env file.")
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def generate_script(topic: str, pillar: str = "finance", duration: int = 30) -> dict:
    """
    Use Claude to write a full Ishan script for a given topic.
    Returns dict with keys: title, script, pronunciation_fixed_script, notes.
    """
    client = _claude_client()
    word_limit = 90 if duration <= 30 else 150

    system = f"""{ISHAN_CHARACTER}

{PILLAR_CONTEXTS.get(pillar, PILLAR_CONTEXTS['finance'])}

You are writing a script that will be:
1. Read aloud by a Text-to-Speech system (ElevenLabs), so it must be pure spoken English
2. Voiced as Ishan — calm, authoritative, Indian English
3. Delivered as a {duration}-second Instagram Reel ({word_limit} words max)

CRITICAL pronunciation rules for TTS:
- NEVER use ₹ symbol — always write "rupees"
- NEVER use digits — write all numbers as English words
- NEVER use % — write "percent"
- NEVER use exclamation marks
- Use em dashes (—) and commas for natural pause points
- Max 15 words per sentence
"""

    prompt = f"""Write a complete Ishan script for this topic: "{topic}"

Pillar: {pillar}
Duration: {duration} seconds (~{word_limit} words)

Return your response as JSON with these exact keys:
{{
  "title": "short title for this video",
  "hook": "first 2 sentences that grab attention (the opening hook)",
  "script": "full complete spoken script — pure spoken English, no symbols, no digits",
  "notes": "1-2 sentences on what makes this script work for the audience"
}}

Only return the JSON, nothing else."""

    message = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    # Strip markdown code fences if Claude wrapped it
    raw = re.sub(r"^```(?:json)?\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    result = json.loads(raw)
    # Apply pronunciation fixes on top of Claude's output
    result["pronunciation_fixed_script"] = fix_pronunciation(result["script"])
    return result


def review_pronunciation(script: str) -> dict:
    """
    Ask Claude to review a script for pronunciation issues before TTS.
    Returns dict: {issues: [...], corrected_script: str, confidence: str}
    """
    client = _claude_client()

    system = f"""{ISHAN_CHARACTER}

You are a pronunciation quality checker for an Indian English Text-to-Speech system (ElevenLabs).
Your job: find any text that ElevenLabs might mispronounce and fix it.

Common issues to catch:
- ₹ or $ or INR → should be written as "rupees" or "dollars"
- Digits like 20,000 → should be "twenty thousand"
- Percentages like 12% → "twelve percent"
- Exclamation marks → remove or replace with period
- Abbreviations like SIP, FD, EMI → usually fine, but check context
- Sentences longer than 15 words → suggest a split
- Missing natural pause markers (commas, em dashes)
- Any word that sounds unnatural in Indian English spoken cadence
"""

    prompt = f"""Review this Ishan script for pronunciation and TTS issues:

---
{script}
---

Return JSON with these keys:
{{
  "issues": ["list of specific issues found, or empty list if none"],
  "corrected_script": "the fully corrected script ready for ElevenLabs",
  "confidence": "high / medium / low — how confident the corrected script will sound right",
  "notes": "brief note on the main changes made"
}}

Only return JSON, nothing else."""

    message = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)


# ─── ELEVENLABS HELPERS ───────────────────────────────────────────────────────

def _el_headers():
    return {"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"}


def el_get_voices():
    r = requests.get(f"{ELEVENLABS_BASE}/voices", headers=_el_headers(), timeout=15)
    r.raise_for_status()
    return r.json().get("voices", [])


def el_find_indian_voice(voices):
    """Find the best Indian English male voice."""
    for v in voices:
        labels = v.get("labels", {})
        accent = labels.get("accent", "").lower()
        gender = labels.get("gender", "").lower()
        if "indian" in accent and "male" in gender:
            return v["voice_id"], v["name"]
    for v in voices:
        labels = v.get("labels", {})
        if "indian" in str(labels).lower():
            return v["voice_id"], v["name"]
    for v in voices:
        if v["name"] in ["Callum", "Adam", "Daniel", "Josh"]:
            return v["voice_id"], v["name"]
    return voices[0]["voice_id"], voices[0]["name"]


def el_generate_voice(text: str, voice_id: str, output_path: Path) -> Path:
    """Generate voice audio and save to output_path."""
    body = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": ISHAN_VOICE_SETTINGS
    }
    r = requests.post(
        f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}",
        headers={**_el_headers(), "Accept": "audio/mpeg"},
        json=body,
        timeout=60
    )
    r.raise_for_status()
    output_path.write_bytes(r.content)
    print(f"   Voice saved → {output_path}")
    return output_path


def generate_voice_with_review(script: str, label: str, with_review: bool = True) -> tuple[Path | None, dict | None]:
    """
    Full voice generation pipeline:
    1. Rule-based pronunciation fix
    2. Claude pronunciation review (if with_review=True)
    3. ElevenLabs TTS
    Returns (audio_path, review_result)
    """
    if not ELEVENLABS_API_KEY:
        print("   ELEVENLABS_API_KEY not set — skipping voice.")
        return None, None

    # Step 1: rule-based fix
    fixed = fix_pronunciation(script)
    print(f"   [pronunciation] rule-based fix applied")

    # Step 2: Claude review
    review = None
    if with_review and ANTHROPIC_API_KEY:
        print(f"   [pronunciation] Claude reviewing script…")
        try:
            review = review_pronunciation(fixed)
            issues = review.get("issues", [])
            if issues:
                print(f"   [pronunciation] {len(issues)} issue(s) found:")
                for iss in issues:
                    print(f"     • {iss}")
                fixed = review["corrected_script"]
                print(f"   [pronunciation] script corrected (confidence: {review.get('confidence','?')})")
            else:
                print(f"   [pronunciation] no issues found (confidence: {review.get('confidence','?')})")
        except Exception as e:
            print(f"   [pronunciation] Claude review failed: {e} — using rule-fixed version")

    # Step 3: ElevenLabs
    try:
        voices = el_get_voices()
        voice_id, voice_name = el_find_indian_voice(voices)
        print(f"   [voice] using {voice_name} ({voice_id})")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = OUT_DIR / "voice" / f"{label}_{ts}.mp3"
        el_generate_voice(fixed, voice_id, out)
        return out, review
    except Exception as e:
        print(f"   [voice] ElevenLabs failed: {e}")
        return None, review


# ─── HIGGSFIELD HELPERS ───────────────────────────────────────────────────────

def _hf_headers():
    if not HIGGSFIELD_API_KEY:
        print("   HIGGSFIELD_API_KEY not set.")
    return {"Authorization": f"Bearer {HIGGSFIELD_API_KEY}", "Content-Type": "application/json"}


def hf_generate_video(model: str, prompt: str, aspect_ratio="9:16",
                      duration=10, genre=None, medias=None, avatars=None,
                      mode=None, resolution="1080p", generate_audio=False) -> dict:
    payload = {
        "model":        model,
        "prompt":       prompt,
        "aspect_ratio": aspect_ratio,
        "duration":     duration,
        "resolution":   resolution,
    }
    if genre:          payload["genre"]          = genre
    if medias:         payload["medias"]         = medias
    if avatars:        payload["avatars"]        = avatars
    if mode:           payload["mode"]           = mode
    if generate_audio: payload["generate_audio"] = True

    r = requests.post(f"{HIGGSFIELD_BASE}/v1/generations",
                      headers=_hf_headers(), json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def hf_poll(job_id: str, interval=8, max_wait=300) -> dict:
    deadline = time.time() + max_wait
    while time.time() < deadline:
        r = requests.get(f"{HIGGSFIELD_BASE}/v1/generations/{job_id}",
                         headers=_hf_headers(), timeout=15)
        r.raise_for_status()
        data = r.json()
        status = data.get("status", "")
        if status == "completed":
            return data
        if status == "failed":
            raise RuntimeError(f"Job {job_id} failed: {data.get('error','unknown')}")
        print(f"   [{status}] waiting…")
        time.sleep(interval)
    raise TimeoutError(f"Job {job_id} timed out after {max_wait}s")


def download_file(url: str, dest: Path):
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    dest.write_bytes(r.content)
    print(f"   Downloaded → {dest}")


def wait_and_download(jobs: list, pillar: str):
    print(f"\n   Waiting for {len(jobs)} {pillar} job(s)…")
    for j in jobs:
        job_id = j.get("job_id")
        if not job_id:
            continue
        print(f"\n   [{j['title']}] polling {job_id}…")
        try:
            data = hf_poll(job_id)
            results = data.get("results", []) or data.get("outputs", [])
            for i, res in enumerate(results):
                url = res.get("url") or res.get("video_url")
                if url:
                    fname = OUT_DIR / pillar / f"{j['key']}_{i+1}.mp4"
                    download_file(url, fname)
        except Exception as e:
            print(f"   Error: {e}")


# ─── VIDEO PROMPT BUILDER: HUMAN-RECORDED UGC ────────────────────────────────
# For Finance reels, we want Marketing Studio UGC — Ishan avatar speaking to camera
# in a way that looks naturally recorded by a human in an office, not AI-generated.

def build_ugc_prompt(hook: str) -> str:
    """
    Build a Marketing Studio prompt that makes the reel look human-recorded.
    Key techniques: natural framing, ambient office feel, slight imperfections.
    """
    return (
        f"InvestwithIshan finance reel. "
        f"Ishan — composed Indian male, late 20s, MBA energy — speaks directly to camera. "
        f"Calm, articulate Indian English. Measured pace. "
        f"Hook: \"{hook}\" "
        f"Setting: minimal home office, warm ambient light from a large window behind. "
        f"Shot on phone, slightly handheld feel — authentic, not over-produced. "
        f"Natural eye contact, subtle hand gestures. Real-person energy, not broadcast TV. "
        f"@InvestwithIshan lower-third. UGC preset. 9:16."
    )


# ─── GENERATION FUNCTIONS ─────────────────────────────────────────────────────

def generate_finance_batch(scripts=None, with_voice=True, with_review=True):
    """Generate InvestwithIshan finance reels with voice + human-recorded UGC video."""
    print("\n📊 Generating FINANCE batch\n" + "─" * 40)
    keys = scripts or list(FINANCE_SCRIPTS.keys())
    jobs = []

    for key in keys:
        s = FINANCE_SCRIPTS[key]
        print(f"\n→ {s['title']}")

        # Save script to disk
        script_path = OUT_DIR / "scripts" / f"finance_{key}.txt"
        script_path.write_text(s["hook"])

        # Voice generation with pronunciation review
        audio_path = None
        if with_voice:
            audio_path, _ = generate_voice_with_review(s["hook"], f"finance_{key}", with_review)

        # Video: Marketing Studio UGC (human-recorded look)
        if not HIGGSFIELD_API_KEY:
            print("   HIGGSFIELD_API_KEY not set — skipping video.")
            continue

        try:
            prompt = build_ugc_prompt(s["hook"][:120])
            result = hf_generate_video(
                model="marketing_studio_video",
                prompt=prompt,
                aspect_ratio="9:16",
                duration=30,
                generate_audio=(audio_path is None),
                avatars=[{"id": ISHAN_AVATAR_ID, "type": "custom"}],
            )
            job_id = result.get("id") or result.get("job_id")
            print(f"   Job submitted: {job_id}")
            jobs.append({"key": key, "job_id": job_id, "title": s["title"]})
        except Exception as e:
            print(f"   Failed: {e}")

    return jobs


def generate_biohack_batch(items=None):
    """Generate biohack cinematic videos (Cinema Studio 3.0)."""
    print("\n🧬 Generating BIOHACK batch\n" + "─" * 40)
    keys = items or list(BIOHACK_PROMPTS.keys())
    jobs = []

    for key in keys:
        b = BIOHACK_PROMPTS[key]
        print(f"\n→ {b['title']}")
        if not HIGGSFIELD_API_KEY:
            print("   HIGGSFIELD_API_KEY not set — skipping video.")
            continue
        try:
            result = hf_generate_video(
                model="cinematic_studio_3_0",
                prompt=b["prompt"],
                aspect_ratio="9:16",
                duration=10,
                genre=b.get("genre", "drama")
            )
            job_id = result.get("id") or result.get("job_id")
            print(f"   Job submitted: {job_id}")
            jobs.append({"key": key, "job_id": job_id, "title": b["title"]})
        except Exception as e:
            print(f"   Failed: {e}")

    return jobs


def generate_books_batch(items=None, with_voice=True, with_review=True):
    """Generate book summary landscape videos with narration."""
    print("\n📚 Generating BOOK SUMMARIES batch\n" + "─" * 40)
    keys = items or list(BOOK_LANDSCAPES.keys())
    jobs = []

    for key in keys:
        b = BOOK_LANDSCAPES[key]
        print(f"\n→ {b['title']}")

        if with_voice:
            generate_voice_with_review(b["narration"], f"book_{key}", with_review)

        if not HIGGSFIELD_API_KEY:
            print("   HIGGSFIELD_API_KEY not set — skipping video.")
            continue
        try:
            result = hf_generate_video(
                model="kling3_0",
                prompt=b["visual_prompt"],
                aspect_ratio="9:16",
                duration=10,
                mode="pro",
            )
            job_id = result.get("id") or result.get("job_id")
            print(f"   Job submitted: {job_id}")
            jobs.append({"key": key, "job_id": job_id, "title": b["title"]})
        except Exception as e:
            print(f"   Failed: {e}")

    return jobs


def generate_psych_batch(items=None, with_voice=True, with_review=True):
    """Generate psychology fact videos (Wan 2.7 audio-sync)."""
    print("\n🧠 Generating PSYCHOLOGY batch\n" + "─" * 40)
    keys = items or list(PSYCH_FACTS.keys())
    jobs = []

    for key in keys:
        p = PSYCH_FACTS[key]
        print(f"\n→ {p['title']}")

        if with_voice:
            generate_voice_with_review(p["script"], f"psych_{key}", with_review)

        if not HIGGSFIELD_API_KEY:
            print("   HIGGSFIELD_API_KEY not set — skipping video.")
            continue
        try:
            result = hf_generate_video(
                model="wan2_7",
                prompt=p["visual"],
                aspect_ratio="9:16",
                duration=15,
                resolution="720p"
            )
            job_id = result.get("id") or result.get("job_id")
            print(f"   Job submitted: {job_id}")
            jobs.append({"key": key, "job_id": job_id, "title": p["title"]})
        except Exception as e:
            print(f"   Failed: {e}")

    return jobs


def one_shot(topic: str, pillar: str = "finance", duration: int = 30,
             no_wait: bool = False):
    """
    Full pipeline for a custom topic:
    Claude writes script → pronunciation fix → ElevenLabs voice → Higgsfield video.
    """
    print(f"\n🎬 One-shot pipeline: '{topic}' [{pillar}, {duration}s]\n" + "─" * 40)

    if not ANTHROPIC_API_KEY:
        print("ANTHROPIC_API_KEY not set — cannot generate script. Set it in .env")
        return

    # 1. Claude generates script
    print("[1/3] Claude generating script…")
    try:
        result = generate_script(topic, pillar, duration)
    except Exception as e:
        print(f"Script generation failed: {e}")
        return

    print(f"\n   Title: {result['title']}")
    print(f"   Script:\n   {result['script']}\n")
    print(f"   Notes: {result.get('notes', '')}")

    # Save script
    slug = re.sub(r"[^\w]+", "_", topic.lower())[:30]
    script_path = OUT_DIR / "scripts" / f"{pillar}_{slug}.json"
    script_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\n   Script saved → {script_path}")

    # 2. Voice generation (includes pronunciation review)
    print("\n[2/3] Generating voice…")
    audio_path, _ = generate_voice_with_review(
        result["pronunciation_fixed_script"], f"{pillar}_{slug}", with_review=True
    )

    # 3. Video generation
    print("\n[3/3] Generating video…")
    if not HIGGSFIELD_API_KEY:
        print("   HIGGSFIELD_API_KEY not set — skipping video.")
        return

    jobs = []
    try:
        if pillar == "finance":
            prompt = build_ugc_prompt(result["hook"][:120])
            res = hf_generate_video(
                model="marketing_studio_video",
                prompt=prompt,
                aspect_ratio="9:16",
                duration=duration,
                generate_audio=(audio_path is None),
                avatars=[{"id": ISHAN_AVATAR_ID, "type": "custom"}],
            )
        elif pillar == "biohack":
            res = hf_generate_video(
                model="cinematic_studio_3_0",
                prompt=result["script"],
                aspect_ratio="9:16",
                duration=10,
                genre="drama"
            )
        elif pillar == "books":
            res = hf_generate_video(
                model="kling3_0",
                prompt=result["script"],
                aspect_ratio="9:16",
                duration=10,
                mode="pro",
            )
        else:  # psych
            res = hf_generate_video(
                model="wan2_7",
                prompt=result["script"],
                aspect_ratio="9:16",
                duration=15,
                resolution="720p"
            )

        job_id = res.get("id") or res.get("job_id")
        print(f"   Job submitted: {job_id}")
        jobs.append({"key": slug, "job_id": job_id, "title": result["title"]})

        if not no_wait:
            wait_and_download(jobs, pillar)

    except Exception as e:
        print(f"   Video generation failed: {e}")


def voice_only(script_text: str, with_review: bool = True):
    """Generate just the voice audio for a given script."""
    print(f"\n🎙 Voice-only pipeline")
    slug = re.sub(r"[^\w]+", "_", script_text[:20].lower())
    audio_path, review = generate_voice_with_review(script_text, f"voice_{slug}", with_review)
    if audio_path:
        print(f"\n   Done → {audio_path}")
    if review and review.get("issues"):
        print(f"\n   Pronunciation notes: {review.get('notes','')}")


def review_only(script_text: str):
    """Run Claude pronunciation review without generating audio."""
    if not ANTHROPIC_API_KEY:
        print("ANTHROPIC_API_KEY not set.")
        return

    print("\n🔍 Pronunciation review\n" + "─" * 40)
    fixed = fix_pronunciation(script_text)
    print(f"Rule-based fixes applied.")

    try:
        review = review_pronunciation(fixed)
        issues = review.get("issues", [])
        print(f"\nIssues found: {len(issues)}")
        for iss in issues:
            print(f"  • {iss}")
        print(f"\nConfidence: {review.get('confidence','?')}")
        print(f"Notes: {review.get('notes','')}")
        print(f"\nCorrected script:\n{review['corrected_script']}")
    except Exception as e:
        print(f"Review failed: {e}")


# ─── INTERACTIVE MENU ─────────────────────────────────────────────────────────

def menu():
    print("""
╔═══════════════════════════════════════════╗
║   InvestwithIshan — AI Content Pipeline   ║
╚═══════════════════════════════════════════╝

  [1] Generate finance batch  (talking head reels)
  [2] Generate biohack batch  (cinematic science)
  [3] Generate book summaries (landscape + narration)
  [4] Generate psychology batch (audio-sync animations)
  [5] Generate ALL pillars
  [6] One-shot: AI writes + generates (custom topic)
  [7] Voice only  (enter script)
  [8] Pronunciation review (enter script)
  [9] List ElevenLabs voices
  [q] Quit
""")
    choice = input("Choose: ").strip().lower()

    if choice == "1":
        jobs = generate_finance_batch()
        wait_and_download(jobs, "finance")
    elif choice == "2":
        jobs = generate_biohack_batch()
        wait_and_download(jobs, "biohack")
    elif choice == "3":
        jobs = generate_books_batch()
        wait_and_download(jobs, "books")
    elif choice == "4":
        jobs = generate_psych_batch()
        wait_and_download(jobs, "psych")
    elif choice == "5":
        for fn, pillar in [
            (generate_finance_batch, "finance"),
            (generate_biohack_batch, "biohack"),
            (generate_books_batch,   "books"),
            (generate_psych_batch,   "psych"),
        ]:
            jobs = fn() if pillar == "biohack" else fn(with_voice=True)
            wait_and_download(jobs, pillar)
    elif choice == "6":
        topic = input("Topic (e.g. 'SIP delay costs 32 lakh'): ").strip()
        pillar = input("Pillar [finance/biohack/books/psych] (default: finance): ").strip() or "finance"
        dur = input("Duration in seconds [30/60] (default: 30): ").strip()
        duration = int(dur) if dur.isdigit() else 30
        if topic:
            one_shot(topic, pillar, duration)
    elif choice == "7":
        script = input("Enter script text: ").strip()
        if script:
            voice_only(script)
    elif choice == "8":
        script = input("Enter script text: ").strip()
        if script:
            review_only(script)
    elif choice == "9":
        voices = el_get_voices()
        print(f"\n{len(voices)} voices found:")
        for v in voices:
            labels = v.get("labels", {})
            print(f"  {v['name']:20s}  accent:{labels.get('accent','—'):15s}  gender:{labels.get('gender','—')}")
    elif choice == "q":
        sys.exit(0)
    else:
        print("Unknown option.")

    menu()


# ─── CLI ENTRYPOINT ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="InvestwithIshan AI influencer pipeline")
    parser.add_argument("--pillar", choices=["finance", "biohack", "books", "psych"],
                        help="Generate a specific pillar batch")
    parser.add_argument("--all", action="store_true",
                        help="Generate all pillar batches")
    parser.add_argument("--topic", type=str,
                        help="One-shot: AI writes script + generates for this topic")
    parser.add_argument("--topic-pillar", default="finance",
                        choices=["finance", "biohack", "books", "psych"],
                        help="Pillar for --topic (default: finance)")
    parser.add_argument("--topic-duration", type=int, default=30,
                        help="Duration for --topic reel in seconds (default: 30)")
    parser.add_argument("--voice", type=str, metavar="SCRIPT",
                        help="Generate voice audio only for a given script")
    parser.add_argument("--review", type=str, metavar="SCRIPT",
                        help="Run pronunciation review on a script (no generation)")
    parser.add_argument("--no-voice", action="store_true",
                        help="Skip voice generation")
    parser.add_argument("--no-review", action="store_true",
                        help="Skip Claude pronunciation review step")
    parser.add_argument("--no-wait", action="store_true",
                        help="Submit Higgsfield jobs without waiting/downloading")
    args = parser.parse_args()

    with_voice  = not args.no_voice
    with_review = not args.no_review

    if args.review:
        review_only(args.review)
        return

    if args.voice:
        voice_only(args.voice, with_review=with_review)
        return

    if args.topic:
        one_shot(args.topic, args.topic_pillar, args.topic_duration, no_wait=args.no_wait)
        return

    if args.all:
        for fn, pillar in [
            (generate_finance_batch, "finance"),
            (generate_biohack_batch, "biohack"),
            (generate_books_batch,   "books"),
            (generate_psych_batch,   "psych"),
        ]:
            if pillar == "biohack":
                jobs = fn()
            else:
                jobs = fn(with_voice=with_voice, with_review=with_review)
            if not args.no_wait:
                wait_and_download(jobs, pillar)
        return

    if args.pillar == "finance":
        jobs = generate_finance_batch(with_voice=with_voice, with_review=with_review)
        if not args.no_wait: wait_and_download(jobs, "finance")
    elif args.pillar == "biohack":
        jobs = generate_biohack_batch()
        if not args.no_wait: wait_and_download(jobs, "biohack")
    elif args.pillar == "books":
        jobs = generate_books_batch(with_voice=with_voice, with_review=with_review)
        if not args.no_wait: wait_and_download(jobs, "books")
    elif args.pillar == "psych":
        jobs = generate_psych_batch(with_voice=with_voice, with_review=with_review)
        if not args.no_wait: wait_and_download(jobs, "psych")
    else:
        menu()


if __name__ == "__main__":
    main()
