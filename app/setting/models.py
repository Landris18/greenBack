from sqlalchemy import BigInteger, Boolean, Enum, Float, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin
from app.core.enums import IdleAttributionPolicy


class GreenConfig(Base, TimestampMixin):
    __tablename__ = "green_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

    # Estimation calculee pour Madagascar, pas une valeur officielle publiee pour ce pays.
    # Mix electrique 2020 (source Wikipedia FR / IEA) : 45,3 % petrole, 12,4 % charbon,
    # 39,4 % hydroelectricite, 1,4 % biomasse, 1,4 % solaire.
    # Facteurs d'emission generiques par source, cycle de vie, en gCO2eq/kWh :
    # petrole ~650, charbon ~820, hydroelectricite ~24, biomasse ~230, solaire ~45.
    # Moyenne ponderee par les parts du mix : 0,453*650 + 0,124*820 + 0,394*24
    # + 0,014*230 + 0,014*45 = 409,4, arrondi a 409.
    # Champ configurable : a ajuster pour tout autre contexte geographique.
    emission_factor_g_per_kwh: Mapped[float] = mapped_column(Float, default=409.0, nullable=False)
    emission_factor_label: Mapped[str] = mapped_column(
        default="Madagascar (estimation mix 2020)", nullable=False
    )

    p_idle_watts: Mapped[float] = mapped_column(Float, default=15.0, nullable=False)
    p_max_watts: Mapped[float] = mapped_column(Float, default=65.0, nullable=False)
    mem_power_w_per_gb: Mapped[float] = mapped_column(Float, default=0.38, nullable=False)
    # Calibre sur machine de reference : 12 mesures appariees RAPL/batterie,
    # ratio moyen 2.65 (ecart-type 0.16). A recalibrer par machine.
    non_cpu_overhead_ratio: Mapped[float] = mapped_column(Float, default=1.65, nullable=False)
    max_idle_ratio: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)

    # Renseigne uniquement par une calibration automatique du collecteur
    # (voir app/collector/calibration.py). Vide sur une modification manuelle.
    calibration_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    weight_cpu: Mapped[float] = mapped_column(Float, default=0.70, nullable=False)
    weight_memory: Mapped[float] = mapped_column(Float, default=0.20, nullable=False)
    weight_io: Mapped[float] = mapped_column(Float, default=0.06, nullable=False)
    weight_network: Mapped[float] = mapped_column(Float, default=0.04, nullable=False)

    idle_attribution_policy: Mapped[IdleAttributionPolicy] = mapped_column(
        Enum(IdleAttributionPolicy, name="idle_attribution_policy"),
        default=IdleAttributionPolicy.OVERHEAD,
        nullable=False,
    )

    threshold_cpu_underuse_percent: Mapped[float] = mapped_column(
        Float, default=30.0, nullable=False
    )
    threshold_memory_underuse_percent: Mapped[float] = mapped_column(
        Float, default=40.0, nullable=False
    )
    threshold_idle_cpu_percent: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    threshold_idle_network_bps: Mapped[float] = mapped_column(Float, default=1024.0, nullable=False)
    threshold_idle_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    threshold_image_size_bytes: Mapped[int] = mapped_column(
        BigInteger, default=1_073_741_824, nullable=False
    )
    threshold_exited_days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    threshold_restart_count: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    analysis_window_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    threshold_cpu_high_percent: Mapped[float] = mapped_column(Float, default=80.0, nullable=False)
    threshold_memory_high_percent: Mapped[float] = mapped_column(
        Float, default=85.0, nullable=False
    )
    live_retention_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    persist_every_n_ticks: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
