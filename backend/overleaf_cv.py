"""Fill explicit CV placeholders without extracting or running LaTeX."""
from io import BytesIO
from pathlib import PurePosixPath
import re
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

FIELDS = frozenset("full_name job_title email phone linkedin github location summary experience education skills projects certifications languages".split())
PLACEHOLDER = re.compile(r"\[\[CV:([A-Z_]+)\]\]")
LATEX_ESCAPE = str.maketrans({
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$",
    "&": r"\&", "#": r"\#", "%": r"\%", "_": r"\_",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
})


def fill_template(stream, profile):
    result = BytesIO()
    matched = False

    def replace(match):
        nonlocal matched
        field = match[1].lower()
        if field not in FIELDS:
            raise ValueError(f"Unknown CV placeholder: {match[0]}")
        matched = True
        return " ".join(profile.get(field, "").split()).translate(LATEX_ESCAPE)

    try:
        with ZipFile(BytesIO(stream.read())) as source, ZipFile(result, "w", ZIP_DEFLATED) as output:
            entries = source.infolist()
            if len(entries) > 200 or sum(entry.file_size for entry in entries) > 20 * 1024 * 1024:
                raise ValueError("Use a ZIP with at most 200 files and 20 MB uncompressed.")
            seen = set()
            for entry in entries:
                name = entry.filename
                path = PurePosixPath(name)
                if (path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name
                        or str(path).casefold() in seen or entry.flag_bits & 1):
                    raise ValueError("Use a ZIP with unique, relative filenames and no encryption.")
                seen.add(str(path).casefold())
                if entry.is_dir():
                    continue
                content = source.read(entry)
                if path.suffix.lower() == ".tex":
                    content = PLACEHOLDER.sub(replace, content.decode("utf-8")).encode("utf-8")
                output.writestr(name, content)
    except (BadZipFile, UnicodeError, NotImplementedError, RuntimeError, OSError):
        raise ValueError("Upload a readable Overleaf ZIP with UTF-8 LaTeX files.") from None
    if not matched:
        raise ValueError("Add a TalentSouk placeholder, such as [[CV:FULL_NAME]], to a .tex file first.")
    result.seek(0)
    return result
