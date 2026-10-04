from datetime import date

from fastapi import APIRouter, HTTPException

from astra.api.schemas import TrialDetail
from astra.ingestion.rules import compare_primary_outcomes, results_due_status, timeline_status
from astra.queries import papers as paper_queries
from astra.queries import signals as signal_queries
from astra.queries import trials as trial_queries

router = APIRouter(tags=["trials"])


@router.get("/trials/{nct_id}", response_model=TrialDetail)
async def get_trial(nct_id: str):
    """A trial with the facts Astra computes from it, its linked papers and its signals."""
    nct_id = nct_id.strip().upper()
    study = await trial_queries.get_study(nct_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Trial not found")
    today = date.today()
    facts = {
        "is_applicable_trial": study.is_applicable_trial,
        "results_due": results_due_status(study, today),
        "timeline": timeline_status(study, today),
        "outcome_comparison": compare_primary_outcomes(
            study.registered_primary_outcomes, study.reported_primary_outcomes
        ),
        "adverse_events": study.adverse_events,
    }
    return {
        "study": study,
        "facts": facts,
        "papers": await paper_queries.linked_papers(nct_id, limit=50),
        "signals": await signal_queries.list_signals(nct_id=nct_id),
    }
