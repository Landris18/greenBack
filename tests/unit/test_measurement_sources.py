import asyncio

import pytest

from app.collector.bmc import parse_chassis_members, parse_power_payload
from app.collector.host_probe import (
    HostProbe,
    discover_battery,
    discover_hwmon,
    discover_rapl_zones,
    is_virtualized,
)
from app.core.enums import MEASURED_POWER_SOURCES, PowerSource
from app.energy.model import (
    host_power_from_battery,
    host_power_from_hwmon,
    host_power_from_rapl,
    select_rapl_zones,
)


def ecrire(racine, chemin: str, contenu: str) -> None:
    fichier = racine / chemin
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(contenu)


def zone_rapl(racine, chemin: str, nom: str, energie: int, plage: int = 262_143_328_850) -> None:
    ecrire(racine, f"{chemin}/name", nom)
    ecrire(racine, f"{chemin}/energy_uj", str(energie))
    ecrire(racine, f"{chemin}/max_energy_range_uj", str(plage))


class TestBatterie:
    def test_power_now_est_converti_en_watts(self):
        assert host_power_from_battery(19_883_000, "Discharging") == pytest.approx(19.883)

    def test_batterie_en_charge_ne_mesure_rien(self):
        assert host_power_from_battery(19_883_000, "Charging") is None

    def test_batterie_pleine_ne_mesure_rien(self):
        assert host_power_from_battery(0, "Full") is None

    def test_statut_insensible_a_la_casse(self):
        assert host_power_from_battery(5_000_000, "  discharging  ") == pytest.approx(5.0)

    def test_power_now_nul_ne_vaut_pas_zero_watt(self):
        assert host_power_from_battery(0, "Discharging") is None

    def test_repli_sur_courant_et_tension(self):
        watts = host_power_from_battery(
            None, "Discharging", current_now_ua=1_500_000, voltage_now_uv=12_000_000
        )
        assert watts == pytest.approx(18.0)

    def test_repli_ignore_si_power_now_present(self):
        watts = host_power_from_battery(
            10_000_000, "Discharging", current_now_ua=1_500_000, voltage_now_uv=12_000_000
        )
        assert watts == pytest.approx(10.0)


class TestHwmon:
    def test_microwatts_convertis_en_watts(self):
        assert host_power_from_hwmon(85_000_000) == pytest.approx(85.0)

    def test_capteur_muet_ne_mesure_rien(self):
        assert host_power_from_hwmon(0) is None
        assert host_power_from_hwmon(None) is None


class TestSelectionRapl:
    def test_psys_prime_et_reste_seul(self):
        assert select_rapl_zones(["package-0", "dram", "psys", "core"]) == ["psys"]

    def test_sous_zones_du_package_sont_exclues(self):
        assert select_rapl_zones(["package-0", "core", "uncore"]) == ["package-0"]

    def test_dram_est_additionnee_au_package(self):
        assert select_rapl_zones(["package-0", "core", "dram"]) == ["dram", "package-0"]

    def test_plusieurs_sockets_sont_sommes(self):
        retenues = select_rapl_zones(["package-0", "package-1", "core", "uncore"])
        assert retenues == ["package-0", "package-1"]

    def test_aucune_zone_exploitable(self):
        assert select_rapl_zones(["core", "uncore"]) == []


class TestDecouverteSysfs:
    def test_zones_rapl_lues_sur_deux_sockets_avec_dram(self, tmp_path):
        zone_rapl(tmp_path, "intel-rapl:0", "package-0", 1_000)
        zone_rapl(tmp_path, "intel-rapl:0/intel-rapl:0:0", "core", 500)
        zone_rapl(tmp_path, "intel-rapl:0/intel-rapl:0:1", "dram", 200)
        zone_rapl(tmp_path, "intel-rapl:1", "package-1", 900)

        noms = sorted(zone.name for zone in discover_rapl_zones(str(tmp_path)))
        assert noms == ["dram", "package-0", "package-1"]

    def test_psys_evince_les_packages(self, tmp_path):
        zone_rapl(tmp_path, "intel-rapl:0", "package-0", 1_000)
        zone_rapl(tmp_path, "intel-rapl:1", "psys", 4_000)

        assert [zone.name for zone in discover_rapl_zones(str(tmp_path))] == ["psys"]

    def test_arborescence_absente_ne_leve_rien(self, tmp_path):
        assert discover_rapl_zones(str(tmp_path / "inexistant")) == []

    def test_zones_sous_un_repertoire_de_type_de_controle(self, tmp_path):
        zone_rapl(tmp_path, "intel-rapl/intel-rapl:0", "package-0", 1_000)
        zone_rapl(tmp_path, "intel-rapl/intel-rapl:0/intel-rapl:0:0", "core", 400)
        zone_rapl(tmp_path, "intel-rapl/intel-rapl:0/intel-rapl:0:1", "dram", 300)

        noms = sorted(zone.name for zone in discover_rapl_zones(str(tmp_path)))
        assert noms == ["dram", "package-0"]

    def test_mmio_ne_double_pas_le_comptage_du_package(self, tmp_path):
        zone_rapl(tmp_path, "intel-rapl/intel-rapl:0", "package-0", 1_000)
        zone_rapl(tmp_path, "intel-rapl-mmio/intel-rapl:0", "package-0", 1_000)

        zones = discover_rapl_zones(str(tmp_path))
        assert [zone.name for zone in zones] == ["package-0"]
        assert zones[0].energy_path.parent.parent.name == "intel-rapl"

    def test_nommage_reel_de_mmio_est_ignore(self, tmp_path):
        zone_rapl(tmp_path, "intel-rapl/intel-rapl:0", "package-0", 1_000)
        zone_rapl(tmp_path, "intel-rapl/intel-rapl:0/intel-rapl:0:0", "core", 400)
        zone_rapl(tmp_path, "intel-rapl-mmio/intel-rapl-mmio:0", "package-0", 1_000)

        zones = discover_rapl_zones(str(tmp_path))
        assert [zone.name for zone in zones] == ["package-0"]
        assert zones[0].energy_path.parent.parent.name == "intel-rapl"

    def test_batterie_detectee(self, tmp_path):
        ecrire(tmp_path, "BAT0/type", "Battery")
        ecrire(tmp_path, "BAT0/status", "Discharging")
        ecrire(tmp_path, "BAT0/power_now", "19883000")
        ecrire(tmp_path, "AC/type", "Mains")

        batterie = discover_battery(str(tmp_path))
        assert batterie is not None
        assert batterie.name == "BAT0"

    def test_secteur_seul_ne_donne_pas_de_batterie(self, tmp_path):
        ecrire(tmp_path, "AC/type", "Mains")
        assert discover_battery(str(tmp_path)) is None

    def test_hwmon_de_batterie_est_exclu(self, tmp_path):
        ecrire(tmp_path, "hwmon3/name", "BAT0")
        ecrire(tmp_path, "hwmon3/power1_input", "19883000")
        ecrire(tmp_path, "hwmon5/name", "pmbus")
        ecrire(tmp_path, "hwmon5/power1_input", "85000000")

        capteurs = discover_hwmon(str(tmp_path))
        assert [capteur.name for capteur in capteurs] == ["pmbus"]

    def test_hwmon_dont_le_peripherique_est_une_batterie_est_exclu(self, tmp_path):
        ecrire(tmp_path, "hwmon0/name", "acpi")
        ecrire(tmp_path, "hwmon0/power1_input", "19883000")
        ecrire(tmp_path, "hwmon0/device/type", "Battery")

        assert discover_hwmon(str(tmp_path)) == []

    def test_virtualisation_detectee_par_le_drapeau_hypervisor(self, tmp_path):
        ecrire(tmp_path, "cpuinfo", "model name\t: QEMU\nflags\t\t: fpu vme hypervisor lm\n")
        assert is_virtualized(str(tmp_path)) is True

    def test_machine_physique_non_virtualisee(self, tmp_path):
        ecrire(tmp_path, "cpuinfo", "model name\t: Intel\nflags\t\t: fpu vme lm\n")
        assert is_virtualized(str(tmp_path)) is False

    def test_procfs_absent_ne_leve_rien(self, tmp_path):
        assert is_virtualized(str(tmp_path / "inexistant")) is False


class TestRedfish:
    def test_puissance_du_chassis_extraite(self):
        payload = {"PowerControl": [{"PowerConsumedWatts": 214.0}]}
        assert parse_power_payload(payload) == pytest.approx(214.0)

    def test_champ_racine_en_repli(self):
        assert parse_power_payload({"PowerConsumedWatts": 180}) == pytest.approx(180.0)

    def test_chassis_sans_mesure(self):
        assert parse_power_payload({"PowerControl": [{"PowerConsumedWatts": None}]}) is None
        assert parse_power_payload({}) is None
        assert parse_power_payload("indisponible") is None

    def test_membres_du_collection_chassis(self):
        payload = {
            "Members": [
                {"@odata.id": "/redfish/v1/Chassis/1"},
                {"@odata.id": "/redfish/v1/Chassis/Enclosure"},
                {"absent": True},
            ]
        }
        assert parse_chassis_members(payload) == [
            "/redfish/v1/Chassis/1",
            "/redfish/v1/Chassis/Enclosure",
        ]

    def test_collection_vide(self):
        assert parse_chassis_members({}) == []
        assert parse_chassis_members(None) == []


class TestChaineDeSources:
    @staticmethod
    def sonde(monkeypatch, tmp_path, **capteurs) -> HostProbe:
        from app.collector import host_probe as module

        monkeypatch.setattr(module.settings, "SYSFS_PATH", str(tmp_path))
        monkeypatch.setattr(module.settings, "PROCFS_PATH", str(tmp_path))
        monkeypatch.setattr(module.settings, "BMC_REDFISH_URL", capteurs.get("bmc_url", ""))
        return HostProbe()

    def lire(self, sonde: HostProbe, interval: float = 1.0, ratio: float = 0.35):
        return asyncio.run(sonde.read(interval, ratio))

    def test_sans_capteur_aucune_mesure_et_mode_degrade(self, monkeypatch, tmp_path):
        sonde = self.sonde(monkeypatch, tmp_path)
        lecture = self.lire(sonde)

        assert lecture.measured_watts is None
        assert lecture.measured_source is None
        assert sonde.capabilities.has_hardware_source is False

    def test_batterie_prime_sur_rapl_et_sans_majoration(self, monkeypatch, tmp_path):
        ecrire(tmp_path, "class/power_supply/BAT0/type", "Battery")
        ecrire(tmp_path, "class/power_supply/BAT0/status", "Discharging")
        ecrire(tmp_path, "class/power_supply/BAT0/power_now", "19883000")
        zone_rapl(tmp_path, "devices/virtual/powercap/intel-rapl:0", "package-0", 0)

        sonde = self.sonde(monkeypatch, tmp_path)
        self.lire(sonde)
        (tmp_path / "devices/virtual/powercap/intel-rapl:0/energy_uj").write_text("7000000")
        lecture = self.lire(sonde)

        assert lecture.measured_source is PowerSource.BATTERY
        assert lecture.measured_watts == pytest.approx(19.883)

    def test_rapl_seul_recoit_la_majoration(self, monkeypatch, tmp_path):
        zone_rapl(tmp_path, "devices/virtual/powercap/intel-rapl:0", "package-0", 0)

        sonde = self.sonde(monkeypatch, tmp_path)
        self.lire(sonde)
        (tmp_path / "devices/virtual/powercap/intel-rapl:0/energy_uj").write_text("7000000")
        lecture = self.lire(sonde)

        assert lecture.measured_source is PowerSource.RAPL
        assert lecture.measured_watts == pytest.approx(7.0 * 1.35)

    def test_rapl_somme_les_zones_retenues(self, monkeypatch, tmp_path):
        base = "devices/virtual/powercap"
        zone_rapl(tmp_path, f"{base}/intel-rapl:0", "package-0", 0)
        zone_rapl(tmp_path, f"{base}/intel-rapl:0/intel-rapl:0:0", "core", 0)
        zone_rapl(tmp_path, f"{base}/intel-rapl:0/intel-rapl:0:1", "dram", 0)

        sonde = self.sonde(monkeypatch, tmp_path)
        self.lire(sonde)
        (tmp_path / base / "intel-rapl:0/energy_uj").write_text("7000000")
        (tmp_path / base / "intel-rapl:0/intel-rapl:0:0/energy_uj").write_text("4000000")
        (tmp_path / base / "intel-rapl:0/intel-rapl:0:1/energy_uj").write_text("2000000")
        lecture = self.lire(sonde)

        assert lecture.measured_watts == pytest.approx(9.0 * 1.35)

    def test_premiere_lecture_rapl_sans_reference_ne_mesure_rien(self, monkeypatch, tmp_path):
        zone_rapl(tmp_path, "devices/virtual/powercap/intel-rapl:0", "package-0", 7_000_000)

        sonde = self.sonde(monkeypatch, tmp_path)
        lecture = self.lire(sonde)

        assert lecture.measured_source is None

    def test_hwmon_prime_sur_rapl_sans_majoration(self, monkeypatch, tmp_path):
        ecrire(tmp_path, "class/hwmon/hwmon5/name", "pmbus")
        ecrire(tmp_path, "class/hwmon/hwmon5/power1_input", "85000000")
        zone_rapl(tmp_path, "devices/virtual/powercap/intel-rapl:0", "package-0", 0)

        sonde = self.sonde(monkeypatch, tmp_path)
        self.lire(sonde)
        (tmp_path / "devices/virtual/powercap/intel-rapl:0/energy_uj").write_text("7000000")
        lecture = self.lire(sonde)

        assert lecture.measured_source is PowerSource.HWMON
        assert lecture.measured_watts == pytest.approx(85.0)

    def test_bmc_prime_sur_la_batterie(self, monkeypatch, tmp_path):
        ecrire(tmp_path, "class/power_supply/BAT0/type", "Battery")
        ecrire(tmp_path, "class/power_supply/BAT0/status", "Discharging")
        ecrire(tmp_path, "class/power_supply/BAT0/power_now", "19883000")

        sonde = self.sonde(monkeypatch, tmp_path, bmc_url="https://bmc.invalid")

        async def puissance_chassis():
            return 214.0

        monkeypatch.setattr(sonde._bmc, "read_power_watts", puissance_chassis)
        lecture = self.lire(sonde)

        assert lecture.measured_source is PowerSource.BMC
        assert lecture.measured_watts == pytest.approx(214.0)

    def test_bmc_injoignable_bascule_sur_la_batterie(self, monkeypatch, tmp_path):
        ecrire(tmp_path, "class/power_supply/BAT0/type", "Battery")
        ecrire(tmp_path, "class/power_supply/BAT0/status", "Discharging")
        ecrire(tmp_path, "class/power_supply/BAT0/power_now", "19883000")

        sonde = self.sonde(monkeypatch, tmp_path, bmc_url="https://bmc.invalid")

        async def bmc_muet():
            return None

        monkeypatch.setattr(sonde._bmc, "read_power_watts", bmc_muet)
        lecture = self.lire(sonde)

        assert lecture.measured_source is PowerSource.BATTERY

    def test_capacites_publiees_pour_le_mode_degrade(self, monkeypatch, tmp_path):
        ecrire(tmp_path, "cpuinfo", "flags\t\t: fpu hypervisor lm\n")

        sonde = self.sonde(monkeypatch, tmp_path)
        capacites = sonde.capabilities.as_dict()

        assert capacites["virtualized"] is True
        assert capacites["rapl"] is False
        assert capacites["rapl_zones"] == []
        assert sonde.capabilities.has_hardware_source is False


class TestQualificationDesSources:
    def test_seul_le_modele_nest_pas_une_mesure(self):
        assert PowerSource.MODEL not in MEASURED_POWER_SOURCES
        for source in (
            PowerSource.BMC,
            PowerSource.BATTERY,
            PowerSource.HWMON,
            PowerSource.RAPL,
        ):
            assert source in MEASURED_POWER_SOURCES

    def test_majoration_rapl_appliquee_une_seule_fois(self):
        assert host_power_from_rapl(7_000_000, 1.0, 0.35) == pytest.approx(9.45)
