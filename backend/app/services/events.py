"""Події для WebSocket (ТЗ 10.1)."""
from datetime import datetime

from app.models import Incident, Target
from app.schemas.incidents import IncidentOut


def metrics_event(target: Target, latest: dict[tuple[str, str], tuple[datetime, float]]) -> dict:
    """Останні значення рядів із пакета + стан об'єкта; клієнт за status бачить і зміну стану."""
    return {"type": "metrics", "target_id": target.id, "status": target.status,
            "last_seen": target.last_seen.isoformat() if target.last_seen else None,
            "values": {f"{m}:{i}" if i else m: v for (m, i), (_, v) in latest.items()}}


def incident_event(incident: Incident, target_name: str, change: str) -> dict:
    out = IncidentOut.model_validate(incident)
    out.target_name = target_name
    return {"type": "incident", "change": change, "incident": out.model_dump(mode="json")}
