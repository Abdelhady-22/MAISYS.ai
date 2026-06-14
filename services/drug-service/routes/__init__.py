"""Central router export for drug-service.

``ALL_ROUTERS`` is imported by ``main.py`` and mounted in order. Add
new routers here when adding endpoints — do not import them in
``main.py`` directly.
"""

from fastapi import APIRouter

from services.drug_service.routes.acquisition import router as acquisition_router
from services.drug_service.routes.alternatives import router as alternatives_router
from services.drug_service.routes.compare import router as compare_router
from services.drug_service.routes.dosage import router as dosage_router
from services.drug_service.routes.health import router as health_router
from services.drug_service.routes.interactions import router as interactions_router
from services.drug_service.routes.lookup import router as lookup_router
from services.drug_service.routes.pharmacokinetics import router as pk_router
from services.drug_service.routes.query import router as query_router
from services.drug_service.routes.ws_query import router as ws_query_router

ALL_ROUTERS: list[APIRouter] = [
    health_router,
    lookup_router,
    interactions_router,
    dosage_router,
    compare_router,
    pk_router,
    alternatives_router,
    acquisition_router,
    query_router,
    ws_query_router,
]

__all__ = ["ALL_ROUTERS"]
