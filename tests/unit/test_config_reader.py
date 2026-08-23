from pathlib import Path

import pytest

from app.collector.config_reader import (
    ConfigAccessError,
    dockerfile_paths,
    read_project_files,
    read_text_file,
    resolve_within,
    translate_host_path,
)

HOST_ROOT = "/home/user"
COMPOSE = """services:
  api:
    build:
      context: ./app
      dockerfile: Dockerfile.api
  worker:
    build: ./worker
  db:
    image: postgres:16
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "mount"
    (root / "projects" / "app").mkdir(parents=True)
    (root / "projects" / "worker").mkdir(parents=True)
    (root / "projects" / "docker-compose.yml").write_text(COMPOSE)
    (root / "projects" / "app" / "Dockerfile.api").write_text('FROM python:3.12\nCMD ["x"]\n')
    (root / "projects" / "worker" / "Dockerfile").write_text("FROM node:22\n")
    return root


class TestTranslateHostPath:
    def test_maps_host_path_into_the_mount(self):
        result = translate_host_path(
            f"{HOST_ROOT}/dev/app/compose.yml", HOST_ROOT, "/host/projects"
        )
        assert result == Path("/host/projects/dev/app/compose.yml")

    def test_refuses_a_path_outside_the_root(self):
        with pytest.raises(ConfigAccessError, match="hors de la racine"):
            translate_host_path("/etc/passwd", HOST_ROOT, "/host/projects")

    def test_refuses_a_relative_path(self):
        with pytest.raises(ConfigAccessError, match="non absolu"):
            translate_host_path("app/compose.yml", HOST_ROOT, "/host/projects")

    def test_refuses_an_empty_path(self):
        with pytest.raises(ConfigAccessError):
            translate_host_path("", HOST_ROOT, "/host/projects")

    def test_refuses_a_sibling_directory_with_the_same_prefix(self):
        with pytest.raises(ConfigAccessError, match="hors de la racine"):
            translate_host_path("/home/user-autre/compose.yml", HOST_ROOT, "/host/projects")


class TestResolveWithin:
    def test_accepts_a_path_inside_the_mount(self, tmp_path: Path):
        target = tmp_path / "compose.yml"
        target.write_text("services: {}")
        assert resolve_within(target, str(tmp_path)) == target.resolve()

    def test_refuses_a_symlink_escaping_the_mount(self, tmp_path: Path):
        outside = tmp_path / "dehors"
        outside.mkdir()
        secret = outside / "secret.yml"
        secret.write_text("interdit")

        mount = tmp_path / "mount"
        mount.mkdir()
        link = mount / "compose.yml"
        link.symlink_to(secret)

        with pytest.raises(ConfigAccessError, match="liens symboliques"):
            resolve_within(link, str(mount))

    def test_refuses_a_traversal_sequence(self, tmp_path: Path):
        mount = tmp_path / "mount"
        mount.mkdir()
        (tmp_path / "secret.yml").write_text("interdit")

        with pytest.raises(ConfigAccessError):
            resolve_within(mount / ".." / "secret.yml", str(mount))


class TestReadTextFile:
    def test_reads_a_regular_file(self, tmp_path: Path):
        target = tmp_path / "compose.yml"
        target.write_text("services: {}")
        assert read_text_file(target, str(tmp_path)) == "services: {}"

    def test_missing_file_is_reported(self, tmp_path: Path):
        with pytest.raises(ConfigAccessError, match="introuvable"):
            read_text_file(tmp_path / "absent.yml", str(tmp_path))

    def test_oversized_file_is_refused(self, tmp_path: Path):
        target = tmp_path / "gros.yml"
        target.write_text("x" * (512 * 1024 + 1))
        with pytest.raises(ConfigAccessError, match="volumineux"):
            read_text_file(target, str(tmp_path))


class TestDockerfilePaths:
    def test_finds_dockerfiles_relative_to_the_compose(self):
        found = dict(dockerfile_paths(COMPOSE, "/home/user/projects/docker-compose.yml"))
        assert found["api"] == "/home/user/projects/app/Dockerfile.api"
        assert found["worker"] == "/home/user/projects/worker/Dockerfile"
        assert "db" not in found

    def test_invalid_yaml_is_reported(self):
        with pytest.raises(ConfigAccessError, match="illisible"):
            dockerfile_paths("services:\n  api:\n   - [unclosed", "/home/user/compose.yml")

    def test_compose_without_services(self):
        assert dockerfile_paths("version: '3'\n", "/home/user/compose.yml") == []


class TestReadProjectFiles:
    def test_reads_compose_and_every_dockerfile(self, project: Path):
        files = read_project_files(
            "/home/user/projects/docker-compose.yml", HOST_ROOT, str(project)
        )
        kinds = [item.kind.value for item in files]
        assert kinds.count("COMPOSE") == 1
        assert kinds.count("DOCKERFILE") == 2
        services = {item.service_name for item in files if item.service_name}
        assert services == {"api", "worker"}

    def test_missing_dockerfile_is_skipped_not_fatal(self, project: Path):
        (project / "projects" / "worker" / "Dockerfile").unlink()
        files = read_project_files(
            "/home/user/projects/docker-compose.yml", HOST_ROOT, str(project)
        )
        assert {item.service_name for item in files if item.service_name} == {"api"}

    def test_compose_outside_the_root_is_refused(self, project: Path):
        with pytest.raises(ConfigAccessError, match="hors de la racine"):
            read_project_files("/etc/docker-compose.yml", HOST_ROOT, str(project))

    def test_content_hash_changes_with_the_content(self, project: Path):
        first = read_project_files(
            "/home/user/projects/docker-compose.yml", HOST_ROOT, str(project)
        )[0]
        (project / "projects" / "docker-compose.yml").write_text(COMPOSE + "\n# modifie\n")
        second = read_project_files(
            "/home/user/projects/docker-compose.yml", HOST_ROOT, str(project)
        )[0]
        assert first.content_hash != second.content_hash
