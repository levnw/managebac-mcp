import json

from diagnostics import ReportWriter


def test_disabled_writer_creates_nothing(tmp_path):
    target = tmp_path / 'absent'
    assert ReportWriter(target).save({}, {}) is None
    assert not target.exists()


def test_failed_tool_response_preserved(tmp_path):
    payload = {'isError': True, 'structuredContent': {'error': {'code': 'session_expired'}}}
    writer = ReportWriter(tmp_path / 'reports', True)
    result = writer.save({'operation': 'get_classes'}, payload)
    assert result['saved']
    from pathlib import Path
    assert json.loads(Path(result['response_file']).read_text()) == payload


def test_export_failure_is_explicit_without_exception_text(tmp_path):
    target = tmp_path / 'private-name'
    target.write_text('not a directory')
    result = ReportWriter(target, True).save({'operation': 'login'}, {'authenticated': False})
    assert result['saved'] is False
    assert 'private-name' not in result['error']


def test_oversized_report_not_written(tmp_path):
    target = tmp_path / 'reports'
    result = ReportWriter(target, True).save({'operation': 'login'}, {'value': 'a' * 2_000_001})
    assert not result['saved']
    assert not target.exists()


def test_status_makes_a_full_evidence_folder_visible(tmp_path, monkeypatch):
    from diagnostics import ReportWriter
    assert ReportWriter(tmp_path, enabled=False).status() == {'enabled': False}
    writer = ReportWriter(tmp_path / 'reports', enabled=True)
    assert writer.status() == {'enabled': True, 'state': 'ok', 'runs': 0, 'limit': 1000}
    monkeypatch.setattr(ReportWriter, 'MAX_RUNS', 10)
    report = {'operation': 'get_classes'}
    for _ in range(9):
        assert writer.save(report, {'classes': []})['saved']
    assert writer.status()['state'] == 'nearly_full'
    assert writer.save(report, {'classes': []})['saved']
    assert writer.status() == {'enabled': True, 'state': 'full', 'runs': 10, 'limit': 10}
    assert writer.save(report, {'classes': []})['saved'] is False   # stops, never deletes evidence
