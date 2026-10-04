"""GitHub ordered path patterns; unsupported syntax cannot prove exclusion."""
import re
from typing import Any


def pattern_match(value: str, pattern: str) -> bool | None:
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == '*':
            if pattern[index:index + 2] == '**':
                index += 1
                if pattern[index + 1:index + 2] == '/':
                    parts.append('(?:.*/)?')
                    index += 1
                else:
                    parts.append('.*')
            else:
                parts.append('[^/]*')
        elif char in '?+':
            if not parts or index == 0 or pattern[index - 1] in '*?+':
                return None
            parts[-1] = f'(?:{parts[-1]}){char}'
        elif char == '[':
            end = pattern.find(']', index + 1)
            if end < 0 or not re.fullmatch(r'[a-zA-Z0-9-]+', pattern[index + 1:end]):
                return None
            parts.append(pattern[index:end + 1])
            index = end
        elif char == '\\':
            index += 1
            if index == len(pattern):
                return None
            parts.append(re.escape(pattern[index]))
        else:
            parts.append(re.escape(char))
        index += 1
    try:
        return re.fullmatch(''.join(parts), value) is not None
    except re.error:
        return None


def ordered_match(value: str, patterns: list[str]) -> bool | None:
    if not isinstance(patterns, list):
        return None
    matched: bool | None = False
    for pattern in patterns:
        if not isinstance(pattern, str):
            return None
        negative = pattern.startswith('!')
        hit = pattern_match(value, pattern[1:] if negative else pattern)
        if hit is None:
            matched = None
        elif hit:
            matched = not negative
    return matched


def document_applies(document: dict[Any, Any], *, event: str, branch: str | None,
                     changed_paths: list[str] | None = None) -> bool:
    """Prove exclusion only from supported immutable workflow trigger filters."""
    triggers = document.get('on', document.get(True))
    if isinstance(triggers, str):
        return triggers == event
    if isinstance(triggers, list):
        return event in triggers
    if not isinstance(triggers, dict) or event not in triggers:
        return False
    filters = triggers[event] or {}
    if not isinstance(filters, dict):
        return True
    if branch:
        if event == 'push' and ({'tags', 'tags-ignore'} & filters.keys()) and not (
                {'branches', 'branches-ignore'} & filters.keys()):
            return False
        included = filters.get('branches')
        excluded = filters.get('branches-ignore', [])
        if included and ordered_match(branch, included) is False:
            return False
        if excluded and ordered_match(branch, excluded) is True:
            return False
    if changed_paths is not None and event in {'push', 'pull_request'}:
        included = filters.get('paths')
        excluded = filters.get('paths-ignore')
        if included is not None and all(ordered_match(path, included) is False for path in changed_paths):
            return False
        if excluded is not None and all(ordered_match(path, excluded) is True for path in changed_paths):
            return False
    return True
