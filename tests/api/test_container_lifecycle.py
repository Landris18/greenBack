from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.collector.snapshot import ContainerSnapshot, HostInfo
from app.collector.supervisor import discover
from app.container.models import Container
from app.core.enums import ContainerStatus
from app.host.models import Host

COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_SERVICE_LABEL = "com.docker.compose.service"


def snapshot(docker_id: str, name: str, status: str = "running") -> ContainerSnapshot:
    return ContainerSnapshot(
        docker_id=docker_id,
        name=name,
        image_ref="greensi-api:latest",
        image_id="sha256:abc",
        image_size_bytes=41_000_000,
        status=status,
        restart_count=0,
        started_at=datetime.now(UTC),
        labels={COMPOSE_PROJECT_LABEL: "greensi", COMPOSE_SERVICE_LABEL: "api"},
        cpu_limit_cores=None,
        memory_limit_bytes=None,
    )


class SourceFictive:
    def __init__(self, snapshots: list[ContainerSnapshot]) -> None:
        self.snapshots = snapshots

    async def info(self) -> HostInfo:
        return HostInfo(cpu_cores=8, total_memory_bytes=16_000_000_000, os_info="Linux")

    async def inventory(self, cpu_cores: int) -> list[ContainerSnapshot]:
        return self.snapshots


@pytest.fixture
async def host(session):
    enregistrement = Host(name="machine-de-test", docker_url="tcp://fictif:2375")
    session.add(enregistrement)
    await session.commit()
    await session.refresh(enregistrement)
    return enregistrement


async def statuts(session) -> dict[str, ContainerStatus]:
    lignes = (await session.execute(select(Container))).scalars().all()
    return {ligne.name: ligne.status for ligne in lignes}


class TestCycleDeVieDesConteneurs:
    async def test_un_conteneur_disparu_est_marque_absent(self, session, host):
        vivant = snapshot("id-vivant", "greensi-api-1")
        ephemere = snapshot("id-ephemere", "greensi-api-run-fd23f9a1808f")

        await discover(session, host, SourceFictive([vivant, ephemere]))
        assert await statuts(session) == {
            "greensi-api-1": ContainerStatus.RUNNING,
            "greensi-api-run-fd23f9a1808f": ContainerStatus.RUNNING,
        }

        await discover(session, host, SourceFictive([vivant]))
        assert await statuts(session) == {
            "greensi-api-1": ContainerStatus.RUNNING,
            "greensi-api-run-fd23f9a1808f": ContainerStatus.ABSENT,
        }

    async def test_un_conteneur_absent_qui_revient_redevient_actif(self, session, host):
        vivant = snapshot("id-vivant", "greensi-api-1")
        intermittent = snapshot("id-intermittent", "greensi-worker-1")

        await discover(session, host, SourceFictive([vivant, intermittent]))
        await discover(session, host, SourceFictive([vivant]))
        assert (await statuts(session))["greensi-worker-1"] is ContainerStatus.ABSENT

        await discover(session, host, SourceFictive([vivant, intermittent]))
        assert (await statuts(session))["greensi-worker-1"] is ContainerStatus.RUNNING

    async def test_un_conteneur_recree_conserve_sa_ligne(self, session, host):
        await discover(session, host, SourceFictive([snapshot("id-avant", "greensi-api-1")]))
        await discover(session, host, SourceFictive([snapshot("id-apres", "greensi-api-1")]))

        lignes = (await session.execute(select(Container))).scalars().all()
        assert len(lignes) == 1
        assert lignes[0].docker_id == "id-apres"
        assert lignes[0].status is ContainerStatus.RUNNING

    async def test_un_inventaire_vide_marque_tout_absent(self, session, host):
        await discover(session, host, SourceFictive([snapshot("id-vivant", "greensi-api-1")]))
        await discover(session, host, SourceFictive([]))

        assert (await statuts(session))["greensi-api-1"] is ContainerStatus.ABSENT

    async def test_un_conteneur_arrete_reste_visible(self, session, host):
        arrete = snapshot("id-arrete", "greensi-api-1", status="exited")
        await discover(session, host, SourceFictive([arrete]))

        assert (await statuts(session))["greensi-api-1"] is ContainerStatus.EXITED
