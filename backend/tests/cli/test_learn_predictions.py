from typer.testing import CliRunner

from cli.commands import learn


def test_prediction_work_preserves_actual_answer_and_attribution(monkeypatch):
    calls = []
    monkeypatch.setattr(learn, 'request', lambda *args: calls.append(args))
    command_id = '00000000-0000-4000-8000-000000000001'
    result = CliRunner().invoke(learn.app, ['work', 'prediction', '--record', 'path-test', '--lesson', 'authority',
        '--step', '0', '--message', 'The exact learner answer', '--explanation-seen', '--command-id', command_id])
    assert result.exit_code == 0, result.output
    assert calls == [('/api/jobs', {'command_id': command_id, 'kind': 'prediction', 'message': 'The exact learner answer',
        'record_id': 'path-test', 'lesson_id': 'authority', 'step': 0, 'actor': 'agent', 'explanation_seen': True})]


def test_prediction_history_routes_and_step_validation(monkeypatch):
    calls = []
    monkeypatch.setattr(learn, 'request', lambda *args: calls.append(args))
    runner = CliRunner()
    assert runner.invoke(learn.app, ['predictions', '--path', 'path-test', '--lesson', 'authority', '--step', '0']).exit_code == 0
    assert calls == [('/api/paths/path-test/lessons/authority/steps/0/predictions',)]
    assert runner.invoke(learn.app, ['predictions', '--path', 'path-test', '--lesson', 'authority', '--step', '-1']).exit_code != 0
