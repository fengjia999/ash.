from pathlib import Path


def test_legacy_fragment_ui_is_removed():
    root = Path(__file__).resolve().parents[1]
    dashboard = (root / "templates/dashboard.html").read_text()
    for marker in ('id="section-manage"', 'data-section="manage"', 'id="tab-text"'):
        assert marker not in dashboard
    assert 'data-tab="json">完整恢复' in dashboard
    script = (root / "static/js/dashboard.js").read_text()
    assert '/api/fragments' not in script
    assert 'renderFragmentLedger' not in script
