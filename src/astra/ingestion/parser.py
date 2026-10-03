import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date
from typing import Any

from astra.ingestion.rules import is_applicable_trial
from astra.models import (
    AdverseEvents,
    Intervention,
    ParsedPaper,
    ParsedStudy,
    RegisteredOutcome,
    ReportedOutcome,
    SeriousTerm,
)

MONTHS = {name: number for number, name in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1
)}  # fmt: skip
LINKED_REFERENCE_TYPES = {"RESULT", "DERIVED"}
TOP_SERIOUS_TERMS = 5
NCT_ACCESSION_PATH = ".//DataBank/AccessionNumberList/AccessionNumber"


def parse_partial_date(value: str | None) -> date | None:
    """CT.gov dates are "YYYY-MM-DD", "YYYY-MM" (first of the month) or "YYYY"."""
    if not value:
        return None
    parts = [int(part) for part in value.split("-")]
    year, month, day = (parts + [1, 1])[:3]
    return date(year, month, day)


def _date_struct(module: dict, key: str) -> tuple[date | None, str | None]:
    struct = module.get(key) or {}
    return parse_partial_date(struct.get("date")), struct.get("type")


def _fda_regulated(oversight: dict) -> bool:
    """Missing flags count as not regulated (CT.gov fills them reliably only from 2017)."""
    return bool(oversight.get("isFdaRegulatedDrug") or oversight.get("isFdaRegulatedDevice"))


def _adverse_events(results: dict) -> AdverseEvents | None:
    module = results.get("adverseEventsModule")
    if not module:
        return None
    groups = module.get("eventGroups", [])
    deaths = [group["deathsNumAffected"] for group in groups if "deathsNumAffected" in group]
    affected_by_term: dict[str, int] = defaultdict(int)
    for event in module.get("seriousEvents", []):
        affected_by_term[event["term"]] += sum(
            stat.get("numAffected", 0) for stat in event.get("stats", [])
        )
    top_terms = sorted(affected_by_term.items(), key=lambda item: (-item[1], item[0]))
    return AdverseEvents(
        total_serious_affected=sum(group.get("seriousNumAffected", 0) for group in groups),
        total_at_risk=sum(group.get("seriousNumAtRisk", 0) for group in groups),
        total_deaths=sum(deaths) if deaths else None,
        top_serious_terms=[
            SeriousTerm(term=term, affected=affected)
            for term, affected in top_terms[:TOP_SERIOUS_TERMS]
            if affected > 0
        ],
    )


def parse_study(raw: dict[str, Any], condition_group: str) -> ParsedStudy:
    """Turn one ClinicalTrials.gov v2 study JSON into a ParsedStudy."""
    protocol = raw["protocolSection"]
    results = raw.get("resultsSection", {})
    identification = protocol["identificationModule"]
    status = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})
    sponsor = protocol.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {})
    description = protocol.get("descriptionModule", {})

    primary_completion_date, primary_completion_type = _date_struct(
        status, "primaryCompletionDateStruct"
    )
    completion_date, completion_type = _date_struct(status, "completionDateStruct")
    reported_measures = results.get("outcomeMeasuresModule", {}).get("outcomeMeasures", [])

    study = ParsedStudy(
        nct_id=identification["nctId"],
        condition_group=condition_group,
        title=identification.get("officialTitle") or identification.get("briefTitle") or "",
        brief_summary=description.get("briefSummary"),
        detailed_description=description.get("detailedDescription"),
        conditions=protocol.get("conditionsModule", {}).get("conditions", []),
        interventions=[
            Intervention(type=item.get("type", "OTHER"), name=item.get("name", ""))
            for item in protocol.get("armsInterventionsModule", {}).get("interventions", [])
        ],
        study_type=design.get("studyType"),
        phases=design.get("phases", []),
        enrollment=design.get("enrollmentInfo", {}).get("count"),
        overall_status=status.get("overallStatus", "UNKNOWN"),
        why_stopped=status.get("whyStopped"),
        sponsor=sponsor.get("name", "Unknown sponsor"),
        sponsor_class=sponsor.get("class"),
        start_date=_date_struct(status, "startDateStruct")[0],
        primary_completion_date=primary_completion_date,
        primary_completion_type=primary_completion_type,
        completion_date=completion_date,
        completion_type=completion_type,
        first_posted=_date_struct(status, "studyFirstPostDateStruct")[0],
        last_update_posted=_date_struct(status, "lastUpdatePostDateStruct")[0],
        results_first_posted=_date_struct(status, "resultsFirstPostDateStruct")[0],
        has_results=bool(raw.get("hasResults")),
        is_fda_regulated=_fda_regulated(protocol.get("oversightModule", {})),
        registered_primary_outcomes=[
            RegisteredOutcome(measure=item.get("measure", ""), time_frame=item.get("timeFrame"))
            for item in protocol.get("outcomesModule", {}).get("primaryOutcomes", [])
        ],
        reported_primary_outcomes=[
            ReportedOutcome(title=item.get("title", ""), time_frame=item.get("timeFrame"))
            for item in reported_measures
            if item.get("type") == "PRIMARY"
        ],
        adverse_events=_adverse_events(results),
        reference_pmids=[
            ref["pmid"]
            for ref in protocol.get("referencesModule", {}).get("references", [])
            if ref.get("type") in LINKED_REFERENCE_TYPES and ref.get("pmid")
        ],
    )
    study.is_applicable_trial = is_applicable_trial(study)
    return study


def _text(element: ET.Element | None) -> str:
    """All text inside an element, including text in inline tags such as <i> or <sup>."""
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def _pub_date(article: ET.Element) -> date | None:
    pub_date = article.find(".//Article/Journal/JournalIssue/PubDate")
    if pub_date is None:
        return None
    year_text = pub_date.findtext("Year")
    month_text = (pub_date.findtext("Month") or "1").strip()
    if not year_text:  # e.g. <MedlineDate>2013 Jan-Feb</MedlineDate>
        parts = (pub_date.findtext("MedlineDate") or "").split()
        if not parts or not parts[0][:4].isdigit():
            return None
        year_text = parts[0][:4]
        month_text = parts[1][:3] if len(parts) > 1 else "1"
    month = int(month_text) if month_text.isdigit() else MONTHS.get(month_text[:3].lower(), 1)
    day_text = pub_date.findtext("Day") or "1"
    return date(int(year_text), month, int(day_text) if day_text.isdigit() else 1)


def parse_pubmed_xml(xml_text: str) -> list[tuple[ParsedPaper, str]]:
    """Parse a PubMed efetch response into (paper, raw article XML) pairs."""
    papers = []
    for article in ET.fromstring(xml_text).findall("PubmedArticle"):
        pmid = article.findtext("MedlineCitation/PMID")
        if not pmid:
            continue
        abstract = " ".join(
            f"{part.get('Label')}: {_text(part)}" if part.get("Label") else _text(part)
            for part in article.findall(".//Article/Abstract/AbstractText")
        )
        paper = ParsedPaper(
            pmid=pmid.strip(),
            title=_text(article.find(".//Article/ArticleTitle")) or "(untitled)",
            abstract=abstract or None,
            journal=_text(article.find(".//Article/Journal/Title")) or None,
            pub_date=_pub_date(article),
            linked_nct_ids=sorted(
                {
                    accession.text.strip()
                    for accession in article.findall(NCT_ACCESSION_PATH)
                    if accession.text and accession.text.strip().startswith("NCT")
                }
            ),
        )
        papers.append((paper, ET.tostring(article, encoding="unicode")))
    return papers
