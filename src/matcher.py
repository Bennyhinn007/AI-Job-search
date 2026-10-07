"""Resume <-> job-description matching.

Two modes:
  * keyword (default, offline, always available)
  * LLM (used when GOOGLE_API_KEY or OPENAI_API_KEY is set; Gemini is preferred,
    then OpenAI; falls back to keyword on ANY error)

The public entry point match_job() picks the mode and guarantees a result.
"""

from __future__ import annotations

import json
import logging

from config import Config
from src.models import Job
from src.resume_parser import ResumeProfile, extract_skills

log = logging.getLogger("matcher")


def _recommendation(score: float, config: Config) -> str:
    if score >= config.apply_threshold:
        return "APPLY"
    if score >= config.consider_threshold:
        return "CONSIDER"
    return "LOW PRIORITY"


def keyword_match(job: Job, resume_skills: list[str], config: Config) -> dict:
    """Skill-overlap matching. Never divides by zero."""
    jd_skills = extract_skills(job.description + " " + job.title, config.skills_vocabulary)
    resume_set = {s.lower() for s in resume_skills}

    if not jd_skills:
        # No recognizable skills in the JD: neutral, low-confidence result.
        return {
            "match_score": 0.0,
            "matching_skills": [],
            "missing_skills": [],
            "reason": "No recognizable skills detected in this job description.",
            "recommendation": "LOW PRIORITY",
        }

    matching = [s for s in jd_skills if s.lower() in resume_set]
    missing = [s for s in jd_skills if s.lower() not in resume_set]
    score = round(len(matching) / len(jd_skills) * 100, 1)

    if matching:
        reason = "Your resume covers " + ", ".join(matching[:6])
        if len(matching) > 6:
            reason += f", and {len(matching) - 6} more"
        reason += "."
    else:
        reason = "No overlapping skills found between your resume and this role."

    return {
        "match_score": score,
        "matching_skills": matching,
        "missing_skills": missing,
        "reason": reason,
        "recommendation": _recommendation(score, config),
    }


def _build_prompt(job: Job, resume_text: str) -> str:
    # Keep payload bounded.
    resume_snippet = (resume_text or "")[:4000]
    jd_snippet = (job.description or "")[:4000]
    return (
        "You are a job-matching assistant. Compare the RESUME to the JOB.\n"
        "Return ONLY compact JSON with keys: match_score (0-100 number), "
        "matching_skills (list of strings), missing_skills (list of strings), "
        "reason (short string), recommendation (one of APPLY, CONSIDER, LOW PRIORITY).\n\n"
        f"JOB TITLE: {job.title}\n"
        f"JOB DESCRIPTION:\n{jd_snippet}\n\n"
        f"RESUME:\n{resume_snippet}\n"
    )


def _parse_llm_json(content: str, config: Config) -> dict:
    """Validate/normalize an LLM JSON response into our standard result dict."""
    data = json.loads(content)
    score = float(data.get("match_score", 0))
    score = max(0.0, min(100.0, score))
    rec = str(data.get("recommendation", "")).upper().strip()
    if rec not in ("APPLY", "CONSIDER", "LOW PRIORITY"):
        rec = _recommendation(score, config)
    return {
        "match_score": round(score, 1),
        "matching_skills": [str(s) for s in data.get("matching_skills", [])][:20],
        "missing_skills": [str(s) for s in data.get("missing_skills", [])][:20],
        "reason": str(data.get("reason", "")).strip()[:500],
        "recommendation": rec,
    }


def _strip_code_fence(text: str) -> str:
    """Gemini sometimes wraps JSON in ```json ... ``` fences; strip them."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1] if "\n" in t else t
        if t.endswith("```"):
            t = t[: -3]
        if t.lstrip().startswith("json"):
            t = t.lstrip()[4:]
    return t.strip()


def _gemini_match(job: Job, resume_text: str, config: Config) -> dict | None:
    """Attempt Google Gemini matching. Returns a validated dict or None on failure."""
    try:
        import google.generativeai as genai
    except ImportError:
        log.info("google-generativeai SDK not installed; skipping Gemini.")
        return None
    try:
        genai.configure(api_key=config.google_api_key)
        model = genai.GenerativeModel(
            config.gemini_model,
            generation_config={"temperature": 0, "response_mime_type": "application/json"},
        )
        resp = model.generate_content(_build_prompt(job, resume_text))
        return _parse_llm_json(_strip_code_fence(resp.text), config)
    except Exception as exc:
        log.warning("Gemini matching failed (%s); trying next option.", exc)
        return None


def _openai_match(job: Job, resume_text: str, config: Config) -> dict | None:
    """Attempt OpenAI matching. Returns a validated dict or None on failure."""
    try:
        from openai import OpenAI
    except ImportError:
        log.info("openai SDK not installed; skipping OpenAI.")
        return None
    try:
        client = OpenAI(api_key=config.openai_api_key)
        resp = client.chat.completions.create(
            model=config.openai_model,
            messages=[{"role": "user", "content": _build_prompt(job, resume_text)}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        return _parse_llm_json(resp.choices[0].message.content, config)
    except Exception as exc:
        log.warning("OpenAI matching failed (%s); trying next option.", exc)
        return None


def _llm_match(job: Job, resume_text: str, config: Config) -> dict | None:
    """Try the configured LLM provider(s). Returns a result or None if all fail."""
    # Prefer Gemini (Google) when its key is present, then OpenAI.
    if config.has_gemini:
        result = _gemini_match(job, resume_text, config)
        if result is not None:
            return result
    if config.has_openai:
        return _openai_match(job, resume_text, config)
    return None


def _apply_result(job: Job, result: dict) -> Job:
    job.match_score = result["match_score"]
    job.matching_skills = result["matching_skills"]
    job.missing_skills = result["missing_skills"]
    job.reason = result["reason"]
    job.recommendation = result["recommendation"]
    return job


def match_job(job: Job, resume_text: str, resume_skills: list[str], config: Config) -> Job:
    """Populate the job's matching fields against a single resume. Always succeeds."""
    result = None
    if config.has_llm:
        result = _llm_match(job, resume_text, config)
    if result is None:
        result = keyword_match(job, resume_skills, config)
    return _apply_result(job, result)


def match_job_multi(job: Job, profiles: list[ResumeProfile], config: Config) -> Job:
    """Match a job against EVERY resume profile and keep the best-scoring one.

    For keyword matching we score all profiles (cheap) and pick the best.
    For LLM matching, to limit API calls, we first find the best profile by the
    fast keyword score, then run the LLM only on that profile (with keyword
    fallback). The winning profile's name is recorded on the job.
    Always succeeds.
    """
    if not profiles:
        # No profiles: nothing to match against.
        return _apply_result(job, {
            "match_score": 0.0, "matching_skills": [], "missing_skills": [],
            "reason": "No resume profiles available.", "recommendation": "LOW PRIORITY",
        })

    # 1. Keyword-score every profile to find the best fit.
    best_profile = None
    best_kw = None
    best_score = -1.0
    for profile in profiles:
        kw = keyword_match(job, profile.skills, config)
        if kw["match_score"] > best_score:
            best_score = kw["match_score"]
            best_profile = profile
            best_kw = kw

    # 2. Optionally upgrade the winning profile with an LLM pass.
    result = best_kw
    if config.has_llm and best_profile is not None:
        llm = _llm_match(job, best_profile.text, config)
        if llm is not None:
            result = llm

    _apply_result(job, result)
    # Record which resume won and surface it in the reason.
    if best_profile is not None:
        job.matched_resume = best_profile.name
        prefix = f"[Best fit: {best_profile.name}] "
        if not job.reason.startswith("[Best fit:"):
            job.reason = prefix + job.reason
    return job
