import json
from datetime import date
from pathlib import Path

import pytest

from astra.ingestion.parser import parse_partial_date, parse_pubmed_xml, parse_study

FIXTURES = Path(__file__).parent / "fixtures"


def load_study(nct_id: str, group: str = "metabolic_t2d"):
    return parse_study(json.loads((FIXTURES / f"ct_{nct_id}.json").read_text()), group)


def test_study_with_results_parses_every_field():
    study = load_study("NCT00799643")
    assert study.nct_id == "NCT00799643"
    assert study.condition_group == "metabolic_t2d"
    assert study.title.startswith("Targeting Inflammation in Type 2 Diabetes: Clinical Trial")
    assert study.brief_summary.startswith("Growing evidence over recent years")
    assert study.detailed_description is None  # this record has no detailedDescription
    assert study.conditions == ["Type 2 Diabetes Mellitus"]
    assert [(item.type, item.name) for item in study.interventions] == [
        ("DRUG", "Salsalate"),
        ("DRUG", "Salsalate Placebo"),
    ]
    assert study.study_type == "INTERVENTIONAL"
    assert study.phases == ["PHASE2", "PHASE3"]
    assert study.enrollment == 638
    assert study.overall_status == "COMPLETED"
    assert study.why_stopped is None
    assert (study.sponsor, study.sponsor_class) == ("Joslin Diabetes Center", "OTHER")
    assert study.start_date == date(2008, 11, 1)  # "2008-11" = first of the month
    assert study.primary_completion_date == date(2012, 9, 1)
    assert study.primary_completion_type == "ACTUAL"
    assert study.first_posted == date(2008, 12, 1)
    assert study.last_update_posted == date(2017, 12, 11)
    assert study.results_first_posted == date(2013, 11, 25)
    assert study.has_results is True
    assert study.is_fda_regulated is False  # no FDA flags in this record (pre-2017)
    assert study.is_applicable_trial is False
    assert len(study.registered_primary_outcomes) == 1
    assert study.registered_primary_outcomes[0].time_frame == "48 weeks from baseline"
    assert len(study.reported_primary_outcomes) == 1
    assert study.reference_pmids == ["23817699", "24130358"]  # BACKGROUND refs excluded


def test_adverse_events_are_aggregated_across_groups():
    events = load_study("NCT00799643").adverse_events
    assert events is not None
    assert events.total_serious_affected == 16
    assert events.total_at_risk == 286
    assert events.total_deaths is None
    assert len(events.top_serious_terms) == 5
    affected = [term.affected for term in events.top_serious_terms]
    assert affected == sorted(affected, reverse=True)
    assert events.top_serious_terms[0].affected == 2


def test_terminated_study_without_results():
    study = load_study("NCT05622981")
    assert study.overall_status == "TERMINATED"
    assert study.why_stopped == "limitations in staff and resources"
    assert study.is_fda_regulated is False
    assert study.has_results is False
    assert study.adverse_events is None
    assert study.reported_primary_outcomes == []
    assert study.is_applicable_trial is False  # behavioural, phase NA, not FDA regulated


def test_active_study_with_past_estimated_date():
    study = load_study("NCT03087032")
    assert study.overall_status == "RECRUITING"
    assert study.primary_completion_date == date(2025, 1, 15)
    assert study.primary_completion_type == "ESTIMATED"
    assert study.detailed_description.startswith("An increasing number of patients")


def test_missing_oversight_module_means_not_fda_regulated():
    study = load_study("NCT01691846")
    assert study.is_fda_regulated is False
    assert study.is_applicable_trial is False


@pytest.mark.parametrize(
    ("oversight", "expected"),
    [
        ({"isFdaRegulatedDrug": True, "isFdaRegulatedDevice": False}, True),
        ({"isFdaRegulatedDrug": False, "isFdaRegulatedDevice": True}, True),
        ({"isFdaRegulatedDrug": False}, False),
        ({}, False),
    ],
)
def test_fda_flags(oversight, expected):
    raw = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT00000003", "briefTitle": "T"},
            "designModule": {"studyType": "INTERVENTIONAL", "phases": ["PHASE3"]},
            "oversightModule": oversight,
        }
    }
    study = parse_study(raw, "oncology")
    assert study.is_fda_regulated is expected
    assert study.is_applicable_trial is expected


def test_minimal_record_with_missing_modules():
    raw = {"protocolSection": {"identificationModule": {"nctId": "NCT00000001", "briefTitle": "T"}}}
    study = parse_study(raw, "oncology")
    assert study.title == "T"
    assert study.overall_status == "UNKNOWN"
    assert study.phases == [] and study.reference_pmids == []
    assert study.adverse_events is None
    assert study.is_applicable_trial is False


def test_adverse_events_with_deaths_and_repeated_terms():
    raw = {
        "protocolSection": {"identificationModule": {"nctId": "NCT00000002", "briefTitle": "T"}},
        "resultsSection": {
            "adverseEventsModule": {
                "eventGroups": [
                    {"seriousNumAffected": 3, "seriousNumAtRisk": 50, "deathsNumAffected": 1},
                    {"seriousNumAffected": 5, "seriousNumAtRisk": 52, "deathsNumAffected": 2},
                ],
                "seriousEvents": [
                    {"term": "Sepsis", "stats": [{"numAffected": 1}, {"numAffected": 2}]},
                    {"term": "Stroke", "stats": [{"numAffected": 4}]},
                    {"term": "Rash", "stats": [{"numAffected": 0}]},
                ],
            }
        },
    }
    events = parse_study(raw, "oncology").adverse_events
    assert (events.total_serious_affected, events.total_at_risk, events.total_deaths) == (8, 102, 3)
    assert [(term.term, term.affected) for term in events.top_serious_terms] == [
        ("Stroke", 4),
        ("Sepsis", 3),
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("2012-09-15", date(2012, 9, 15)), ("2012-09", date(2012, 9, 1)), ("2012", date(2012, 1, 1))],
)
def test_partial_dates(value, expected):
    assert parse_partial_date(value) == expected
    assert parse_partial_date(None) is None


def test_pubmed_fixture():
    papers = dict(
        (paper.pmid, (paper, raw))
        for paper, raw in parse_pubmed_xml((FIXTURES / "pubmed_NCT00799643.xml").read_text())
    )
    assert set(papers) == {"23817699", "24130358"}
    paper, raw = papers["23817699"]
    assert paper.title.startswith("Salicylate (salsalate) in patients with type 2 diabetes")
    assert paper.abstract.startswith("BACKGROUND: ")
    assert paper.journal == "Annals of internal medicine"
    assert paper.pub_date == date(2013, 7, 2)
    assert paper.linked_nct_ids == ["NCT00799643"]
    assert raw.startswith("<PubmedArticle")


def test_pubmed_inline_markup_and_medline_date():
    xml = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID>
      <CommentsCorrectionsList><CommentsCorrections><PMID>999</PMID></CommentsCorrections>
      </CommentsCorrectionsList>
      <Article><Journal><Title>J</Title><JournalIssue><PubDate>
        <MedlineDate>2013 Jan-Feb</MedlineDate></PubDate></JournalIssue></Journal>
      <ArticleTitle>Effect of <i>drug X</i> on HbA<sub>1c</sub></ArticleTitle>
      <Abstract><AbstractText>Plain abstract.</AbstractText></Abstract></Article>
    </MedlineCitation></PubmedArticle></PubmedArticleSet>"""
    [(paper, _)] = parse_pubmed_xml(xml)
    assert paper.pmid == "1"
    assert paper.title == "Effect of drug X on HbA1c"
    assert paper.abstract == "Plain abstract."
    assert paper.pub_date == date(2013, 1, 1)
