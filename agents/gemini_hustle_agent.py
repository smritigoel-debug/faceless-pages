"""
Gemini Hustle Content Agent
============================
Creates Instagram content (statics + videos) for 18-21 yr olds around:
  - Hustle culture satire
  - CUET exam struggles
  - Adulting
  - Gen Z friendships

Uses Gemini for content scripting + guidance, then fires image/video generation.
"""

import os
import json
import time
import requests
from typing import Optional

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL   = "gemini-2.0-flash"
GEMINI_URL     = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# Higgsfield / faceless-pages API (populated from env)
HF_API_KEY     = os.environ.get("HIGGSFIELD_API_KEY", "")
HF_BASE        = "https://api.higgsfield.ai/v1"

HEADERS_HF     = {"Authorization": f"Bearer {HF_API_KEY}", "Content-Type": "application/json"}

# ---------------------------------------------------------------------------
# CONTENT THEMES
# ---------------------------------------------------------------------------
THEMES = [
    {
        "id": "cuet_struggle",
        "topic": "CUET exam 2026 struggles",
        "type": "static",
        "tone": "dark humor, satirical, relatable to Indian college aspirants",
        "format": "meme split-panel or checklist",
    },
    {
        "id": "hustle_culture",
        "topic": "Hustle culture and grindset satire",
        "type": "static",
        "tone": "sarcastic, funny, CEO mindset parody",
        "format": "before/after or tips list",
    },
    {
        "id": "adulting",
        "topic": "Adulting struggles at 18-21",
        "type": "static",
        "tone": "relatable, overwhelmed but humorous",
        "format": "unlocked achievement checklist",
    },
    {
        "id": "friendship_2026",
        "topic": "Gen Z friendships in 2026",
        "type": "static",
        "tone": "dry humor, texting culture, ghosting",
        "format": "chat screenshot mockup",
    },
    {
        "id": "cuet_day_in_life",
        "topic": "A day in the life of a CUET aspirant",
        "type": "video",
        "tone": "satirical comedy, fast cuts",
        "format": "reel, 8 seconds, 9:16",
    },
    {
        "id": "hustle_bro_day",
        "topic": "Day in the life of a hustle bro CEO",
        "type": "video",
        "tone": "satirical, parody, Gen Z humor",
        "format": "reel, 8 seconds, 9:16",
    },
]


# ---------------------------------------------------------------------------
# GEMINI HELPERS
# ---------------------------------------------------------------------------

def gemini_ask(prompt: str, system: str = "") -> str:
    """Call Gemini and return the text response."""
    if not GEMINI_API_KEY:
        raise EnvironmentError("GEMINI_API_KEY not set")

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.9, "maxOutputTokens": 1024},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}

    resp = requests.post(
        GEMINI_URL,
        headers={"Content-Type": "application/json"},
        params={"key": GEMINI_API_KEY},
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


SYSTEM_CONTENT_AGENT = """
You are a Gen Z social media content strategist for an Indian Instagram page.
Target: 18-21 year olds, India, 2026.
Platform: Instagram (statics = posts, videos = Reels).
Language: Hinglish (mix of Hindi + English) or English with Indian slang.
Style: Funny, satirical, dark humor, extremely relatable, trending meme formats.
Topics: hustle culture, CUET exams, adulting, Gen Z friendships.
Always output structured JSON.
"""

def get_content_brief(theme: dict) -> dict:
    """Ask Gemini to produce a full content brief for a theme."""
    prompt = f"""
Create an Instagram content brief for:
Topic: {theme['topic']}
Type: {theme['type']} ({theme['format']})
Tone: {theme['tone']}

Return ONLY valid JSON with these fields:
{{
  "hook": "First line / hook text (max 10 words, punchy)",
  "copy": "Full caption copy with emojis (max 150 chars)",
  "hashtags": ["list", "of", "10", "relevant", "hashtags"],
  "visual_description": "Detailed visual description for image/video generation (2-3 sentences)",
  "image_prompt": "Optimized prompt for AI image generator (for statics only, else null)",
  "video_script": "Scene-by-scene script for video (for videos only, else null)",
  "cta": "Call to action (e.g. 'save this', 'tag your squad')"
}}
"""
    raw = gemini_ask(prompt, SYSTEM_CONTENT_AGENT)
    # Strip markdown code fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


# ---------------------------------------------------------------------------
# IMAGE / VIDEO GENERATION (Higgsfield API direct calls)
# ---------------------------------------------------------------------------

def generate_image(prompt: str, aspect_ratio: str = "9:16") -> dict:
    """Submit an image generation job."""
    body = {
        "model": "gpt_image_2",
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "quality": "high",
        "resolution": "2k",
    }
    resp = requests.post(f"{HF_BASE}/image/generate", headers=HEADERS_HF, json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def generate_video(prompt: str, duration: int = 8, aspect_ratio: str = "9:16") -> dict:
    """Submit a video generation job."""
    body = {
        "model": "kling3_0",
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "duration": duration,
        "mode": "std",
        "sound": "on",
    }
    resp = requests.post(f"{HF_BASE}/video/generate", headers=HEADERS_HF, json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def poll_job(job_id: str, max_wait: int = 300) -> dict:
    """Poll until a generation job completes or times out."""
    interval = 10
    elapsed = 0
    while elapsed < max_wait:
        resp = requests.get(f"{HF_BASE}/jobs/{job_id}", headers=HEADERS_HF, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status", "pending")
        print(f"  [{job_id[:8]}] status={status} ({elapsed}s)")
        if status in ("completed", "failed"):
            return data
        time.sleep(interval)
        elapsed += interval
    raise TimeoutError(f"Job {job_id} did not complete within {max_wait}s")


# ---------------------------------------------------------------------------
# MAIN AGENT LOOP
# ---------------------------------------------------------------------------

def run_agent(dry_run: bool = False) -> list[dict]:
    """
    Full agent run:
    1. Get Gemini brief for each theme
    2. Generate images/videos
    3. Return list of completed content items
    """
    results = []

    for theme in THEMES:
        print(f"\n=== [{theme['id']}] Getting Gemini brief ===")

        if dry_run or not GEMINI_API_KEY:
            # Use pre-baked briefs (see content_plan.json)
            with open("content_plan.json") as f:
                plan = json.load(f)
            brief = next(p for p in plan if p["id"] == theme["id"])
        else:
            brief = get_content_brief(theme)
            brief["id"] = theme["id"]
            brief["type"] = theme["type"]

        print(f"  Hook: {brief.get('hook', '')}")
        print(f"  Copy: {brief.get('copy', '')[:80]}...")

        if not dry_run:
            print(f"  Generating {theme['type']}...")
            if theme["type"] == "static":
                job = generate_image(brief.get("image_prompt", brief["visual_description"]))
            else:
                job = generate_video(brief.get("video_script", brief["visual_description"]))

            job_id = job["results"][0]["id"]
            print(f"  Job ID: {job_id}")
            completed = poll_job(job_id)
            brief["job_result"] = completed

        results.append(brief)

    return results


# ---------------------------------------------------------------------------
# ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv

    if not GEMINI_API_KEY and not dry:
        print("[WARN] GEMINI_API_KEY not set — will use pre-baked content_plan.json briefs")

    output = run_agent(dry_run=dry)

    out_file = "agent_run_output.json"
    with open(out_file, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nDone! Results saved to {out_file}")
