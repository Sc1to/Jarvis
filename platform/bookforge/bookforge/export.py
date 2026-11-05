"""Export: the manuscript as DOCX, EPUB and print PDF, and a companion book, with Pandoc.

`manuscript.md` is the single source and stays clean Markdown; everything format-specific happens here,
after assembly. Front and back matter (title page extras, dedication, acknowledgments) are Markdown files
in `books/<book>/matter/front/` and `.../back/`, added in file-name order. The title, author and rights come
from `export:` in the config (Pandoc builds the title page from them).

Each export is a folder `books/<book>/exports/<tag>/` with the files and an `export.json` (what was built, from
which text, with which tools). The folder is not kept in Git (it can be rebuilt from the tagged text); the Git tag
`<book>-export-<date>` marks the exact commit and records the manuscript's hash. An export of a book whose
`final` checkpoint is not approved is only made with `draft=True` and is tagged `<book>-export-draft-<date>`.

Formats: `docx` (manuscript format: Times 12 pt, double spaced, indented paragraphs), `epub` (with the cover and
a small stylesheet), `pdf` (print interior at the configured trim size; engine Typst, XeLaTeX or LuaLaTeX,
whichever is installed), `companion` (a Markdown book of the cast, places, rules, timeline, chapter outline and
series ledger, and its PDF when an engine is installed). Scene breaks are centred asterisks in every format.
"""

import hashlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import assemble, vcs
from .bible import store
from .bible.positions import parse_position
from .errors import BookforgeError
from .project import Project

log = logging.getLogger("platform_bookforge.export")

FORMATS = ("docx", "epub", "pdf", "companion")
DATA_DIR = Path(__file__).resolve().parent / "data"
LANGUAGES = {"english": "en", "german": "de", "french": "fr", "spanish": "es", "italian": "it", "dutch": "nl",
             "portuguese": "pt", "swedish": "sv", "norwegian": "nb", "danish": "da", "finnish": "fi", "polish": "pl"}
PDF_ENGINES = ("typst", "xelatex", "lualatex")
TIMEOUT_SECONDS = 600


class ExportError(BookforgeError):
    pass


@dataclass
class ExportResult:
    name: str
    directory: str  # relative to the series
    files: list[str] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)  # format -> why it was not made
    warnings: list[str] = field(default_factory=list)
    tag: str | None = None
    sha256: str = ""
    draft: bool = False


# ── tools ─────────────────────────────────────────────────────────────────────

def find_pandoc() -> str | None:
    return shutil.which("pandoc")


def find_pdf_engine(project: Project) -> str | None:
    wanted = project.config.export.pdf_engine
    for engine in (PDF_ENGINES if wanted == "auto" else (wanted,)):
        if shutil.which(engine):
            return engine
    return None


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, cwd=cwd)
    except FileNotFoundError as e:
        raise ExportError(f"{cmd[0]} is not installed") from e
    except subprocess.TimeoutExpired as e:
        raise ExportError(f"{cmd[0]} did not finish within {TIMEOUT_SECONDS} s") from e
    if proc.returncode != 0:
        raise ExportError(f"{cmd[0]} failed: {(proc.stderr or proc.stdout).strip()[:600]}")


def pandoc_version() -> str:
    pandoc = find_pandoc()
    if not pandoc:
        return ""
    try:
        return subprocess.run([pandoc, "--version"], capture_output=True, text=True, timeout=30).stdout.splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""


# ── the source ────────────────────────────────────────────────────────────────

def matter_files(project: Project, where: str) -> list[Path]:
    d = project.book_dir / "matter" / where
    return sorted(p for p in d.glob("*.md") if p.is_file()) if d.is_dir() else []


def language_code(language: str) -> str:
    low = language.strip().lower()
    return LANGUAGES.get(low) or (low if re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]+)?", low) else "en")


def metadata(project: Project, warnings: list[str] | None = None) -> dict:
    cfg = project.config.export
    title = cfg.title.strip()
    if not title:
        title = project.root.name.replace("-", " ").replace("_", " ").title()
        if warnings is not None:
            warnings.append(f"export.title is not set; the series folder's name is used ({title!r})")
    meta = {"title": title, "lang": language_code(project.config.book.language), "date": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
    for key in ("subtitle", "author", "rights"):
        if getattr(cfg, key).strip():
            meta[key] = getattr(cfg, key).strip()
    return meta


def build_source(project: Project) -> str:
    """Front matter, the manuscript, back matter: the text every format is built from."""
    path = assemble.manuscript_path(project)
    if not path.is_file():
        raise ExportError("there is no manuscript yet: run `assemble` first")
    parts = [p.read_text(encoding="utf-8").strip() for p in matter_files(project, "front")]
    parts.append(path.read_text(encoding="utf-8").strip())
    parts += [p.read_text(encoding="utf-8").strip() for p in matter_files(project, "back")]
    return "\n\n".join(parts) + "\n"


# ── the companion book ────────────────────────────────────────────────────────

def _bullets(value, indent: int = 0) -> list[str]:
    pad = "  " * indent
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                out += [f"{pad}- **{k}**:"] + _bullets(v, indent + 1)
            else:
                out.append(f"{pad}- **{k}**: {v if v not in (None, '', [], {}) else '(none)'}")
        return out
    if isinstance(value, list):
        out = []
        for v in value:
            out += _bullets(v, indent) if isinstance(v, (dict, list)) else [f"{pad}- {v}"]
        return out
    return [f"{pad}- {value}"]


def _cell(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def build_companion(project: Project, title: str) -> str:
    constants = store.load_constants(project)
    tracks = store.load_tracks(project)
    chapters = store.load_chapters(project) if store.chapters_path(project).exists() else []
    acts = store.load_acts(project) if store.acts_path(project).exists() else []
    scenes = store.load_scenes(project) if store.scenes_path(project).exists() else []
    timeline = store.load_timeline(project)
    names = {e.id: e.name for e in constants.entities}
    chapter_title = {c.id: c.title for c in chapters}

    def where(pos: str) -> str:
        p = parse_position(pos)
        return f"chapter {p.chapter}" + (f", scene {p.scene}" if p.is_scene else "")

    out = [f"# Companion to {title}", "", "Characters, places, rules, timeline and outline, as they stand in the story bible.", ""]
    for heading, kinds in (("Characters", ("character",)), ("Places", ("place",)), ("Objects, groups and ideas", ("object", "group", "concept"))):
        found = [e for e in constants.entities if e.kind in kinds]
        if not found:
            continue
        out += [f"## {heading}", ""]
        for e in found:
            out += [f"### {e.name}", ""] + [f"- {f}" for f in e.facts]
            mine = [t for t in tracks if t.entity == e.id]
            for t in mine:
                out.append(f"- *{t.kind}, through the book:* " + "; ".join(f"{where(x.from_)}: {x.value}" for x in t.plan))
            out.append("")
    if constants.rules:
        out += ["## Rules of the world", ""] + [f"- {r.text}" for r in constants.rules] + [""]
    if timeline:
        out += ["## Timeline", "", "| Day | Time | Scene | Chapter | Viewpoint | Place |", "|---|---|---|---|---|---|"]
        by_scene = {s.id: s for s in scenes}
        for t in timeline:
            s = by_scene.get(t.id)
            out.append(f"| {t.day}{' (flashback)' if t.flashback else ''} | {_cell(t.time)} | {t.id.split('.', 1)[-1]} | "
                       f"{_cell(chapter_title.get(s.chapter if s else '', ''))} | {_cell(names.get(s.pov, '') if s else '')} | {_cell(names.get(s.setting, '') if s else '')} |")
        out.append("")
    if chapters:
        out += ["## Outline", ""]
        by_act = {a.id: a for a in acts}
        current = None
        for c in chapters:
            if c.act != current and c.act in by_act:
                out += [f"### {by_act[c.act].title}", "", by_act[c.act].summary, ""]
                current = c.act
            out.append(f"- **{c.title}.** {c.summary}")
        out.append("")
    ledger_path = project.root / "ledger.yaml"
    try:
        ledger = yaml.safe_load(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else None
    except (OSError, yaml.YAMLError):
        ledger = None
    if isinstance(ledger, dict) and any(ledger.values()):
        out += ["## Series ledger", ""] + _bullets(ledger) + [""]
    return "\n".join(out).rstrip() + "\n"


# ── Word: the manuscript format ───────────────────────────────────────────────

_TIMES = '<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman" w:eastAsia="Times New Roman" />'


def _restyle(styles: str) -> str:
    """Pandoc's default reference.docx made into a standard manuscript: Times 12 pt, double spaced, indented paragraphs."""
    styles = re.sub(r"(<w:rPrDefault>\s*<w:rPr>\s*)<w:rFonts [^>]*/>", lambda m: m.group(1) + _TIMES, styles, count=1)

    def edit(style_id: str, fn) -> None:
        nonlocal styles
        styles = re.sub(rf'(<w:style [^>]*w:styleId="{style_id}".*?</w:style>)', lambda m: fn(m.group(1)), styles, count=1, flags=re.S)

    edit("BodyText", lambda s: re.sub(r"<w:spacing [^>]*/>", '<w:spacing w:before="0" w:after="0" w:line="480" w:lineRule="auto" /><w:ind w:firstLine="720" />', s, count=1))
    edit("FirstParagraph", lambda s: s.replace("</w:style>", '<w:pPr><w:ind w:firstLine="0" /></w:pPr></w:style>'))
    for heading in ("Heading1", "Heading2", "Title", "Subtitle", "Author", "Date"):
        edit(heading, lambda s: re.sub(r"<w:color [^>]*/>", '<w:color w:val="000000" />',
                                       re.sub(r"<w:rFonts [^>]*/>", _TIMES, s)))
    scene_break = ('<w:style w:type="paragraph" w:customStyle="1" w:styleId="SceneBreak"><w:name w:val="SceneBreak" /><w:basedOn w:val="Normal" />'
                   '<w:qFormat /><w:pPr><w:spacing w:before="240" w:after="240" w:line="480" w:lineRule="auto" /><w:jc w:val="center" /></w:pPr></w:style>')
    return styles.replace("</w:styles>", scene_break + "</w:styles>")


def make_reference_docx(pandoc: str, out: Path) -> None:
    raw = subprocess.run([pandoc, "--print-default-data-file", "reference.docx"], capture_output=True, timeout=60)
    if raw.returncode != 0 or not raw.stdout:
        raise ExportError("pandoc could not produce its default reference.docx")
    base = out.with_suffix(".base.docx")
    base.write_bytes(raw.stdout)
    with zipfile.ZipFile(base) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/styles.xml":
                data = _restyle(data.decode("utf-8")).encode("utf-8")
            zout.writestr(item, data)
    base.unlink()


# ── the formats ───────────────────────────────────────────────────────────────

def _typst_header(project: Project) -> str:
    c = project.config.export
    return (f"#set page(width: {c.page_width_in}in, height: {c.page_height_in}in, margin: {c.margin_in}in)\n"
            f"#set text(size: {c.font_size_pt}pt)\n#set par(justify: true, first-line-indent: 1.2em, leading: 0.7em, spacing: 0.7em)\n")


def _pdf_args(project: Project, engine: str, work: Path) -> list[str]:
    c = project.config.export
    if engine == "typst":
        header = work / "typst-header.typ"
        header.write_text(_typst_header(project), encoding="utf-8")
        return ["--pdf-engine=typst", f"--include-in-header={header}"]
    return [f"--pdf-engine={engine}", "--top-level-division=part", "-V", "documentclass=book", "-V", "indent=true",
            "-V", f"fontsize={int(round(c.font_size_pt))}pt",
            "-V", f"geometry:paperwidth={c.page_width_in}in", "-V", f"geometry:paperheight={c.page_height_in}in",
            "-V", f"geometry:margin={c.margin_in}in"]


def _pandoc(pandoc: str, source: Path, out: Path, meta: Path, fmt: str, extra: list[str], cwd: Path) -> None:
    cmd = [pandoc, str(source), "--from", "markdown+smart", "--to", fmt, "--output", str(out), "--metadata-file", str(meta),
           "--lua-filter", str(DATA_DIR / "scene-break.lua"), "--standalone", *extra]
    _run(cmd, cwd=cwd)


def _unique_tag(project: Project, base: str) -> str:
    tag, n = base, 1
    while vcs.tag_exists(project.root, tag):
        n += 1
        tag = f"{base}-{n}"
    return tag


def _ensure_ignored(project: Project) -> None:
    path = project.root / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if "books/*/exports/" not in text:
        path.write_text(text.rstrip("\n") + "\nbooks/*/exports/\n", encoding="utf-8")


def export_book(project: Project, formats: list[str] | None = None, draft: bool = False) -> ExportResult:
    formats = list(dict.fromkeys(formats or FORMATS))
    unknown = [f for f in formats if f not in FORMATS]
    if unknown:
        raise ExportError(f"unknown format {', '.join(unknown)} (expected: {', '.join(FORMATS)})")
    pandoc = find_pandoc()
    if not pandoc:
        raise ExportError("pandoc is not installed (sudo apt install pandoc)")
    if not draft and project.state.checkpoints["final"].status != "approved":
        raise ExportError("the final checkpoint is not approved: read the manuscript and `approve final`, or export a draft")
    source_text = build_source(project)
    sha = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    warnings: list[str] = []
    meta = metadata(project, warnings)
    try:
        if assemble.build_manuscript(project)[0].strip() != assemble.manuscript_path(project).read_text(encoding="utf-8").strip():
            warnings.append("manuscript.md differs from what the accepted scenes would assemble to (you edited it, or scenes changed since)")
    except BookforgeError as e:
        warnings.append(f"manuscript.md was not checked against the scenes: {e}")

    # the exact text being exported is committed, so the tag marks it
    _ensure_ignored(project)
    if project.config.git.commit_each_step or project.config.git.tag_checkpoints:
        rels = [".gitignore"] + [str(p.relative_to(project.root)) for p in [assemble.manuscript_path(project), *matter_files(project, "front"), *matter_files(project, "back")]]
        vcs.commit(project.root, f"{project.book}: export source ({sha[:8]})", rels)

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    base_tag = f"{project.book}-export-{'draft-' if draft else ''}{date}"
    tag = _unique_tag(project, base_tag)
    out_dir = project.book_dir / "exports" / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    result = ExportResult(name=tag, directory=str(out_dir.relative_to(project.root)), warnings=warnings, sha256=sha, draft=draft)
    stem = project.book if not draft else f"{project.book}-draft"

    with tempfile.TemporaryDirectory(prefix="bookforge-export-") as tmp:
        work = Path(tmp)
        source = work / "source.md"
        source.write_text(source_text, encoding="utf-8")
        meta_file = work / "meta.yaml"
        meta_file.write_text(yaml.safe_dump(meta, allow_unicode=True), encoding="utf-8")

        def made(path: Path) -> None:
            result.files.append(str(path.relative_to(project.root)))

        def attempt(label: str, fn) -> None:
            try:
                fn()
            except ExportError as e:
                result.skipped[label] = str(e)

        if "docx" in formats:
            def docx() -> None:
                ref = project.root / project.config.export.reference_docx if project.config.export.reference_docx else None
                if ref is not None and not ref.is_file():
                    raise ExportError(f"export.reference_docx not found: {ref}")
                if ref is None:
                    ref = work / "reference.docx"
                    make_reference_docx(pandoc, ref)
                out = out_dir / f"{stem}-manuscript.docx"
                _pandoc(pandoc, source, out, meta_file, "docx", [f"--reference-doc={ref}", "--top-level-division=part"], work)
                made(out)
            attempt("docx", docx)

        if "epub" in formats:
            def epub() -> None:
                extra = ["--toc", "--split-level=2", f"--css={DATA_DIR / 'epub.css'}", "--top-level-division=part"]
                cover = project.config.export.cover_image
                if cover:
                    cover_path = project.root / cover
                    if not cover_path.is_file():
                        raise ExportError(f"export.cover_image not found: {cover_path}")
                    extra.append(f"--epub-cover-image={cover_path}")
                out = out_dir / f"{stem}.epub"
                _pandoc(pandoc, source, out, meta_file, "epub3", extra, work)
                made(out)
            attempt("epub", epub)

        engine = find_pdf_engine(project)
        if "pdf" in formats:
            def pdf() -> None:
                if engine is None:
                    raise ExportError("no PDF engine installed (typst, xelatex or lualatex), or the configured one is missing")
                out = out_dir / f"{stem}-print.pdf"
                _pandoc(pandoc, source, out, meta_file, "pdf", _pdf_args(project, engine, work), work)
                made(out)
            attempt("pdf", pdf)

        if "companion" in formats:
            def companion() -> None:
                md = out_dir / f"{stem}-companion.md"
                md.write_text(build_companion(project, meta["title"]), encoding="utf-8")
                made(md)
                if engine is None:
                    result.skipped["companion-pdf"] = "no PDF engine installed; the Markdown companion was written"
                    return
                out = out_dir / f"{stem}-companion.pdf"
                _pandoc(pandoc, md, out, meta_file, "pdf", _pdf_args(project, engine, work), work)
                made(out)
            attempt("companion", companion)

    if not result.files:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise ExportError("nothing was exported: " + "; ".join(f"{k}: {v}" for k, v in result.skipped.items()))

    (out_dir / "export.json").write_text(json.dumps({
        "name": tag, "draft": draft, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "manuscript_sha256": sha,
        "commit": vcs.head_sha(project.root), "formats": formats, "files": [Path(f).name for f in result.files], "skipped": result.skipped,
        "warnings": warnings, "pandoc": pandoc_version(), "pdf_engine": engine, "metadata": meta}, indent=2, ensure_ascii=False), encoding="utf-8")
    if project.config.git.tag_checkpoints:
        vcs.tag(project.root, tag, f"{project.book} export{' (draft)' if draft else ''}: {', '.join(Path(f).name for f in result.files)}; manuscript sha256 {sha}")
        result.tag = tag
    return result


def list_exports(project: Project) -> list[dict]:
    d = project.book_dir / "exports"
    out = []
    for p in sorted(d.iterdir(), reverse=True) if d.is_dir() else []:
        try:
            rec = json.loads((p / "export.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"name": p.name, "draft": rec.get("draft", False), "created": rec.get("created"), "files": rec.get("files", []),
                    "skipped": rec.get("skipped", {}), "warnings": rec.get("warnings", []), "sha256": rec.get("manuscript_sha256", "")})
    return out
