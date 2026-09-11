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


def test_check_discussion_preserves_context_and_uses_saved_check_endpoint(monkeypatch, tmp_path):
    import json
    calls = []
    monkeypatch.setattr(learn, 'request', lambda *args: calls.append(args))
    context = {'section':'review', 'attempt_id':'saved-check'}
    path = tmp_path / 'context.json'
    path.write_text(json.dumps(context))
    runner = CliRunner()
    result = runner.invoke(learn.app, ['work', 'tutor', '--record', 'path-test', '--lesson', 'authority',
        '--message', 'The policy was not specified.', '--context-file', str(path)])
    assert result.exit_code == 0, result.output
    assert calls[-1][1]['learning_check'] == context and calls[-1][1]['actor'] == 'agent'
    assert runner.invoke(learn.app, ['check', '--path', 'path-test', '--lesson', 'authority']).exit_code == 0
    assert calls[-1] == ('/api/paths/path-test/lessons/authority/learning-check',)
    assert runner.invoke(learn.app, ['discussion', '--path', 'path-test', '--lesson', 'authority', '--attempt', 'saved-check']).exit_code == 0
    assert calls[-1] == ('/api/paths/path-test/lessons/authority/check-discussion?attempt_id=saved-check',)
