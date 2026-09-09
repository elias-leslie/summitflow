"""Small GitHub adapter for rule-aware publication and revision-specific checks."""
from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import yaml

from .workflow_filters import ordered_match


class GitHubError(RuntimeError):
    """GitHub could not safely complete publication."""


def check_state(checks: list[dict[str, Any]], required: list[dict[str, Any]]) -> str:
    if any(check['state'] == 'failed' for check in checks):
        return 'failed'
    for rule in required:
        matches = [check for check in checks if check['name'] == rule['context'] and (
            rule.get('integration_id') in {None, 0, -1} or check.get('app_id') == rule['integration_id']
        )]
        if not matches or any(check['state'] != 'success' for check in matches):
            return 'pending'
    return 'success' if checks and all(check['state'] == 'success' for check in checks) else 'pending'


class GitHub:
    def __init__(self, repo: Path, name: str):
        self.repo = repo
        self.name = name
        self.push_scope: dict[str, Any] | None = None
        self.pull_number: int | None = None

    def api(self, path: str, *, method: str = 'GET', body: dict[str, Any] | None = None,
            absent_ok: bool = False) -> Any:
        args = ['gh', 'api', f'repos/{self.name}/{path}' if path else f'repos/{self.name}', '--method', method]
        if body is not None:
            args.extend(['--input', '-'])
        try:
            result = subprocess.run(args, cwd=self.repo, input=json.dumps(body) if body is not None else None,
                                    capture_output=True, text=True, check=False, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitHubError(f'GitHub {method} {path} unavailable: {type(exc).__name__}') from exc
        if result.returncode:
            # Only this exact response means classic protection is absent. Auth errors stay errors.
            if absent_ok and 'Branch not protected' in result.stdout and '404' in result.stderr:
                return None
            raise GitHubError(f'GitHub {method} {path}: {result.stderr.strip() or "request failed"}')
        try:
            return json.loads(result.stdout)
        except ValueError as exc:
            raise GitHubError(f'GitHub returned unreadable JSON for {path}') from exc

    def pages(self, path: str, key: str | None = None) -> list[dict[str, Any]]:
        rows = []
        # GitHub lists are intrinsically paginated; refuse silent truncation.
        for page in range(1, 101):
            data = self.api(f'{path}{"&" if "?" in path else "?"}per_page=100&page={page}')
            batch = data[key] if key else data
            rows.extend(batch)
            if len(batch) < 100:
                return rows
        raise GitHubError(f'GitHub pagination limit reached for {path}')

    def protection(self, path: str, *, private: bool, absent_ok: bool = False) -> Any:
        try:
            return self.api(path, absent_ok=absent_ok)
        except GitHubError as exc:
            feature_unavailable = 'Upgrade to GitHub Pro or make this repository public to enable this feature'
            if private and feature_unavailable in str(exc) and 'HTTP 403' in str(exc):
                return None
            raise

    def plan(self) -> dict[str, Any]:
        metadata = self.api('')
        base = metadata['default_branch']
        private = metadata.get('private') is True
        rules = self.protection(f'rules/branches/{quote(base, safe="")}?per_page=100', private=private) or []
        if len(rules) >= 100:
            rules = self.pages(f'rules/branches/{quote(base, safe="")}')
        classic = self.protection(f'branches/{quote(base, safe="")}/protection', private=private, absent_ok=True) or {}
        required = [check for rule in rules if rule['type'] == 'required_status_checks'
                    for check in rule.get('parameters', {}).get('required_status_checks', [])]
        old_checks = classic.get('required_status_checks') or {}
        required.extend({'context': check['context'], 'integration_id': check.get('app_id')}
                        for check in old_checks.get('checks', []))
        required.extend({'context': name} for name in old_checks.get('contexts', [])
                        if not any(check['context'] == name for check in required))
        requires_pr = bool(required or classic.get('required_pull_request_reviews') or
                           any(rule['type'] in {'pull_request', 'merge_queue'} for rule in rules))
        linear = any(rule['type'] == 'required_linear_history' for rule in rules) or bool(
            (classic.get('required_linear_history') or {}).get('enabled'))
        methods = ('squash', 'rebase') if linear else ('merge', 'squash', 'rebase')
        allowed = set(methods)
        for rule in rules:
            if rule['type'] == 'pull_request' and (rule.get('parameters') or {}).get('allowed_merge_methods'):
                allowed.intersection_update(rule['parameters']['allowed_merge_methods'])
        method = next((value for value in methods if value in allowed and metadata.get(f'allow_{value}_merge' if value != 'merge' else 'allow_merge_commit')), None)
        if requires_pr and not method:
            raise GitHubError('No allowed pull request merge method available')
        return {'base': base, 'required': required, 'requires_pr': requires_pr, 'merge_method': method}

    def observe(self, sha: str, required: list[dict[str, Any]], *, event: str = "push", branch: str | None = None) -> dict[str, Any]:
        checks = []
        workflows_for_sha = self.pages(f'actions/runs?head_sha={sha}', 'workflow_runs')
        unrelated = [run for run in workflows_for_sha if run.get('path') == 'dynamic/dependabot/dependabot-updates']
        unrelated_suites = {run['check_suite_id'] for run in unrelated}
        required_names = {check['context'] for check in required}
        runs = self.pages(f'commits/{sha}/check-runs?filter=latest', 'check_runs')
        for run in runs:
            if (run.get('check_suite') or {}).get('id') in unrelated_suites and run['name'] not in required_names:
                continue
            state = 'pending' if run['status'] != 'completed' else (
                'success' if run['conclusion'] in {'success', 'neutral', 'skipped'} else 'failed')
            checks.append({'name': run['name'], 'state': state, 'app_id': (run.get('app') or {}).get('id'),
                           'url': run.get('html_url')})
        statuses = self.pages(f'commits/{sha}/statuses')
        seen = set()
        for status in statuses:  # API returns newest first; superseded failures do not count.
            if status['context'] in seen:
                continue
            seen.add(status['context'])
            checks.append({'name': status['context'], 'state': 'success' if status['state'] == 'success' else (
                'pending' if status['state'] == 'pending' else 'failed'), 'url': status.get('target_url')})
        latest = {}
        for workflow in workflows_for_sha:
            if workflow in unrelated:
                continue
            key = (workflow['workflow_id'], workflow['event'], workflow.get('head_branch'))
            latest.setdefault(key, workflow)
        for workflow in latest.values():
            state = 'pending' if workflow['status'] != 'completed' else (
                'success' if workflow['conclusion'] in {'success', 'neutral', 'skipped'} else 'failed')
            checks.append({'name': f"workflow: {workflow['name']}", 'state': state, 'url': workflow.get('html_url')})
        state = check_state(checks, required)
        if state == 'success' or (not checks and not required):
            workflows = self.pages('actions/workflows', 'workflows')
            # Actions' workflow index can lag a first workflow push. Inspect the
            # immutable commit tree before concluding that no CI applies.
            tree = self.api(f'git/trees/{sha}?recursive=1')
            if tree.get('truncated'):
                raise GitHubError('Cannot establish CI applicability from a truncated commit tree')
            declared = {entry['path'] for entry in tree['tree']
                        if entry['type'] == 'blob' and entry['path'].startswith('.github/workflows/')
                        and entry['path'].count('/') == 2 and entry['path'].endswith(('.yml', '.yaml'))}
            # Deleted YAML can remain in the Actions index; the commit owns its declarations.
            workflows = [workflow for workflow in workflows
                         if not workflow['path'].startswith('.github/workflows/') or workflow['path'] in declared]
            indexed_paths = {workflow['path'] for workflow in workflows}
            workflows.extend({'state': 'active', 'path': path} for path in sorted(declared - indexed_paths))
            applicable = [workflow for workflow in workflows
                          if self.workflow_applies(workflow, sha, event=event, branch=branch,
                                                   changed_paths=(self.push_scope.get("paths") if self.push_scope
                                                                  and event == "push" and self.push_scope.get("sha") == sha
                                                                  and self.push_scope.get("branch") == branch else None))]
            for workflow in applicable:
                path = workflow['path']
                # External managed checks already contribute their check-runs above.
                if not path.startswith('.github/workflows/') and checks:
                    continue
                if not any(run.get('path') == path and run.get('event') == event
                           and (event != 'push' or not branch or run.get('head_branch') == branch)
                           for run in workflows_for_sha):
                    checks.append({'name': f'workflow: {path}', 'state': 'pending'})
            state = check_state(checks, required) if checks or required else 'not_applicable'
        return {'state': state, 'sha': sha, 'checks': checks,
                'unrelated_workflows': [{'name': run['name'], 'url': run.get('html_url'),
                                         'conclusion': run.get('conclusion')} for run in unrelated]}

    def workflow_applies(self, workflow: dict[str, Any], sha: str, *, event: str, branch: str | None,
                         changed_paths: list[str] | None = None) -> bool:
        if workflow['state'] != 'active':
            return False
        path = workflow['path']
        if path.startswith('dynamic/dependabot/'):
            return False
        if not path.startswith('.github/workflows/'):
            return True  # Managed security checks have no user-authored YAML; remain observable.
        data = self.api(f'contents/{quote(path, safe="/")}?ref={sha}')
        try:
            document = yaml.safe_load(base64.b64decode(data['content']).decode())
        except (ValueError, UnicodeError, yaml.YAMLError) as exc:
            raise GitHubError(f'Cannot read workflow triggers for {path}') from exc
        if not isinstance(document, dict):
            raise GitHubError(f'Invalid workflow document: {path}')
        triggers = document.get('on', document.get(True))  # YAML 1.1 treats unquoted on as True.
        if isinstance(triggers, str):
            return triggers == event
        if isinstance(triggers, list):
            return event in triggers
        if not isinstance(triggers, dict) or event not in triggers:
            return False
        filters = triggers[event] or {}
        if branch and isinstance(filters, dict):
            if event == 'push' and ({'tags', 'tags-ignore'} & filters.keys()) and not (
                    {'branches', 'branches-ignore'} & filters.keys()):
                return False
            included = filters.get('branches')
            excluded = filters.get('branches-ignore', [])
            if included and ordered_match(branch, included) is False:
                return False
            if excluded and ordered_match(branch, excluded) is True:
                return False
        if (isinstance(filters, dict) and {'paths', 'paths-ignore'} & filters.keys()
                and event == 'pull_request' and self.pull_number is not None):
            files = self.pages(f'pulls/{self.pull_number}/files')
            current = self.api(f'pulls/{self.pull_number}')
            if current['head']['sha'] == sha and len(files) == current.get('changed_files'):
                changed_paths = sorted({path for file in files for path in
                                        (file['filename'], file.get('previous_filename', file['filename']))})
        if isinstance(filters, dict) and changed_paths is not None and event in {'push', 'pull_request'}:
            included_paths = filters.get('paths')
            excluded_paths = filters.get('paths-ignore')
            if included_paths is not None and all(ordered_match(path, included_paths) is False
                                                  for path in changed_paths):
                return False
            if excluded_paths is not None and all(ordered_match(path, excluded_paths) is True
                                                   for path in changed_paths):
                return False
        return True

    def observe_feature_branch(self, sha: str, required: list[dict[str, Any]], branch: str) -> dict[str, Any]:
        """Observe existing PR triggers without taking ownership of their merge."""
        push = self.observe(sha, required, branch=branch)
        query = urlencode({'state': 'open', 'head': f'{self.name.split("/")[0]}:{branch}'})
        pulls = self.pages(f'pulls?{query}')
        observations = [push]
        pull_results = []
        for pull in pulls:
            if pull['head']['sha'] != sha:
                # PR metadata can lag the branch push too. Never reuse old-head CI.
                evidence = {'state': 'pending', 'checks': [], 'reason': 'pull_request_head_not_updated'}
            else:
                self.pull_number = pull['number']
                evidence = self.observe(sha, required, event='pull_request', branch=pull['base']['ref'])
            observations.append(evidence)
            pull_results.append({'number': pull['number'], 'url': pull['html_url'],
                                 'base': pull['base']['ref'], **evidence})
        state = next((value for value in ('failed', 'unavailable', 'pending')
                      if any(item['state'] == value for item in observations)),
                     'success' if any(item['state'] == 'success' for item in observations) else 'not_applicable')
        return {**push, 'state': state, 'pull_requests': pull_results,
                'checks': [check for item in observations for check in item['checks']]}

    def base_sha(self, base: str) -> str:
        return self.api(f'branches/{quote(base, safe="")}')['commit']['sha']

    def pull_request(self, head: str, base: str, title: str, sha: str) -> dict[str, Any]:
        params = urlencode({'state': 'all', 'head': f'{self.name.split("/")[0]}:{head}', 'base': base})
        pulls = self.api(f'pulls?{params}')
        for pull in pulls:
            if pull['state'] == 'open' or (pull.get('merged_at') and pull['head']['sha'] == sha):
                return pull
        return self.api('pulls', method='POST', body={'head': head, 'base': base, 'title': title,
                        'body': 'Publish verified task changes through the canonical ST workflow.'})

    def finish_pr(self, number: int, sha: str, plan: dict[str, Any]) -> dict[str, Any]:
        self.pull_number = number
        pull = self.api(f'pulls/{number}')
        if pull['head']['sha'] != sha:
            raise GitHubError('Pull request head changed; rerun publication against current revision')
        if pull.get('merged'):
            return {**self.observe(pull['merge_commit_sha'], [], branch=plan['base']),
                    'merge_sha': pull['merge_commit_sha'],
                    'pr_checks': self.observe(sha, plan['required'], event='pull_request', branch=plan['base'])}
        evidence = self.observe(sha, plan['required'], event='pull_request', branch=plan['base'])
        if evidence['state'] not in {'success', 'not_applicable'}:
            return evidence
        merged = self.api(f'pulls/{number}/merge', method='PUT', body={'sha': sha, 'merge_method': plan['merge_method']})
        if not merged.get('merged'):
            raise GitHubError(f'Pull request merge not completed: {merged.get("message", "unknown reason")}')
        # Main-push checks are evidence about a different revision; never reuse PR checks.
        return {**self.observe(merged['sha'], [], branch=plan['base']), 'merge_sha': merged['sha'], 'pr_checks': evidence}
