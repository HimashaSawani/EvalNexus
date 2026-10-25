import pytest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
INDEX_HTML = ROOT_DIR / "backend" / "static" / "index.html"


def test_index_html_exists():
    assert INDEX_HTML.exists()
    content = INDEX_HTML.read_text(encoding="utf-8")
    assert len(content) > 10000


def test_real_final_answer_extraction_in_ui():
    """Verify index.html extracts real agent final answer from traces instead of using a static string template."""
    content = INDEX_HTML.read_text(encoding="utf-8")
    # Verify legacy hardcoded string is removed
    assert "'Refund has been registered in the system with status: '" not in content
    # Verify trace extraction logic exists
    assert "t.event_type === 'FINAL_ANSWER'" in content
    assert "finalTrace.result.final_answer" in content


def test_catalog_dynamic_scenario_selection_in_ui():
    """Verify runSingleScenarioFromCatalog dynamically appends unknown scenario options to suiteSelect."""
    content = INDEX_HTML.read_text(encoding="utf-8")
    assert "function runSingleScenarioFromCatalog(ref)" in content
    assert "suiteSelect.appendChild(opt)" in content


def test_status_pill_resets_on_start_polling():
    """Verify startPollingRun immediately resets the status pill to queued to prevent stale status flicker."""
    content = INDEX_HTML.read_text(encoding="utf-8")
    assert "document.getElementById('panelRunStatusPill').className = 'status-pill queued';" in content
    assert "document.getElementById('panelRunStatusPill').textContent = 'QUEUED';" in content
