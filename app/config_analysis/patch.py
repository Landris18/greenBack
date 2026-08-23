import difflib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Patch:
    file_path: str
    kind: str
    service: str | None
    before: str
    after: str
    unified_diff: str

    def as_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "kind": self.kind,
            "service": self.service,
            "before": self.before,
            "after": self.after,
            "unified_diff": self.unified_diff,
        }


def unified_diff(before: str, after: str, path: str) -> str:
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=path,
        tofile=f"{path} (propose)",
        n=3,
    )
    return "".join(lines)


def build_patch(
    original: str, updated: str, path: str, kind: str, service: str | None = None
) -> Patch:
    before_lines = original.splitlines()
    after_lines = updated.splitlines()
    matcher = difflib.SequenceMatcher(None, before_lines, after_lines)

    before_fragment: list[str] = []
    after_fragment: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        before_fragment.extend(before_lines[i1:i2])
        after_fragment.extend(after_lines[j1:j2])

    return Patch(
        file_path=path,
        kind=kind,
        service=service,
        before="\n".join(before_fragment),
        after="\n".join(after_fragment),
        unified_diff=unified_diff(original, updated, path),
    )


def replace_line(content: str, line_number: int, new_line: str) -> str:
    lines = content.splitlines()
    index = line_number - 1
    if index < 0 or index >= len(lines):
        return content
    lines[index] = new_line
    return "\n".join(lines) + ("\n" if content.endswith("\n") else "")


def insert_after(content: str, line_number: int, new_lines: list[str]) -> str:
    lines = content.splitlines()
    index = max(0, min(line_number, len(lines)))
    lines[index:index] = new_lines
    return "\n".join(lines) + ("\n" if content.endswith("\n") else "")


def find_service_block(content: str, service: str) -> tuple[int, int, str] | None:
    lines = content.splitlines()
    services_index = None
    for position, line in enumerate(lines):
        if re.match(r"^\s*services\s*:\s*$", line):
            services_index = position
            break
    if services_index is None:
        return None

    pattern = re.compile(rf"^(\s+){re.escape(service)}\s*:\s*$")
    start = None
    indent = ""
    for position in range(services_index + 1, len(lines)):
        match = pattern.match(lines[position])
        if match:
            start = position
            indent = match.group(1)
            break
    if start is None:
        return None

    end = len(lines)
    for position in range(start + 1, len(lines)):
        line = lines[position]
        if not line.strip():
            continue
        current_indent = len(line) - len(line.lstrip())
        if current_indent <= len(indent):
            end = position
            break

    return start, end, indent


def find_key_line(content: str, service: str, key: str) -> int | None:
    block = find_service_block(content, service)
    if block is None:
        return None

    start, end, indent = block
    lines = content.splitlines()
    pattern = re.compile(rf"^{re.escape(indent)}\s+{re.escape(key)}\s*:")
    for position in range(start + 1, end):
        if pattern.match(lines[position]):
            return position + 1
    return None


def set_service_key(content: str, service: str, key: str, value: str) -> str:
    existing = find_key_line(content, service, key)
    block = find_service_block(content, service)
    if block is None:
        return content

    start, _, indent = block
    child_indent = f"{indent}  "

    if existing is not None:
        lines = content.splitlines()
        current = lines[existing - 1]
        current_indent = current[: len(current) - len(current.lstrip())]
        return replace_line(content, existing, f"{current_indent}{key}: {value}")

    return insert_after(content, start + 1, [f"{child_indent}{key}: {value}"])


def remove_service(content: str, service: str) -> str:
    block = find_service_block(content, service)
    if block is None:
        return content

    start, end, _ = block
    lines = content.splitlines()
    del lines[start:end]
    return "\n".join(lines) + ("\n" if content.endswith("\n") else "")
