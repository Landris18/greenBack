import re
from dataclasses import dataclass, field

import yaml

MEMORY_UNITS = {"b": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}
MEMORY_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([bkmgt])?[b]?\s*$", re.IGNORECASE)

BUILD_TOOLING = (
    "build-essential",
    "gcc",
    "g++",
    "make",
    "cmake",
    "python3-dev",
    "libpq-dev",
    "rustc",
)
LIGHT_SUFFIXES = ("-slim", "-alpine", "slim", "alpine", "-bookworm-slim")


@dataclass(frozen=True)
class DockerfileInstruction:
    line_number: int
    keyword: str
    value: str
    raw: str


@dataclass(frozen=True)
class ParsedDockerfile:
    path: str
    content: str
    instructions: list[DockerfileInstruction] = field(default_factory=list)

    def by_keyword(self, keyword: str) -> list[DockerfileInstruction]:
        return [item for item in self.instructions if item.keyword == keyword.upper()]

    @property
    def stage_count(self) -> int:
        return len(self.by_keyword("FROM"))

    @property
    def base_images(self) -> list[DockerfileInstruction]:
        return self.by_keyword("FROM")

    @property
    def has_user(self) -> bool:
        return any(item.value.strip() not in ("", "root", "0") for item in self.by_keyword("USER"))


@dataclass(frozen=True)
class ComposeService:
    name: str
    image: str | None
    build_context: str | None
    dockerfile: str | None
    cpus: float | None
    memory_limit_bytes: int | None
    memory_limit_raw: str | None


@dataclass(frozen=True)
class ParsedCompose:
    path: str
    content: str
    services: dict[str, ComposeService] = field(default_factory=dict)


def parse_memory_value(raw: str | int | float | None) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, int | float):
        return int(raw)

    match = MEMORY_PATTERN.match(str(raw))
    if not match:
        return None
    amount = float(match.group(1))
    unit = (match.group(2) or "b").lower()
    return int(amount * MEMORY_UNITS[unit])


def parse_dockerfile(content: str, path: str = "Dockerfile") -> ParsedDockerfile:
    instructions: list[DockerfileInstruction] = []
    lines = content.splitlines()
    index = 0

    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        start = index

        if not stripped or stripped.startswith("#"):
            index += 1
            continue

        buffer = [stripped]
        while buffer[-1].endswith("\\") and index + 1 < len(lines):
            index += 1
            buffer.append(lines[index].strip())

        joined = " ".join(part.rstrip("\\").strip() for part in buffer)
        parts = joined.split(maxsplit=1)
        keyword = parts[0].upper()
        value = parts[1] if len(parts) > 1 else ""

        instructions.append(
            DockerfileInstruction(line_number=start + 1, keyword=keyword, value=value, raw=raw)
        )
        index += 1

    return ParsedDockerfile(path=path, content=content, instructions=instructions)


def is_light_image(image: str) -> bool:
    reference = image.split()[0] if image else ""
    tag = reference.split(":")[-1] if ":" in reference else ""
    return any(reference.endswith(suffix) or tag.endswith(suffix) for suffix in LIGHT_SUFFIXES)


def installs_build_tooling(dockerfile: ParsedDockerfile) -> list[DockerfileInstruction]:
    return [
        item
        for item in dockerfile.by_keyword("RUN")
        if any(tool in item.value for tool in BUILD_TOOLING)
    ]


def apt_without_cleanup(dockerfile: ParsedDockerfile) -> list[DockerfileInstruction]:
    return [
        item
        for item in dockerfile.by_keyword("RUN")
        if "apt-get install" in item.value and "rm -rf /var/lib/apt/lists" not in item.value
    ]


def parse_compose(content: str, path: str = "docker-compose.yml") -> ParsedCompose:
    document = yaml.safe_load(content) or {}
    raw_services = document.get("services") or {}
    services: dict[str, ComposeService] = {}

    if not isinstance(raw_services, dict):
        return ParsedCompose(path=path, content=content, services=services)

    for name, definition in raw_services.items():
        if not isinstance(definition, dict):
            continue

        build = definition.get("build")
        build_context = None
        dockerfile = None
        if isinstance(build, str):
            build_context, dockerfile = build, "Dockerfile"
        elif isinstance(build, dict):
            build_context = str(build.get("context") or ".")
            dockerfile = str(build.get("dockerfile") or "Dockerfile")

        deploy_limits = ((definition.get("deploy") or {}).get("resources") or {}).get(
            "limits"
        ) or {}
        memory_raw = definition.get("mem_limit") or deploy_limits.get("memory")
        cpus_raw = definition.get("cpus") or deploy_limits.get("cpus")

        services[str(name)] = ComposeService(
            name=str(name),
            image=definition.get("image"),
            build_context=build_context,
            dockerfile=dockerfile,
            cpus=float(cpus_raw) if cpus_raw is not None else None,
            memory_limit_bytes=parse_memory_value(memory_raw),
            memory_limit_raw=str(memory_raw) if memory_raw is not None else None,
        )

    return ParsedCompose(path=path, content=content, services=services)
