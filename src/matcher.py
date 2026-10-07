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

    overlap = len(matching) / len(jd_skills)  # 0..1 coverage of JD skills

    # Confidence: a JD listing only 1-2 detected skills is weak evidence, so a
    # "100%" there should not outrank a richer JD. Ramp confidence up to a floor
    # of CONFIDENCE_MIN until the JD lists CONFIDENCE_FULL_AT skills.
    CONFIDENCE_FULL_AT = 6
    CONFIDENCE_MIN = 0.5
    confidence = min(1.0, CONFIDENCE_MIN + (1 - CONFIDENCE_MIN) * (len(jd_skills) / CONFIDENCE_FULL_AT))
    score = round(overlap * confidence * 100, 1)

    if matching:
        reason = f"Your resume covers {len(matching)} of {len(jd_skills)} skills in this role: "
        reason += ", ".join(matching[:6])
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
        # Use the REST transport (more firewall-friendly than the default gRPC).
        genai.configure(api_key=config.google_api_key, transport="rest")
        model = genai.GenerativeModel(
            config.gemini_model,
            generation_config={"temperature": 0, "response_mime_type": "application/json"},
        )
        resp = model.generate_content(
            _build_prompt(job, resume_text),
            request_options={"timeout": 20},
        )
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


def _best_profile(job: Job, profiles: list[ResumeProfile], config: Config):
    """Keyword-score every profile and return (best_profile, best_keyword_result)."""
    best_profile = None
    best_kw = None
    best_score = -1.0
    for profile in profiles:
        kw = keyword_match(job, profile.skills, config)
        if kw["match_score"] > best_score:
            best_score = kw["match_score"]
            best_profile = profile
            best_kw = kw
    return best_profile, best_kw


def _prefix_reason(job: Job, profile_name: str) -> None:
    prefix = f"[Best fit: {profile_name}] "
    if not job.reason.startswith("[Best fit:"):
        job.reason = prefix + job.reason


def match_job_multi(job: Job, profiles: list[ResumeProfile], config: Config) -> Job:
    """Fast KEYWORD match of a job against every resume profile; best fit wins.

    This path does NO LLM call — it is instant and used to score and rank ALL
    jobs. LLM enrichment happens separately on just the top jobs via
    enrich_with_llm(). The winning profile is stored on the job and remembered
    (job._best_profile) so enrichment can reuse it without re-scoring.
    Always succeeds.
    """
    if not profiles:
        return _apply_result(job, {
            "match_score": 0.0, "matching_skills": [], "missing_skills": [],
            "reason": "No resume profiles available.", "recommendation": "LOW PRIORITY",
        })

    best_profile, best_kw = _best_profile(job, profiles, config)
    _apply_result(job, best_kw)
    if best_profile is not None:
        job.matched_resume = best_profile.name
        job._best_profile = best_profile  # cached for enrichment
        _prefix_reason(job, best_profile.name)
    return job


def enrich_with_llm(job: Job, config: Config) -> Job:
    """Upgrade an already keyword-matched job with an LLM pass (top jobs only).

    Uses the job's best-fit resume (cached by match_job_multi). On any LLM
    failure/timeout the existing keyword result is kept unchanged.
    Always succeeds; never raises.
    """
    if not config.has_llm:
        return job
    profile = getattr(job, "_best_profile", None)
    if profile is None:
        return job
    try:
        llm = _llm_match(job, profile.text, config)
    except Exception as exc:  # safety net
        log.warning("LLM enrichment errored (%s); keeping keyword result.", exc)
        llm = None
    if llm is not None:
        _apply_result(job, llm)
        _prefix_reason(job, profile.name)
    return job
