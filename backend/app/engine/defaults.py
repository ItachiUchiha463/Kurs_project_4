"""Системні типові пороги (ТЗ 7.3) для метрик, що вже збираються. Нові додаються разом зі збирачами."""
from app.engine.thresholds import Threshold

_T = Threshold
DEFAULT_THRESHOLDS: dict[str, Threshold] = {t.metric: t for t in [
    _T("cpu_usage", "avg", 120, warn=80, crit=95, duration_s=0),
    _T("ram_usage", "avg", 120, warn=85, crit=95, duration_s=0),
    _T("load_per_core", "avg", 300, warn=1.5, crit=3, duration_s=0),
    _T("disk_usage", "last", 0, warn=85, crit=95, duration_s=60),
    _T("response_ms", "avg", 60, warn=1000, crit=3000, duration_s=0),
    _T("packet_loss", "avg", 60, warn=10, crit=50, duration_s=0),
    # бінарні метрики: лише crit, без гістерезису
    _T("available", "last", 0, crit=0, direction="equals", duration_s=30),
    _T("ping_available", "last", 0, crit=0, direction="equals", duration_s=30),
    _T("agent_alive", "last", 0, crit=0, direction="equals", duration_s=0),
]}

# метрики, інцидент на яких робить об'єкт «недоступним», а не «критичним» (ТЗ 7.2)
AVAILABILITY_METRICS = {"available", "agent_alive", "ping_available"}
