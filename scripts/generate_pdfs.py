"""PDF generator for Aster Systems knowledge documents.

Converts approved v1 Markdown knowledge documents into searchable, professional
A4 portrait PDF documents using ReportLab. Staging and validation occur before
publishing to the output directory.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import xml.sax.saxutils

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)
import yaml

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.validate_documents import validate_documents


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas that adds running headers and dynamic 'Page X of Y' footers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict] = []
        self._doc_id = ""

    def set_doc_id(self, doc_id: str) -> None:
        self._doc_id = doc_id

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_header_footer(num_pages)
            super().showPage()
        super().save()

    def draw_header_footer(self, page_count: int) -> None:
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#555555"))

        # Running header (pages > 1)
        if self._pageNumber > 1:
            header_text = f"Aster Systems — {self._doc_id}" if self._doc_id else "Aster Systems"
            self.drawString(20 * mm, 297 * mm - 15 * mm, header_text)
            self.setStrokeColor(colors.HexColor("#CCCCCC"))
            self.setLineWidth(0.5)
            self.line(20 * mm, 297 * mm - 16 * mm, 210 * mm - 20 * mm, 297 * mm - 16 * mm)

        # Running footer (all pages)
        self.drawString(20 * mm, 12 * mm, "Aster Systems Internal Documentation")
        self.drawRightString(210 * mm - 20 * mm, 12 * mm, f"Page {self._pageNumber} of {page_count}")
        self.setStrokeColor(colors.HexColor("#CCCCCC"))
        self.setLineWidth(0.5)
        self.line(20 * mm, 15 * mm, 210 * mm - 20 * mm, 15 * mm)
        self.restoreState()


def load_source_document(
    file_path: Path,
) -> tuple[dict, str, list[tuple[str, list[str]]]]:
    """Parse Markdown front matter, H1 title, and 6 sections with paragraphs."""
    content = file_path.read_text(encoding="utf-8").lstrip("\ufeff")
    fm_match = re.match(r"^---\r?\n(.*?)\r?\n---(?:\r?\n(.*))?$", content, re.DOTALL)
    if not fm_match:
        raise ValueError(f"Missing YAML front matter in {file_path.name}")

    metadata = yaml.safe_load(fm_match.group(1))
    body = fm_match.group(2) or ""

    h1_match = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
    if not h1_match:
        raise ValueError(f"Missing H1 title in {file_path.name}")
    doc_title = h1_match.group(1).strip()

    raw_sections = re.split(r"^##\s+(.+)$", body, flags=re.MULTILINE)
    if len(raw_sections) != 13:
        raise ValueError(
            f"Expected exactly 6 sections in {file_path.name}, got {(len(raw_sections)-1)//2}"
        )

    sections: list[tuple[str, list[str]]] = []
    for i in range(1, len(raw_sections), 2):
        sec_title = raw_sections[i].strip()
        sec_content = raw_sections[i + 1].strip()
        marker_match = re.search(r"<!--\s*fact_id:\s*([A-Za-z0-9_]+)\s*-->", sec_content)
        if marker_match:
            p1 = sec_content[: marker_match.start()].strip()
            p2 = sec_content[marker_match.end() :].strip()
            paras = [p for p in [p1, p2] if p]
        else:
            paras = [p.strip() for p in re.split(r"\r?\n\s*\r?\n", sec_content) if p.strip()]
        sections.append((sec_title, paras))

    return metadata, doc_title, sections


def build_pdf(
    dest_path: Path,
    metadata: dict,
    doc_title: str,
    sections: list[tuple[str, list[str]]],
) -> None:
    """Generate a single formatted A4 portrait PDF document."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    doc_id = str(metadata.get("document_id", "")).strip()
    raw_dept = str(metadata.get("owner_department", "")).strip()
    dept_display = raw_dept.replace("_", " ").title()
    classification_display = str(metadata.get("classification", "")).strip().title()

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#111827"),
        spaceAfter=6,
    )
    meta_style = ParagraphStyle(
        "DocMeta",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#4B5563"),
    )
    h2_style = ParagraphStyle(
        "SecHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#1F2937"),
        spaceBefore=8,
        spaceAfter=3,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "BodyTextCustom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#1F2937"),
        spaceAfter=5,
    )

    doc = SimpleDocTemplate(
        str(dest_path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        title=doc_title,
        author="Aster Systems",
        subject=f"{doc_id} v1",
    )

    story = []

    # Company label
    company_style = ParagraphStyle(
        "CompanyHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#4B5563"),
        spaceAfter=3,
    )
    story.append(Paragraph("<b>Aster Systems</b>", company_style))

    # Document title
    story.append(Paragraph(xml.sax.saxutils.escape(doc_title), title_style))

    # Metadata banner
    meta_lines = [
        f"<b>Document ID:</b> {doc_id}",
        "<b>Version:</b> v1",
        f"<b>Department:</b> {dept_display}",
        f"<b>Classification:</b> {classification_display}",
        "<b>Effective Date:</b> 2026-11-01",
    ]
    story.append(Paragraph(" &nbsp;&nbsp;|&nbsp;&nbsp; ".join(meta_lines), meta_style))
    story.append(Spacer(1, 3))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#D1D5DB"), spaceAfter=6))

    # Sections and body paragraphs
    for sec_title, paras in sections:
        story.append(Paragraph(xml.sax.saxutils.escape(sec_title), h2_style))
        for para in paras:
            story.append(Paragraph(xml.sax.saxutils.escape(para), body_style))

    class DocCanvas(NumberedCanvas):
        def __init__(self, *args, **kwargs):
            kwargs["invariant"] = 1
            super().__init__(*args, **kwargs)
            self.set_doc_id(doc_id)

    doc.build(story, canvasmaker=DocCanvas)


def _get_temp_dir_on_same_volume(target_dir: Path, prefix: str) -> Path:
    """Create a temporary directory outside the repository on the same volume as target_dir."""
    resolved_target = target_dir.resolve()
    drive = resolved_target.anchor
    sys_temp = Path(tempfile.gettempdir()).resolve()

    if sys_temp.anchor.lower() == drive.lower() and not sys_temp.is_relative_to(PROJECT_ROOT):
        base_temp = sys_temp
    else:
        base_temp = Path(drive) / "temp"
        base_temp.mkdir(parents=True, exist_ok=True)

    return Path(tempfile.mkdtemp(prefix=prefix, dir=base_temp))


APPROVED_DEPARTMENTS = {
    "engineering",
    "it_support",
    "people_operations",
    "finance_operations",
}


def inspect_destination_for_unexpected_entries(
    output_dir: Path, expected_rel_paths: set[Path]
) -> list[str]:
    """Inspect output_dir and return a list of unexpected relative paths (files, dirs, symlinks).
    Does not follow symlinks or junctions.
    """
    if not output_dir.exists():
        return []

    unexpected: list[str] = []

    if output_dir.is_symlink():
        return [output_dir.name]

    for root, dirs, files in os.walk(str(output_dir), followlinks=False):
        root_path = Path(root)
        try:
            rel_root = root_path.relative_to(output_dir)
        except ValueError:
            continue

        if rel_root != Path(".") and root_path.is_symlink():
            unexpected.append(rel_root.as_posix())
            dirs.clear()
            continue

        if rel_root == Path("."):
            for d in dirs:
                dir_path = root_path / d
                if dir_path.is_symlink() or d not in APPROVED_DEPARTMENTS:
                    unexpected.append(Path(d).as_posix())
            for f in files:
                unexpected.append(Path(f).as_posix())
        elif len(rel_root.parts) == 1:
            dept = rel_root.parts[0]
            if dept in APPROVED_DEPARTMENTS:
                for d in dirs:
                    unexpected.append((rel_root / d).as_posix())
                for f in files:
                    rel_f = rel_root / f
                    if (root_path / f).is_symlink() or rel_f not in expected_rel_paths:
                        unexpected.append(rel_f.as_posix())
            else:
                for d in dirs:
                    unexpected.append((rel_root / d).as_posix())
                for f in files:
                    unexpected.append((rel_root / f).as_posix())
        else:
            for d in dirs:
                unexpected.append((rel_root / d).as_posix())
            for f in files:
                unexpected.append((rel_root / f).as_posix())

    return sorted(set(unexpected))


def validate_output_destination_path(output_path: Path) -> None:
    """Validate that output_path is either absent or an ordinary directory.

    Rejects regular files, symbolic links (valid or broken), directory junctions,
    reparse points, and non-directories before any inspection, staging, or publication.
    Never alters, moves, or deletes rejected objects.
    """
    try:
        st = output_path.lstat()
    except FileNotFoundError:
        # Genuinely absent path is accepted
        return
    except OSError as err:
        if not output_path.exists(follow_symlinks=False):
            return
        raise RuntimeError(
            f"Refusing publication: unable to inspect output path '{output_path}': {err}"
        ) from err

    # Check for symbolic links (valid or broken)
    if output_path.is_symlink():
        raise RuntimeError(
            f"Refusing publication: output path '{output_path}' is an unsafe symbolic link"
        )

    # Check for Windows directory junctions
    is_junc = False
    if hasattr(output_path, "is_junction"):
        try:
            is_junc = output_path.is_junction()
        except Exception:
            pass
    if not is_junc and hasattr(os.path, "isjunction"):
        try:
            is_junc = os.path.isjunction(str(output_path))
        except Exception:
            pass
    if is_junc:
        raise RuntimeError(
            f"Refusing publication: output path '{output_path}' is an unsafe directory junction"
        )

    # Check for Windows reparse points
    st_attrs = getattr(st, "st_file_attributes", 0)
    if st_attrs & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
        raise RuntimeError(
            f"Refusing publication: output path '{output_path}' is an unsafe reparse point"
        )

    # Check for regular files
    if stat.S_ISREG(st.st_mode):
        raise RuntimeError(
            f"Refusing publication: output path '{output_path}' is an existing regular file"
        )

    # Must be an ordinary directory
    if not stat.S_ISDIR(st.st_mode):
        raise RuntimeError(
            f"Refusing publication: output path '{output_path}' is not an ordinary directory"
        )


def generate_all_pdfs(
    source_dir_path: Path | str | None = None,
    output_dir_path: Path | str | None = None,
    spec_dir_path: Path | str | None = None,
) -> list[Path]:
    """Validate source Markdown, generate 24 PDFs in staging, validate, and publish safely."""
    # Late import to prevent circular dependency
    from scripts.validate_pdfs import validate_pdfs

    source_dir = Path(source_dir_path) if source_dir_path else PROJECT_ROOT / "data" / "source"
    output_dir = Path(output_dir_path) if output_dir_path else PROJECT_ROOT / "data" / "pdfs"
    spec_dir = Path(spec_dir_path) if spec_dir_path else PROJECT_ROOT / "data" / "spec"

    # Step 1: Pre-generation output path safety check
    validate_output_destination_path(output_dir)

    # Step 2: Pre-generation source validation
    src_errors = validate_documents(source_dir, spec_dir)
    if src_errors:
        raise RuntimeError(
            f"Source document validation failed with {len(src_errors)} error(s):\n"
            + "\n".join(f"  - {err}" for err in src_errors)
        )

    # Step 3: Read document inventory
    inv_file = spec_dir / "document_inventory.csv"
    if not inv_file.exists():
        raise FileNotFoundError(f"Missing inventory file: {inv_file}")

    with open(inv_file, encoding="utf-8") as f:
        inventory = {r["document_id"]: r for r in csv.DictReader(f)}

    if len(inventory) != 24:
        raise ValueError(f"Expected 24 documents in inventory, found {len(inventory)}")

    # Compute expected relative paths
    expected_rel_paths: set[Path] = set()
    for doc_id, meta in inventory.items():
        dept = meta["owner_department"]
        pdf_name = f"{doc_id.lower().replace('-', '_')}_v1.pdf"
        expected_rel_paths.add(Path(dept) / pdf_name)

    # Safety check on destination before touching anything:
    # Refuse unsafe replacement if unexpected files or directories exist in destination
    if output_dir.exists():
        unexpected_entries = inspect_destination_for_unexpected_entries(
            output_dir, expected_rel_paths
        )
        if unexpected_entries:
            raise RuntimeError(
                f"Refusing replacement: destination directory '{output_dir}' contains "
                f"unexpected filesystem entries: {', '.join(unexpected_entries)}"
            )

    # Step 3: Create temporary staging and backup directories on same volume outside repo
    staging_base = _get_temp_dir_on_same_volume(output_dir, prefix="astercite_pdf_staging_")
    staging_dir = staging_base / "staged_corpus"
    backup_base = _get_temp_dir_on_same_volume(output_dir, prefix="astercite_pdf_backup_")
    backup_path = backup_base / "pdfs_backup"

    output_dir_existed = output_dir.exists()
    old_moved_to_backup = False
    staging_moved_to_output = False

    try:
        # Step 4: Generate all 24 PDFs into staging directory
        for doc_id, meta in sorted(inventory.items()):
            dept = meta["owner_department"]
            src_filename = f"{doc_id.lower().replace('-', '_')}.md"
            src_path = source_dir / dept / src_filename
            if not src_path.exists():
                raise FileNotFoundError(f"Source document missing: {src_path}")

            metadata, doc_title, sections = load_source_document(src_path)
            staged_pdf = staging_dir / dept / f"{doc_id.lower().replace('-', '_')}_v1.pdf"
            build_pdf(staged_pdf, metadata, doc_title, sections)

        # Step 5: Validate staged PDFs before publication
        val_errors = validate_pdfs(
            output_dir_path=staging_dir,
            source_dir_path=source_dir,
            spec_dir_path=spec_dir,
        )
        if val_errors:
            raise RuntimeError(
                f"Staged PDF collection failed validation with {len(val_errors)} error(s):\n"
                + "\n".join(f"  - {err}" for err in val_errors)
            )

        # Confirm staging contains exactly the approved PDF paths
        staged_files = {p.relative_to(staging_dir) for p in staging_dir.rglob("*.pdf")}
        if staged_files != expected_rel_paths:
            missing = expected_rel_paths - staged_files
            extra = staged_files - expected_rel_paths
            raise RuntimeError(
                f"Staged collection paths do not match expected inventory (missing: {missing}, extra: {extra})"
            )

        # Step 6: Safe directory swap
        # If output_dir exists, move it to backup_path
        if output_dir_existed:
            os.replace(str(output_dir), str(backup_path))
            old_moved_to_backup = True

        # Move staged directory into output_dir
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(str(staging_dir), str(output_dir))
        staging_moved_to_output = True

        # Step 7: Validate the newly published collection
        post_val_errors = validate_pdfs(
            output_dir_path=output_dir,
            source_dir_path=source_dir,
            spec_dir_path=spec_dir,
        )
        if post_val_errors:
            raise RuntimeError(
                f"Published PDF collection failed validation with {len(post_val_errors)} error(s):\n"
                + "\n".join(f"  - {err}" for err in post_val_errors)
            )

        # Step 8: Clean up backup directory after successful publication
        if backup_base.exists():
            try:
                shutil.rmtree(backup_base)
            except Exception as cleanup_exc:
                print(
                    f"Warning: Failed to clean up backup directory at '{backup_base}': {cleanup_exc}",
                    file=sys.stderr,
                )

        published_paths = [output_dir / rel for rel in sorted(expected_rel_paths)]
        return published_paths

    except Exception as exc:
        rollback_failed = False
        rb_exc_saved = None
        try:
            if staging_moved_to_output:
                if output_dir.exists():
                    shutil.rmtree(output_dir)
            if old_moved_to_backup:
                if output_dir.exists():
                    shutil.rmtree(output_dir)
                os.replace(str(backup_path), str(output_dir))
            elif not output_dir_existed and output_dir.exists():
                shutil.rmtree(output_dir)
        except Exception as rb_exc:
            rollback_failed = True
            rb_exc_saved = rb_exc

        if rollback_failed:
            raise RuntimeError(
                f"Publication failed: {exc}. CRITICAL: Rollback failed ({rb_exc_saved}); "
                f"previous collection preserved at '{backup_path}'"
            ) from exc

        if old_moved_to_backup:
            try:
                if backup_base.exists():
                    shutil.rmtree(backup_base)
            except Exception as b_rem_exc:
                print(
                    f"Warning: Failed to clean up backup base '{backup_base}' after rollback: {b_rem_exc}",
                    file=sys.stderr,
                )

        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"Publication failed: {exc}") from exc

    finally:
        # Clean up temporary staging base directory only; never delete backup_base here
        if staging_base.exists():
            try:
                shutil.rmtree(staging_base)
            except Exception as stage_clean_exc:
                print(
                    f"Warning: Failed to clean up staging directory '{staging_base}': {stage_clean_exc}",
                    file=sys.stderr,
                )


def main() -> int:
    """CLI entrypoint for PDF generation."""
    print("Starting AsterCite v1 PDF generation with mandatory staging and validation...")
    try:
        generated = generate_all_pdfs()
        print(f"Successfully generated and published {len(generated)} searchable v1 PDF documents:")
        for path in generated:
            print(f"  - {path.relative_to(PROJECT_ROOT)}")
        return 0
    except Exception as exc:
        print(f"PDF generation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
