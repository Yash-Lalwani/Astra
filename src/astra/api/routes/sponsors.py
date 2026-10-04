from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

from astra.api.deps import PagingDep
from astra.api.schemas import Page, Sponsor, SponsorDetail, to_page
from astra.models import ConditionGroup
from astra.queries import signals as signal_queries
from astra.queries import sponsors as sponsor_queries
from astra.queries import trials as trial_queries

router = APIRouter(tags=["sponsors"])


@router.get("/sponsors", response_model=Page[Sponsor])
async def list_sponsors(
    paging: PagingDep,
    min_studies: Annotated[int, Query(ge=1)] = 3,
    order_by: Literal["compliance_rate", "missing_results", "total_studies"] = "compliance_rate",
    condition_group: ConditionGroup | None = None,
):
    """compliance_rate sorts lowest first; the other orders sort highest first."""
    rows = await sponsor_queries.list_profiles(
        condition_group, min_studies, order_by, paging.limit, paging.offset
    )
    return to_page(rows, Sponsor)


@router.get("/sponsors/profile", response_model=SponsorDetail)
async def get_sponsor(name: str):
    profile = await sponsor_queries.get_profile(name.strip())
    if profile is None:
        raise HTTPException(status_code=404, detail="Sponsor not found")
    return {
        "profile": profile,
        "trials": await trial_queries.studies_for_sponsor(profile["sponsor"]),
        "signals": await signal_queries.signals_for_sponsor(profile["sponsor"]),
    }
