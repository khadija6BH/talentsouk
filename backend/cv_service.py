"""Validation and text extraction for user-uploaded CV documents."""

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from zipfile import BadZipFile, ZipFile
import re

from docx import Document
from pypdf import PdfReader


MAX_EXTRACTED_TEXT_LENGTH = 2_000_000


class CVExtractionError(ValueError):
    """Raised when an uploaded file is not a readable PDF or DOCX document."""


@dataclass(frozen=True)
class ExtractedCV:
    text: str
    mime_type: str
    page_count: int | None
    content_sha256: str
    extraction_status: str


def _clean_text(parts):
    text = "\n".join(part.strip() for part in parts if part and part.strip()).strip()
    if len(text) > MAX_EXTRACTED_TEXT_LENGTH:
        raise CVExtractionError("The extracted CV text is too large to store safely.")
    return text


def _extract_pdf(data):
    if not data.startswith(b"%PDF-"):
        raise CVExtractionError("The selected file is not a valid PDF document.")
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise CVExtractionError("Password-protected PDF files are not supported.")
        text = _clean_text(page.extract_text() or "" for page in reader.pages)
        return text, len(reader.pages), "application/pdf"
    except CVExtractionError:
        raise
    except Exception as exc:
        raise CVExtractionError("The PDF could not be read.") from exc


def _extract_docx(data):
    try:
        with ZipFile(BytesIO(data)) as archive:
            names = set(archive.namelist())
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise CVExtractionError("The selected file is not a valid DOCX document.")

        document = Document(BytesIO(data))
        parts = [paragraph.text for paragraph in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.append("\t".join(cell.text.strip() for cell in row.cells))
        return _clean_text(parts), None, (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    except CVExtractionError:
        raise
    except (BadZipFile, Exception) as exc:
        raise CVExtractionError("The DOCX file could not be read.") from exc


def _validate_doc(data):
    """Validate a legacy Word binary without pretending its text was extracted."""
    if not data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        raise CVExtractionError("The selected file is not a valid DOC document.")
    return "", None, "application/msword"


def extract_cv(data, extension):
    """Validate document content and return extracted text plus immutable metadata."""
    if not data:
        raise CVExtractionError("The selected CV file is empty.")

    extension = str(extension or "").casefold()
    if extension == "pdf":
        text, page_count, mime_type = _extract_pdf(data)
    elif extension == "doc":
        text, page_count, mime_type = _validate_doc(data)
    elif extension == "docx":
        text, page_count, mime_type = _extract_docx(data)
    else:
        raise CVExtractionError("Only PDF, DOC, and DOCX files are supported.")

    return ExtractedCV(
        text=text,
        mime_type=mime_type,
        page_count=page_count,
        content_sha256=sha256(data).hexdigest(),
        extraction_status="extracted" if text else "no_text",
    )


SECTION_ALIASES = {
    "summary": ("summary", "profile", "profil", "about", "objective", "objectif"),
    "skills": ("skills", "compétences", "competences", "technologies", "technical skills"),
    "education": ("education", "formation", "academic background", "études", "etudes"),
    "experience": ("experience", "expérience", "work experience", "professional experience"),
    "languages": ("languages", "langues"),
    "projects": ("projects", "projets", "personal projects"),
    "certifications": ("certifications", "certificates", "certificats"),
}


def extract_profile_fields(text):
    """Extract reviewable structured fields from CV text without inventing data."""
    text = str(text or "").replace("\r", "\n")
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    result = {key: "" for key in (*SECTION_ALIASES, "email", "phone", "linkedin", "github")}
    result["email"] = next(iter(re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)), "")
    phone = re.search(r"(?:\+?\d[\d\s().-]{7,}\d)", text)
    result["phone"] = phone.group(0).strip() if phone else ""
    linkedin = re.search(r"https?://(?:www\.)?linkedin\.com/[^\s]+", text, re.I)
    github = re.search(r"https?://(?:www\.)?github\.com/[^\s]+", text, re.I)
    result["linkedin"] = linkedin.group(0).rstrip(".,;)") if linkedin else ""
    result["github"] = github.group(0).rstrip(".,;)") if github else ""

    alias_lookup = {
        alias.casefold(): field for field, aliases in SECTION_ALIASES.items() for alias in aliases
    }
    current = None
    sections = {field: [] for field in SECTION_ALIASES}
    for line in lines:
        heading = re.sub(r"[:\-–—]+$", "", line).strip().casefold()
        if heading in alias_lookup:
            current = alias_lookup[heading]
            continue
        if current:
            sections[current].append(line)
    for field, values in sections.items():
        result[field] = "\n".join(values).strip()

    if not result["skills"]:
        known = (
            "Python", "Java", "JavaScript", "TypeScript", "React", "Angular", "Vue", "SQL",
            "Excel", "Power BI", "Tableau", "Machine Learning", "Data Analysis", "Data Science",
            "Docker", "Kubernetes", "AWS", "Azure", "Google Cloud", "Git", "Linux", "HTML", "CSS",
            "Cybersecurity", "Networking", "Communication", "Teamwork", "Project Management",
        )
        result["skills"] = ", ".join(skill for skill in known if re.search(
            r"(?<!\w)" + re.escape(skill) + r"(?!\w)", text, re.I
        ))
    return result
