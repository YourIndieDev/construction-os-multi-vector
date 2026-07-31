"""Create an idempotent Test project and PDF source for Phase 5 verification."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
from pathlib import Path

from construction_os.config import UPLOADS_FOLDER
from construction_os.domain.project import Asset, Project, Source

PROJECT_NAME = "Test"
SOURCE_TITLE = "Page_001_P001.pdf"
PROJECT_DESCRIPTION = (
    "Deterministic multi-vector verification project using the GEN Korean BBQ "
    "House P001 plumbing cover and sheet-index drawing."
)
SOURCE_TEXT = (
    "GEN Korean BBQ House, sheet P001, General Notes, Codes and Sheet Index. "
    "Project 24-079 at 75-971 Henry Street, Kailua-Kona, Hawaii."
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_fixture(source_path: Path) -> Path:
    if not source_path.is_file():
        raise FileNotFoundError(f"Fixture PDF not found: {source_path}")
    if source_path.suffix.lower() != ".pdf":
        raise ValueError(f"Fixture must be a PDF: {source_path}")

    target_dir = Path(UPLOADS_FOLDER) / "phase5-fixture"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / SOURCE_TITLE

    if not target_path.exists() or _sha256(target_path) != _sha256(source_path):
        shutil.copyfile(source_path, target_path)

    if not target_path.is_file() or target_path.stat().st_size < 1:
        raise RuntimeError(f"Fixture copy failed: {target_path}")
    return target_path


async def _get_or_create_project() -> Project:
    projects = await Project.get_all(order_by="updated desc")
    project = next((item for item in projects if item.name.strip() == PROJECT_NAME), None)
    if project is None:
        project = Project(name=PROJECT_NAME, description=PROJECT_DESCRIPTION)
        await project.save()
    elif project.description != PROJECT_DESCRIPTION:
        project.description = PROJECT_DESCRIPTION
        await project.save()
    if not project.id:
        raise RuntimeError("Test project was saved without an ID")
    return project


async def _get_or_create_source(project: Project, pdf_path: Path) -> Source:
    sources = await project.get_sources(include_full_text=True)
    source = next((item for item in sources if (item.title or "") == SOURCE_TITLE), None)

    if source is None:
        source = Source(
            title=SOURCE_TITLE,
            asset=Asset(file_path=str(pdf_path)),
            full_text=SOURCE_TEXT,
            pipeline_stage="completed",
        )
        await source.save()
        if not source.id:
            raise RuntimeError("Fixture source was saved without an ID")
        await source.add_to_project(str(project.id))
    else:
        changed = False
        if source.asset is None or source.asset.file_path != str(pdf_path):
            source.asset = Asset(file_path=str(pdf_path))
            changed = True
        if not source.full_text:
            source.full_text = SOURCE_TEXT
            changed = True
        if source.pipeline_stage != "completed":
            source.pipeline_stage = "completed"
            changed = True
        if changed:
            await source.save()

    if not source.id:
        raise RuntimeError("Fixture source has no ID")

    linked = await project.get_sources()
    if str(source.id) not in {str(item.id) for item in linked}:
        await source.add_to_project(str(project.id))

    return source


async def bootstrap(fixture_path: Path) -> dict[str, object]:
    stored_path = _copy_fixture(fixture_path)
    project = await _get_or_create_project()
    source = await _get_or_create_source(project, stored_path)

    return {
        "project_id": str(project.id),
        "project_name": project.name,
        "source_id": str(source.id),
        "source_title": source.title,
        "file_path": str(stored_path),
        "file_size": stored_path.stat().st_size,
        "file_hash": _sha256(stored_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture_pdf", type=Path)
    args = parser.parse_args()
    result = asyncio.run(bootstrap(args.fixture_pdf))
    print("PHASE5_FIXTURE_JSON=" + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
