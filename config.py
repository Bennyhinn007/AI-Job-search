"""Centralized configuration for AI Job Search.

Loads settings from a .env file (via python-dotenv) and exposes them as a
single typed object. Secrets are never printed; the check() helper reports
only whether each secret is set.

Edit SKILLS_VOCABULARY and TARGET_ROLES here to tune what the system looks for.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()  # loads .env from the current working directory if present


# ---------------------------------------------------------------------------
# Skills / technology vocabulary (single source of truth).
# Used both for resume skill extraction and job-description skill detection.
# Edit freely. Keep entries lowercase-comparable; matching is case-insensitive.
# ---------------------------------------------------------------------------
SKILLS_VOCABULARY: list[str] = [
    "Java", "Python", "C", "C++", "C#", "Go", "Rust", "JavaScript", "TypeScript",
    "HTML", "CSS", "React", "Next.js", "Angular", "Vue", "Node.js", "Express",
    "Spring Boot", "Django", "Flask", "FastAPI", "REST API", "GraphQL",
    "MongoDB", "MySQL", "PostgreSQL", "SQL", "Redis", "Elasticsearch",
    "Git", "GitHub", "GitLab", "Docker", "Kubernetes", "Terraform", "Ansible",
    "AWS", "Azure", "GCP", "Linux", "Bash", "Networking",
    "Cybersecurity", "Penetration Testing", "VAPT", "Burp Suite", "Nmap",
    "Wireshark", "Metasploit", "SIEM", "Splunk", "Cloud Security",
    "DevOps", "DevSecOps", "CI/CD", "Jenkins",
    "Blockchain", "Ethereum", "Solidity", "Web3", "Smart Contracts",
    "AI", "Machine Learning", "Deep Learning", "NLP", "PyTorch", "TensorFlow",
    "Pandas", "NumPy", "Scikit-learn", "Kafka", "Spark", "Airflow",
    "Selenium", "Cypress", "JUnit", "Pytest",
]


# ---------------------------------------------------------------------------
# Target roles. A job is "relevant" if its title or description mentions any
# of these (case-insensitive). Kept broad on purpose.
# ---------------------------------------------------------------------------
TARGET_ROLES: list[str] = [
    "Software Engineer", "Software Developer", "Full Stack Developer",
    "Backend Developer", "Frontend Developer", "Java Developer",
    "Python Developer", "Web Developer",
    "Cybersecurity Analyst", "Security Engineer", "Application Security Engineer",
    "Cloud Engineer", "DevOps Engineer", "DevSecOps Engineer",
    "AI Engineer", "ML Engineer", "Machine Learning Engineer",
    "Data Engineer", "QA Engineer", "Automation Engineer",
    "Systems Engineer", "Network Engineer", "IT Engineer", "IT Analyst",
    "Technical Support Engineer", "Solutions Engineer",
    # Loose single-word anchors so we don't accidentally drop good roles.
    "developer", "engineer", "programmer",
]


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _get_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class Config:
    # Adzuna
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    adzuna_country: str = "in"

    # Email
    email_address: str = ""
    email_password: str = ""
    recipient_email: str = ""

    # LLM (OpenAI)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # LLM (Google Gemini)
    google_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"

    # Tuning
    max_job_age_days: int = 1
    min_match_score: int = 60
    max_email_jobs: int = 10
    apply_threshold: int = 80
    consider_threshold: int = 60

    location_priority: list[str] = field(default_factory=list)

    # Shared vocab
    skills_vocabulary: list[str] = field(default_factory=lambda: list(SKILLS_VOCABULARY))
    target_roles: list[str] = field(default_factory=lambda: list(TARGET_ROLES))

    # ---- convenience flags ----
    @property
    def has_adzuna(self) -> bool:
        return bool(self.adzuna_app_id and self.adzuna_app_key)

    @property
    def has_email(self) -> bool:
        return bool(self.email_address and self.email_password and self.recipient_email)

    @property
    def has_gemini(self) -> bool:
        return bool(self.google_api_key)

    @property
    def has_openai(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def has_llm(self) -> bool:
        return bool(self.google_api_key or self.openai_api_key)

    @property
    def llm_provider(self) -> str:
        """Which LLM provider will be used: 'gemini', 'openai', or 'none'."""
        if self.google_api_key:
            return "gemini"
        if self.openai_api_key:
            return "openai"
        return "none"


def load_config() -> Config:
    return Config(
        adzuna_app_id=os.getenv("ADZUNA_APP_ID", "").strip(),
        adzuna_app_key=os.getenv("ADZUNA_APP_KEY", "").strip(),
        adzuna_country=os.getenv("ADZUNA_COUNTRY", "in").strip() or "in",
        email_address=os.getenv("EMAIL_ADDRESS", "").strip(),
        email_password=os.getenv("EMAIL_PASSWORD", "").strip(),
        recipient_email=os.getenv("RECIPIENT_EMAIL", "").strip(),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        google_api_key=os.getenv("GOOGLE_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-flash-latest").strip() or "gemini-flash-latest",
        max_job_age_days=_get_int("MAX_JOB_AGE_DAYS", 1),
        min_match_score=_get_int("MIN_MATCH_SCORE", 60),
        max_email_jobs=_get_int("MAX_EMAIL_JOBS", 10),
        apply_threshold=_get_int("APPLY_THRESHOLD", 80),
        consider_threshold=_get_int("CONSIDER_THRESHOLD", 60),
        location_priority=_get_list(
            "LOCATION_PRIORITY",
            ["Bengaluru", "Hyderabad", "Pune", "Chennai", "Mumbai", "Delhi NCR", "Remote"],
        ),
    )


def describe(config: Config) -> str:
    """Human-readable, SECRET-SAFE summary of the loaded config."""
    def flag(value: bool) -> str:
        return "set" if value else "not set"

    lines = [
        "AI Job Search - configuration check",
        "-" * 40,
        f"Adzuna credentials : {flag(config.has_adzuna)}",
        f"Adzuna country     : {config.adzuna_country}",
        f"Email credentials  : {flag(config.has_email)}",
        f"Google (Gemini) key: {flag(config.has_gemini)}  (optional)",
        f"OpenAI key         : {flag(config.has_openai)}  (optional)",
        f"LLM provider       : {config.llm_provider}",
        "",
        f"Max job age (days) : {config.max_job_age_days}",
        f"Min match score    : {config.min_match_score}",
        f"Max email jobs     : {config.max_email_jobs}",
        f"APPLY threshold    : {config.apply_threshold}",
        f"CONSIDER threshold : {config.consider_threshold}",
        f"Location priority  : {', '.join(config.location_priority)}",
        f"Skills vocabulary  : {len(config.skills_vocabulary)} entries",
        f"Target roles       : {len(config.target_roles)} entries",
        "",
        "Matching mode      : " + (f"LLM/{config.llm_provider} (keyword fallback)" if config.has_llm else "keyword"),
        "Job sources        : " + ("Adzuna + Remotive" if config.has_adzuna else "Remotive (keyless)"),
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe(load_config()))
