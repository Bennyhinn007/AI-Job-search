"""Resume loading and skill extraction (multi-resume aware).

The app supports MULTIPLE resume profiles in the resume/ folder. Each .txt or
.pdf (except the bundled sample) becomes a ResumeProfile with its own text and
skill set. Each job is later matched against every profile and the best fit
wins. A single resume still works — it's just one profile.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

RESUME_DIR = "resume"
# Legacy single-file paths (still supported as a fallback).
PDF_PATH = os.path.join(RESUME_DIR, "resume.pdf")
TXT_PATH = os.path.join(RESUME_DIR, "resume.txt")

# Files in resume/ we never treat as a real resume.
_IGNORED_NAMES = {".gitkeep", "resume.sample.txt"}


class ResumeNotFoundError(FileNotFoundError):
    pass


@dataclass
class ResumeProfile:
    name: str            # human label derived from the filename
    path: str
    text: str
    skills: list[str] = field(default_factory=list)


def _read_pdf(path: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "pypdf is required to read PDF resumes. Run: pip install pypdf"
        ) from exc

    reader = PdfReader(path)
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(parts)


def _read_file(path: str) -> str:
    if path.lower().endswith(".pdf"):
        return _read_pdf(path)
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def _label_from_filename(filename: str) -> str:
    """Turn '01-cybersecurity.txt' into 'Cybersecurity'."""
    base = os.path.splitext(filename)[0]
    # strip a leading numeric ordering prefix like "01-" or "1_"
    for sep in ("-", "_"):
        head, _, tail = base.partition(sep)
        if head.isdigit() and tail:
            base = tail
            break
    return base.replace("-", " ").replace("_", " ").strip().title() or filename


import re
from functools import lru_cache


@lru_cache(maxsize=512)
def _skill_pattern(skill: str) -> "re.Pattern[str]":
    """Compile a word-boundary-aware, case-insensitive pattern for a skill.

    Plain substring matching over-matches badly: 'C' matches the 'c' inside
    'Docker', 'AI' matches 'maintain', 'Go' matches 'Google'. We instead require
    the skill to appear as a whole token. Special characters in skill names
    (C++, C#, Next.js, CI/CD, Node.js) are escaped, and we use lookarounds
    rather than \\b so symbol-containing skills still anchor correctly.
    """
    esc = re.escape(skill)
    # A token boundary = start/space/punctuation on each side, but allow the
    # skill's own trailing symbols (e.g. the '+' in C++, '#' in C#).
    return re.compile(rf"(?<![A-Za-z0-9]){esc}(?![A-Za-z0-9])", re.IGNORECASE)


def extract_skills(text: str, vocabulary: list[str]) -> list[str]:
    """Return the vocabulary skills present in the text as whole tokens.

    Case-insensitive, word-boundary aware so short skills like 'C', 'Go', 'AI'
    don't match substrings of unrelated words.
    """
    blob = text or ""
    found = []
    for skill in vocabulary:
        if _skill_pattern(skill).search(blob):
            found.append(skill)
    return found


def load_resume_text(pdf_path: str = PDF_PATH, txt_path: str = TXT_PATH) -> str:
    """Legacy single-resume loader. Raises if neither default file exists."""
    if os.path.exists(pdf_path):
        text = _read_pdf(pdf_path)
        if text.strip():
            return text
    if os.path.exists(txt_path):
        return _read_file(txt_path)
    raise ResumeNotFoundError(
        f"No resume found. Place your resume at '{pdf_path}' or '{txt_path}'."
    )


def load_resume_profiles(resume_dir: str = RESUME_DIR,
                         vocabulary: list[str] | None = None) -> list[ResumeProfile]:
    """Load every resume in resume_dir as a ResumeProfile (skills populated).

    Picks up all .txt and .pdf files except the sample/.gitkeep. Raises
    ResumeNotFoundError if the folder has no usable resume.
    """
    vocabulary = vocabulary or []
    profiles: list[ResumeProfile] = []

    if os.path.isdir(resume_dir):
        for filename in sorted(os.listdir(resume_dir)):
            if filename in _IGNORED_NAMES:
                continue
            lower = filename.lower()
            if not (lower.endswith(".txt") or lower.endswith(".pdf")):
                continue
            path = os.path.join(resume_dir, filename)
            try:
                text = _read_file(path)
            except Exception:
                continue
            if not text.strip():
                continue
            profiles.append(ResumeProfile(
                name=_label_from_filename(filename),
                path=path,
                text=text,
                skills=extract_skills(text, vocabulary),
            ))

    if not profiles:
        raise ResumeNotFoundError(
            f"No resume found in '{resume_dir}/'. Add a .pdf or .txt resume there "
            f"(e.g. copy resume/resume.sample.txt to resume/resume.txt)."
        )
    return profiles
