"""Milestone 14.12: export with Pandoc (DOCX and EPUB are built for real; PDF through a stand-in engine)."""

import json
import re
import shutil
import subprocess
import zipfile

import pytest
import yaml
from typer.testing import CliRunner

from bookforge import assemble, cli, export, scenefiles, vcs
from bookforge.bible import store
from bookforge.project import Project
from test_report_assemble_bench import full  # noqa: F401  (fixture)
from test_prose_qc import book  # noqa: F401  (fixture)

needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")


@pytest.fixture
def ready(full):
    """A finished, assembled book with the final checkpoint approved and an export config."""
    assemble.assemble(full)
    full.state.approve_checkpoint("final")
    full.save_state()
    cfg = full.root / "config.yaml"
    cfg.write_text(cfg.read_text() + "export:\n  title: The Harbor Ledger\n  author: A. Writer\n  rights: (c) 2026 A. Writer\n")
    vcs.commit(full.root, "test: export config")
    return Project.open(full.root)


def git(p, *args):
    return subprocess.run(["git", "-C", str(p.root), *args], capture_output=True, text=True).stdout


def pandoc_text(path, fmt):
    return subprocess.run(["pandoc", str(path), "-t", "plain", "--wrap=none"], capture_output=True, text=True).stdout


# ── the source ──────────────────────────────────────────────────────────────

def test_matter_is_added_around_the_manuscript_in_file_order(ready):
    for where, name, text in (("front", "02-dedication.md", "For the clerk."), ("front", "01-epigraph.md", "An epigraph."), ("back", "01-thanks.md", "Thanks to all.")):
        (ready.book_dir / "matter" / where).mkdir(parents=True, exist_ok=True)
        (ready.book_dir / "matter" / where / name).write_text(text)
    src = export.build_source(ready)
    assert src.index("An epigraph.") < src.index("For the clerk.") < src.index("# Act 1") < src.index("Thanks to all.")


def test_metadata_falls_back_with_a_warning_and_maps_the_language(full):
    warnings = []
    meta = export.metadata(full, warnings)
    assert meta["title"] == "Series" and meta["lang"] == "en" and "export.title is not set" in warnings[0]
    assert export.language_code("German") == "de" and export.language_code("fr") == "fr" and export.language_code("Klingon") == "en"


def test_no_manuscript_means_no_export(full):
    full.state.approve_checkpoint("final") if full.state.checkpoints["final"].status == "waiting" else None
    with pytest.raises(export.ExportError) as e:
        export.build_source(full)
    assert "assemble" in str(e.value)


# ── the gate ────────────────────────────────────────────────────────────────

@needs_pandoc
def test_an_unapproved_book_exports_only_as_a_draft(full):
    assemble.assemble(full)
    with pytest.raises(export.ExportError) as e:
        export.export_book(Project.open(full.root), ["epub"])
    assert "final checkpoint is not approved" in str(e.value)
    r = export.export_book(Project.open(full.root), ["epub"], draft=True)
    assert r.draft and r.tag.startswith("b1-export-draft-") and r.files[0].endswith("b1-draft.epub")


def test_unknown_format(ready):
    with pytest.raises(export.ExportError):
        export.export_book(ready, ["mobi"])


def test_pandoc_missing_is_a_clear_error(ready, monkeypatch):
    monkeypatch.setattr(export, "find_pandoc", lambda: None)
    with pytest.raises(export.ExportError) as e:
        export.export_book(ready)
    assert "pandoc is not installed" in str(e.value)


# ── real Pandoc output ──────────────────────────────────────────────────────

@needs_pandoc
def test_docx_is_a_manuscript_with_headings_and_centred_scene_breaks(ready):
    r = export.export_book(ready, ["docx"])
    path = ready.root / r.files[0]
    assert path.name == "b1-manuscript.docx" and "docx" not in r.skipped
    text = pandoc_text(path, "docx")
    assert "Act 1" in text and "Chapter 3" in text and "* * *" in text
    with zipfile.ZipFile(path) as z:
        styles, doc = z.read("word/styles.xml").decode(), z.read("word/document.xml").decode()
    flat = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", doc))
    assert "The Harbor LedgerA. Writer" in flat  # the title page: title, then author
    assert "Times New Roman" in styles and 'w:line="480"' in styles and 'w:firstLine="720"' in styles
    assert 'w:styleId="SceneBreak"' in styles and "SceneBreak" in doc and "4F81BD" not in styles.split('w:styleId="Heading1"')[1].split("</w:style>")[0]


@needs_pandoc
def test_epub_has_metadata_chapters_and_scene_breaks(ready):
    r = export.export_book(ready, ["epub"])
    path = ready.root / r.files[0]
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        opf = next(z.read(n).decode() for n in names if n.endswith(".opf"))
        body = " ".join(z.read(n).decode() for n in names if n.endswith(".xhtml"))
        css = " ".join(z.read(n).decode() for n in names if n.endswith(".css"))
    assert "The Harbor Ledger" in opf and "A. Writer" in opf and "<dc:language>en" in opf and "(c) 2026 A. Writer" in opf
    assert 'class="scene-break"' in body and "Chapter 4" in body and "text-indent" in css
    assert sum(n.endswith(".xhtml") for n in names) >= 5  # split by chapter


@needs_pandoc
def test_epub_cover_and_a_missing_cover(ready, tmp_path):
    cfg = ready.root / "config.yaml"
    cfg.write_text(cfg.read_text() + "  cover_image: cover.png\n")
    with pytest.raises(export.ExportError) as e:
        export.export_book(Project.open(ready.root), ["epub"])
    assert "epub: export.cover_image not found" in str(e.value)
    r = export.export_book(Project.open(ready.root), ["epub", "companion"])
    assert "epub" in r.skipped and any(f.endswith("-companion.md") for f in r.files)  # the rest still goes out
    png = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cfc0000003010100c9fe92ef0000000049454e44ae426082")
    (ready.root / "cover.png").write_bytes(png)
    r = export.export_book(Project.open(ready.root), ["epub"])
    with zipfile.ZipFile(ready.root / r.files[0]) as z:
        assert any("cover" in n for n in z.namelist())


@needs_pandoc
def test_a_reference_docx_of_your_own_is_used(ready):
    ref = ready.root / "mine.docx"
    export.make_reference_docx(export.find_pandoc(), ref)
    cfg = ready.root / "config.yaml"
    cfg.write_text(cfg.read_text() + "  reference_docx: mine.docx\n")
    assert export.export_book(Project.open(ready.root), ["docx"]).files
    cfg.write_text(cfg.read_text().replace("mine.docx", "missing.docx"))
    with pytest.raises(export.ExportError):
        export.export_book(Project.open(ready.root), ["docx"])


@needs_pandoc
def test_the_companion_lists_cast_places_rules_timeline_and_outline(ready):
    r = export.export_book(ready, ["companion"])
    md = (ready.root / next(f for f in r.files if f.endswith("-companion.md"))).read_text()
    assert "# Companion to The Harbor Ledger" in md
    assert "### Anna Voss" in md and "- grey eyes" in md and "*physical, through the book:* chapter 2, scene 2: deep cut" in md
    assert "## Places" in md and "### The vestry" in md and "## Rules of the world" in md and "each name crossed out costs a year of memory" in md
    assert "| Day | Time | Scene |" in md and "| 1 | dusk | ch01.s1 |" in md and "### Act 2" in md and "- **Chapter 3.**" in md
    assert "Series ledger" not in md  # the ledger is still empty


def test_a_filled_ledger_appears_in_the_companion(ready):
    (ready.root / "ledger.yaml").write_text(yaml.safe_dump({"open_threads": ["Who bought the boat?"], "end_of_book_states": {"anna": {"wound": "healed"}}}))
    md = export.build_companion(ready, "T")
    assert "## Series ledger" in md and "- Who bought the boat?" in md and "  - **wound**: healed" in md


# ── the PDF (a stand-in engine: only the command is checked) ─────────────────

@pytest.fixture
def fake_engine(monkeypatch):
    class Seen(list):
        headers: list

    seen, headers = Seen(), []

    def run(cmd, cwd=None):
        out = cmd[cmd.index("--output") + 1]
        if out.endswith(".pdf"):
            seen.append(cmd)
            header = next((a.split("=", 1)[1] for a in cmd if a.startswith("--include-in-header=")), None)
            headers.append(open(header).read() if header else "")
            open(out, "wb").write(b"%PDF-fake")
        else:
            real(cmd, cwd)

    real = export._run
    monkeypatch.setattr(export, "_run", run)
    monkeypatch.setattr(export.shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("typst", "pandoc", "xelatex") else None)
    seen.headers = headers
    return seen


def test_pdf_with_typst_sets_the_trim_size_in_the_header(ready, fake_engine):
    r = export.export_book(ready, ["pdf"])
    cmd = fake_engine[0]
    assert "--pdf-engine=typst" in cmd and r.files[0].endswith("b1-print.pdf") and not r.skipped
    assert "width: 6.0in, height: 9.0in, margin: 0.8in" in fake_engine.headers[0] and "first-line-indent" in fake_engine.headers[0]
    assert "--lua-filter" in cmd and "--metadata-file" in cmd


def test_pdf_with_latex_passes_the_geometry(ready, fake_engine, monkeypatch):
    cfg = ready.root / "config.yaml"
    cfg.write_text(cfg.read_text() + "  pdf_engine: xelatex\n  page_width_in: 5.5\n  page_height_in: 8.5\n")
    export.export_book(Project.open(ready.root), ["pdf"])
    cmd = fake_engine[0]
    assert "--pdf-engine=xelatex" in cmd and "geometry:paperwidth=5.5in" in cmd and "geometry:paperheight=8.5in" in cmd and "documentclass=book" in cmd


@needs_pandoc
def test_without_a_pdf_engine_the_pdf_is_skipped_and_the_rest_is_made(ready, monkeypatch):
    real = shutil.which
    monkeypatch.setattr(export.shutil, "which", lambda n: None if n in export.PDF_ENGINES else real(n))
    r = export.export_book(ready, ["pdf", "docx", "companion"])
    assert "no PDF engine installed" in r.skipped["pdf"] and "companion-pdf" in r.skipped
    assert sorted(f.rsplit("/", 1)[-1] for f in r.files) == ["b1-companion.md", "b1-manuscript.docx"]


@needs_pandoc
def test_nothing_made_is_an_error_and_leaves_no_folder_or_tag(ready, monkeypatch):
    real = shutil.which
    monkeypatch.setattr(export.shutil, "which", lambda n: None if n in export.PDF_ENGINES else real(n))
    with pytest.raises(export.ExportError) as e:
        export.export_book(ready, ["pdf"])
    assert "nothing was exported" in str(e.value)
    assert not (ready.book_dir / "exports").exists() or not list((ready.book_dir / "exports").iterdir())
    assert not [t for t in vcs.list_tags(ready.root) if "export" in t]


# ── git and the record ──────────────────────────────────────────────────────

@needs_pandoc
def test_an_export_is_tagged_recorded_and_not_kept_in_git(ready):
    r = export.export_book(ready, ["docx", "companion"])
    assert r.tag.startswith("b1-export-20") and r.tag in vcs.list_tags(ready.root)
    assert r.sha256 in git(ready, "tag", "-n1", r.tag)
    rec = json.loads((ready.root / r.directory / "export.json").read_text())
    assert rec["manuscript_sha256"] == r.sha256 and rec["formats"] == ["docx", "companion"] and rec["metadata"]["title"] == "The Harbor Ledger"
    assert rec["commit"] == git(ready, "rev-list", "-n1", r.tag).strip()
    assert "books/*/exports/" in (ready.root / ".gitignore").read_text() and git(ready, "status", "--porcelain").strip() == ""
    again = export.export_book(ready, ["companion"])
    assert again.tag == r.tag + "-2"


@needs_pandoc
def test_edits_to_the_manuscript_are_committed_before_the_tag_and_warned_about(ready):
    path = assemble.manuscript_path(ready)
    path.write_text(path.read_text().replace("Chapter 1", "Chapter One"))
    r = export.export_book(ready, ["companion"])
    assert any("differs from what the accepted scenes would assemble" in w for w in r.warnings)
    assert "Chapter One" in git(ready, "show", f"{r.tag}:books/b1/manuscript.md")


@needs_pandoc
def test_listing_exports(ready):
    export.export_book(ready, ["companion"])
    [x] = export.list_exports(ready)
    assert x["files"] == ["b1-companion.md"] and x["draft"] is False and len(x["sha256"]) == 64


# ── the command ─────────────────────────────────────────────────────────────

@needs_pandoc
def test_the_export_command(ready):
    runner = CliRunner()
    out = runner.invoke(cli.app, ["export", str(ready.root), "-f", "docx", "-f", "companion"])
    assert out.exit_code == 0, out.output
    assert "b1-manuscript.docx" in out.output and "(tagged b1-export-20" in out.output
    bad = runner.invoke(cli.app, ["export", str(ready.root), "-f", "mobi"])
    assert bad.exit_code == 1 and "unknown format" in bad.output
