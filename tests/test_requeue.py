"""requeue: a quarantined draft's documents go back to the inbox and the draft is deleted."""

from __future__ import annotations

from pathlib import Path

import pytest

from archivist.requeue import RequeueError, requeue

DRAFT = """---
type: Runbook
title: Rotating the Pager
status: quarantined
sources:
  - resource: sources/quarantine/pager.md
    title: pager notes
  - resource: sources/quarantine/pager-followup.md
    title: follow-up
okfx_quarantine: {reason: no owner, needs: a teams entry}
---
"""


@pytest.fixture
def draft(handbook: Path) -> Path:
    for name in ("pager.md", "pager-followup.md"):
        (handbook / "sources/quarantine").mkdir(parents=True, exist_ok=True)
        (handbook / "sources/quarantine" / name).write_text(name, encoding="utf-8")
    path = handbook / "quarantine/pager.md"
    path.parent.mkdir()
    path.write_text(DRAFT, encoding="utf-8")
    return path


def test_requeue_moves_every_cited_document_back_and_deletes_the_draft(handbook: Path, draft: Path) -> None:
    result = requeue(draft)
    assert result.draft == "quarantine/pager.md"
    assert not draft.exists()
    assert (handbook / "sources/inbox/pager.md").read_text(encoding="utf-8") == "pager.md"
    assert (handbook / "sources/inbox/pager-followup.md").is_file()
    assert not any((handbook / "sources/quarantine").iterdir())


def test_requeue_refuses_anything_but_a_quarantined_draft(handbook: Path, draft: Path) -> None:
    readme = handbook / "quarantine/README.md"
    readme.write_text("# Quarantine\n", encoding="utf-8")
    with pytest.raises(RequeueError, match="not a quarantined draft"):
        requeue(readme)
    concept = handbook / "knowledge/x.md"
    concept.parent.mkdir()
    concept.write_text(DRAFT, encoding="utf-8")
    with pytest.raises(RequeueError, match="not a quarantined draft"):
        requeue(concept)
    draft.write_text(DRAFT.replace("status: quarantined", "status: draft"), encoding="utf-8")
    with pytest.raises(RequeueError, match="does not have `status: quarantined`"):
        requeue(draft)


def test_requeue_moves_nothing_when_any_document_cannot_go_back(handbook: Path, draft: Path) -> None:
    (handbook / "sources/inbox").mkdir(parents=True, exist_ok=True)
    (handbook / "sources/inbox/pager-followup.md").write_text("newer", encoding="utf-8")
    with pytest.raises(RequeueError, match="already exists"):
        requeue(draft)
    assert draft.is_file() and (handbook / "sources/quarantine/pager.md").is_file()
    draft.write_text(DRAFT.replace("sources/quarantine/pager.md", "sources/processed/pager.md"), encoding="utf-8")
    with pytest.raises(RequeueError, match="not a document in sources/quarantine/"):
        requeue(draft)
