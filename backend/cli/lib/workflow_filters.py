"""GitHub ordered path patterns; unsupported syntax cannot prove exclusion."""
import re


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
