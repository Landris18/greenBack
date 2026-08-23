from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.enums import Difficulty, RecommendationStatus, RuleCode, Severity
from app.host.models import Host
from app.project.models import Project
from app.recommendation.models import Recommendation
from app.recommendation.rules.base import RuleFinding
from app.recommendation.service import scan_project

RULE_CODE = RuleCode.NO_LIMITS_SET


def finding(**overrides) -> RuleFinding:
    defaults = dict(
        rule_code=RULE_CODE,
        severity=Severity.MEDIUM,
        difficulty=Difficulty.EASY,
        title="Aucune limite de ressource",
        description="Le conteneur peut consommer sans plafond le CPU et la mémoire de l'hôte.",
    )
    defaults.update(overrides)
    return RuleFinding(**defaults)


@pytest.fixture
async def host(session):
    enregistrement = Host(name="machine-de-test", docker_url="tcp://fictif:2375")
    session.add(enregistrement)
    await session.commit()
    await session.refresh(enregistrement)
    return enregistrement


@pytest.fixture
async def project(session, host):
    now = datetime.now(UTC)
    enregistrement = Project(
        host_id=host.id,
        name="greensi",
        display_name="GreenSI",
        first_seen_at=now,
        last_seen_at=now,
    )
    session.add(enregistrement)
    await session.commit()
    await session.refresh(enregistrement)
    return enregistrement


def sans_findings(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.recommendation.service.evaluate_config", lambda context, thresholds: []
    )


def avec_finding(monkeypatch, **overrides) -> None:
    monkeypatch.setattr(
        "app.recommendation.service.evaluate_config",
        lambda context, thresholds: [finding(**overrides)],
    )


async def recommandation_unique(session, project) -> Recommendation:
    lignes = (
        (
            await session.execute(
                select(Recommendation).where(
                    Recommendation.project_id == project.id, Recommendation.rule_code == RULE_CODE
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(lignes) == 1
    return lignes[0]


class TestScanProjectNeDupliquePasLesRecommandationsTraitees:
    async def test_un_probleme_toujours_present_ne_duplique_pas_une_recommandation_ecartee(
        self, monkeypatch, session, project, green_config_factory
    ):
        config = await green_config_factory()

        avec_finding(monkeypatch)
        premier_scan = await scan_project(session, project, config)
        assert premier_scan.created == 1

        ligne = await recommandation_unique(session, project)
        ligne.status = RecommendationStatus.DISMISSED
        await session.commit()

        avec_finding(monkeypatch, description="Description mise à jour")
        second_scan = await scan_project(session, project, config)

        assert second_scan.created == 0
        assert second_scan.updated == 1

        ligne = await recommandation_unique(session, project)
        assert ligne.status == RecommendationStatus.DISMISSED
        assert ligne.description == "Description mise à jour"

    async def test_un_probleme_toujours_present_ne_duplique_pas_une_recommandation_appliquee(
        self, monkeypatch, session, project, green_config_factory
    ):
        config = await green_config_factory()

        avec_finding(monkeypatch)
        await scan_project(session, project, config)

        ligne = await recommandation_unique(session, project)
        ligne.status = RecommendationStatus.APPLIED
        await session.commit()

        avec_finding(monkeypatch)
        second_scan = await scan_project(session, project, config)

        assert second_scan.created == 0
        ligne = await recommandation_unique(session, project)
        assert ligne.status == RecommendationStatus.APPLIED

    async def test_une_recommandation_prise_en_compte_bascule_en_appliquee_si_le_probleme_disparait(
        self, monkeypatch, session, project, green_config_factory
    ):
        config = await green_config_factory()

        avec_finding(monkeypatch)
        await scan_project(session, project, config)

        ligne = await recommandation_unique(session, project)
        ligne.status = RecommendationStatus.ACKNOWLEDGED
        await session.commit()

        sans_findings(monkeypatch)
        second_scan = await scan_project(session, project, config)

        assert second_scan.resolved == 1
        ligne = await recommandation_unique(session, project)
        assert ligne.status == RecommendationStatus.APPLIED

    async def test_une_recommandation_ecartee_reste_ecartee_si_le_probleme_disparait(
        self, monkeypatch, session, project, green_config_factory
    ):
        config = await green_config_factory()

        avec_finding(monkeypatch)
        await scan_project(session, project, config)

        ligne = await recommandation_unique(session, project)
        ligne.status = RecommendationStatus.DISMISSED
        await session.commit()

        sans_findings(monkeypatch)
        second_scan = await scan_project(session, project, config)

        assert second_scan.resolved == 0
        ligne = await recommandation_unique(session, project)
        assert ligne.status == RecommendationStatus.DISMISSED

    async def test_une_recommandation_ouverte_est_mise_a_jour_en_place_pas_dupliquee(
        self, monkeypatch, session, project, green_config_factory
    ):
        config = await green_config_factory()

        avec_finding(monkeypatch)
        premier_scan = await scan_project(session, project, config)
        assert premier_scan.created == 1

        avec_finding(monkeypatch, description="Nouvelle description")
        second_scan = await scan_project(session, project, config)

        assert second_scan.created == 0
        assert second_scan.updated == 1
        ligne = await recommandation_unique(session, project)
        assert ligne.status == RecommendationStatus.OPEN
        assert ligne.description == "Nouvelle description"
