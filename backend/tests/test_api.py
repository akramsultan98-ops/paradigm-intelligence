"""API tests against the real app and a real database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import OpportunityStatus
from app.models import Contact, Opportunity, Source
from tests.conftest import requires_db
from tests.factories import (
    make_company,
    make_contact,
    make_opportunity,
    make_signal,
    make_source,
)

pytestmark = requires_db


# --------------------------------------------------------------------------
# health
# --------------------------------------------------------------------------

def test_liveness(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"]


def test_readiness_reports_the_database_and_the_extractor(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["database"] is True
    # A production box running the deterministic fallback should be visible to
    # monitoring.
    assert body["rule_based_fallback"] == (body["ai_provider"] == "rule_based")


# --------------------------------------------------------------------------
# Top 50
# --------------------------------------------------------------------------

def test_top50_is_ranked_and_honest_about_its_length(
    client: TestClient, session: Session
) -> None:
    make_opportunity(session, score=95, company_name="Alpha Industries")
    make_opportunity(session, score=80, company_name="Beta Holdings")
    make_opportunity(session, score=50, company_name="Weak Leads")

    body = client.get("/api/v1/opportunities/top50").json()
    assert body["returned"] == 2
    assert body["top_n"] == 50
    assert body["eligible_total"] == 2
    assert body["qualifying_threshold"] == 70
    assert [item["rank"] for item in body["items"]] == [1, 2]
    assert [item["company"]["name"] for item in body["items"]] == [
        "Alpha Industries", "Beta Holdings"
    ]


def test_top50_row_carries_everything_the_ui_shows(
    client: TestClient, session: Session
) -> None:
    """Spec §29: every field on the card must be present."""
    company = make_company(session, "Elsewedy Electric", sector="Industrial")
    make_contact(session, company)
    make_opportunity(session, company=company, score=88)

    item = client.get("/api/v1/opportunities/top50").json()["items"][0]
    for field in ("rank", "score", "type", "event_probability", "commercial_value",
                  "commercial_value_band", "why_now", "sales_angle", "recommended_action",
                  "opportunity_window", "recommended_contact_timing", "classification",
                  "assertion_level", "status"):
        assert field in item, field
    assert item["company"]["sector"] == "Industrial"
    assert item["signal"]["title"]
    assert item["signal"]["source"]["source_url"]
    assert item["primary_contact"] is None or "email_status" in item["primary_contact"]


def test_top50_labels_every_opportunity_with_an_assertion_level(
    client: TestClient, session: Session
) -> None:
    """A prediction must never reach the UI looking like a booking."""
    make_opportunity(session, score=90)
    item = client.get("/api/v1/opportunities/top50").json()["items"][0]
    assert item["assertion_level"] in {"FACT", "INFERENCE", "PREDICTION"}


def test_top50_exposes_the_score_breakdown(client: TestClient, session: Session) -> None:
    make_opportunity(session, score=90)
    item = client.get("/api/v1/opportunities/top50").json()["items"][0]
    for field in ("base_score", "decay_factor", "contact_quality", "timing_score",
                  "evidence_score"):
        assert field in item, field
    assert isinstance(item["decay_factor"], float)


def test_top50_on_an_empty_database(client: TestClient) -> None:
    body = client.get("/api/v1/opportunities/top50").json()
    assert body["items"] == []
    assert body["returned"] == 0


# --------------------------------------------------------------------------
# filters
# --------------------------------------------------------------------------

def test_sector_filter(client: TestClient, session: Session) -> None:
    make_opportunity(session, score=90, sector="Banking", company_name="Bank One")
    make_opportunity(session, score=95, sector="Technology", company_name="Tech One")
    body = client.get("/api/v1/opportunities/top50", params={"sector": "Banking"}).json()
    assert [i["company"]["name"] for i in body["items"]] == ["Bank One"]


def test_status_and_type_filters(client: TestClient, session: Session) -> None:
    make_opportunity(session, score=90, status=OpportunityStatus.NEW)
    make_opportunity(session, score=85, status=OpportunityStatus.CONTACTED)

    body = client.get("/api/v1/opportunities/top50", params={"status": "NEW"}).json()
    assert body["returned"] == 1
    assert body["items"][0]["status"] == "NEW"

    body = client.get(
        "/api/v1/opportunities/top50", params={"type": "PRODUCT_LAUNCH"}
    ).json()
    assert all(i["type"] == "PRODUCT_LAUNCH" for i in body["items"])


def test_score_and_date_filters(client: TestClient, session: Session) -> None:
    now = datetime.now(UTC)
    make_opportunity(session, score=95, company_name="Strong Corp")
    make_opportunity(session, score=72, company_name="Weaker Corp",
                     created_at=now - timedelta(days=10))

    body = client.get("/api/v1/opportunities/top50", params={"min_score": 90}).json()
    assert [i["company"]["name"] for i in body["items"]] == ["Strong Corp"]

    body = client.get(
        "/api/v1/opportunities/top50",
        params={"date_from": (now - timedelta(days=1)).isoformat()},
    ).json()
    assert [i["company"]["name"] for i in body["items"]] == ["Strong Corp"]


def test_invalid_filter_values_are_rejected(client: TestClient) -> None:
    assert client.get("/api/v1/opportunities/top50", params={"status": "NOPE"}).status_code == 422
    assert client.get(
        "/api/v1/opportunities/top50", params={"min_score": 500}
    ).status_code == 422


# --------------------------------------------------------------------------
# list, detail, status
# --------------------------------------------------------------------------

def test_list_includes_sub_threshold_opportunities(
    client: TestClient, session: Session
) -> None:
    make_opportunity(session, score=90)
    make_opportunity(session, score=30)
    assert len(client.get("/api/v1/opportunities").json()) == 2


def test_detail_includes_every_contact(client: TestClient, session: Session) -> None:
    company = make_company(session, "Elsewedy Electric")
    make_contact(session, company, name="Ahmed Hassan", email="a@elsewedy.test")
    make_contact(session, company, name="Mona Said", job_title="PR Manager",
                 email="m@elsewedy.test", contact_score=70)
    opportunity = make_opportunity(session, company=company, score=90)

    body = client.get(f"/api/v1/opportunities/{opportunity.id}").json()
    assert len(body["contacts"]) == 2
    assert {c["name"] for c in body["contacts"]} == {"Ahmed Hassan", "Mona Said"}
    # Contacts are ordered best first.
    assert body["contacts"][0]["contact_score"] >= body["contacts"][1]["contact_score"]


def test_detail_404_for_an_unknown_id(client: TestClient) -> None:
    response = client.get("/api/v1/opportunities/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_status_can_be_updated(client: TestClient, session: Session) -> None:
    opportunity = make_opportunity(session, score=90)
    response = client.patch(
        f"/api/v1/opportunities/{opportunity.id}", json={"status": "CONTACTED"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "CONTACTED"

    session.expire_all()
    assert session.get(Opportunity, opportunity.id).status is OpportunityStatus.CONTACTED


def test_scores_cannot_be_edited_by_hand(client: TestClient, session: Session) -> None:
    """A hand-edited score would make the whole ranking meaningless."""
    opportunity = make_opportunity(session, score=90)
    response = client.patch(
        f"/api/v1/opportunities/{opportunity.id}",
        json={"status": "CONTACTED", "score": 100, "why_now": "because I said so"},
    )
    assert response.status_code == 200
    session.expire_all()
    refreshed = session.get(Opportunity, opportunity.id)
    assert refreshed.score == 90
    assert "because I said so" not in refreshed.why_now


def test_invalid_status_is_rejected(client: TestClient, session: Session) -> None:
    opportunity = make_opportunity(session, score=90)
    response = client.patch(
        f"/api/v1/opportunities/{opportunity.id}", json={"status": "DEFINITELY_WON"}
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# companies
# --------------------------------------------------------------------------

def test_company_endpoints(client: TestClient, session: Session) -> None:
    company = make_company(session, "Juhayna Food Industries", sector="FMCG")
    make_contact(session, company)
    make_opportunity(session, company=company, score=85)

    listed = client.get("/api/v1/companies").json()
    assert [c["name"] for c in listed] == ["Juhayna Food Industries"]

    detail = client.get(f"/api/v1/companies/{company.id}").json()
    assert detail["sector"] == "FMCG"
    assert detail["signal_count"] == 1
    assert detail["opportunity_count"] == 1
    assert len(detail["contacts"]) == 1


def test_company_search_and_sector_filter(client: TestClient, session: Session) -> None:
    make_company(session, "Alpha Industries", sector="Industrial")
    make_company(session, "Beta Bank", sector="Banking")
    session.commit()
    assert len(client.get("/api/v1/companies", params={"search": "alpha"}).json()) == 1
    assert len(client.get("/api/v1/companies", params={"sector": "Banking"}).json()) == 1


def test_sectors_endpoint_is_not_shadowed_by_the_uuid_route(client: TestClient) -> None:
    """A literal path registered after a UUID parameter would be swallowed by it."""
    response = client.get("/api/v1/companies/sectors")
    assert response.status_code == 200
    sectors = response.json()
    assert "Technology" in sectors and "Oil & Gas" in sectors


# --------------------------------------------------------------------------
# ingestion
# --------------------------------------------------------------------------

def test_documents_can_be_submitted_directly(client: TestClient, session: Session) -> None:
    response = client.post(
        "/api/v1/ingest/documents",
        json={
            "documents": [
                {
                    "url": "https://elsewedy.test/news/1",
                    "title": "Elsewedy Electric unveils a new product line",
                    "content": (
                        "Elsewedy Electric announced the launch of a new product line at a "
                        "briefing in Cairo. The company said the products will be built at "
                        "its Egyptian plants and taken to market with its distribution "
                        "partners. The CEO said the rollout is scheduled for next month and "
                        "that customer briefings would accompany the commercial launch."
                    ),
                    "source_type": "COMPANY",
                    "publisher": "Elsewedy Electric",
                    "company_hint": "Elsewedy Electric",
                    "confidence": 0.9,
                }
            ]
        },
    )
    assert response.status_code == 200
    stats = response.json()
    assert stats["documents_seen"] == 1
    assert stats["sources_created"] == 1
    assert session.scalar(select(func.count(Source.id))) == 1


def test_submitting_the_same_document_twice_is_deduplicated(client: TestClient) -> None:
    payload = {
        "documents": [
            {
                "url": "https://a.test/1",
                "title": "A partnership was announced",
                "content": (
                    "Two firms announced a strategic partnership in Cairo, according to a "
                    "statement issued by both companies. The agreement covers joint "
                    "delivery of industrial projects in Egypt and was signed by the "
                    "chairman of each group. Management said the partnership would be "
                    "presented to customers and partners over the coming weeks."
                ),
                "source_type": "BUSINESS_PUBLICATION",
            }
        ]
    }
    client.post("/api/v1/ingest/documents", json=payload)
    second = client.post("/api/v1/ingest/documents", json=payload).json()
    assert second["duplicates_skipped"] == 1
    assert second["sources_created"] == 0


def test_document_validation(client: TestClient) -> None:
    assert client.post("/api/v1/ingest/documents", json={"documents": []}).status_code == 422
    assert client.post(
        "/api/v1/ingest/documents",
        json={"documents": [{"url": "not-a-url", "content": "x"}]},
    ).status_code == 422
    assert client.post(
        "/api/v1/ingest/documents",
        json={"documents": [{"url": "https://a.test", "content": ""}]},
    ).status_code == 422


def test_contacts_require_provenance(client: TestClient) -> None:
    """A contact without a source_url is exactly what must not be stored."""
    response = client.post(
        "/api/v1/ingest/contacts",
        json={"contacts": [{"company_name": "Elsewedy Electric", "name": "Ahmed Hassan"}]},
    )
    assert response.status_code == 422


def test_contacts_cannot_be_claimed_verified(client: TestClient) -> None:
    response = client.post(
        "/api/v1/ingest/contacts",
        json={
            "contacts": [
                {
                    "company_name": "Elsewedy Electric",
                    "name": "Ahmed Hassan",
                    "email": "a.hassan@elsewedy.test",
                    "email_status": "VERIFIED",
                    "source_url": "https://elsewedy.test/leadership",
                }
            ]
        },
    )
    assert response.status_code == 422
    assert "verification" in response.text


def test_contacts_attach_to_a_known_company(client: TestClient, session: Session) -> None:
    make_company(session, "Elsewedy Electric")
    session.commit()

    response = client.post(
        "/api/v1/ingest/contacts",
        json={
            "contacts": [
                {
                    "company_name": "Elsewedy Electric S.A.E.",
                    "name": "Ahmed Hassan",
                    "job_title": "Marketing Director",
                    "department": "MARKETING",
                    "email": "a.hassan@elsewedy.test",
                    "email_status": "PUBLIC",
                    "linkedin_url": "linkedin.com/in/ahmed-hassan",
                    "source_url": "https://elsewedy.test/leadership",
                    "source_type": "COMPANY",
                }
            ]
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "created": 1, "updated": 0, "skipped": 0, "unresolved_companies": []
    }

    contact = session.scalars(select(Contact)).one()
    assert contact.email_status.value == "PUBLIC"
    assert contact.contact_score > 70
    assert contact.source_id is not None


def test_contacts_for_an_unknown_company_are_reported_not_invented(
    client: TestClient, session: Session
) -> None:
    """A contact payload must not be able to create an account."""
    response = client.post(
        "/api/v1/ingest/contacts",
        json={
            "contacts": [
                {
                    "company_name": "Never Heard Of This Company",
                    "name": "Someone Unknown",
                    "source_url": "https://a.test/page",
                }
            ]
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["skipped"] == 1
    assert body["unresolved_companies"] == ["Never Heard Of This Company"]
    assert session.scalar(select(func.count(Contact.id))) == 0


def test_ingest_run_with_no_sources_configured(client: TestClient) -> None:
    """No enabled feeds is a valid state, not an error."""
    response = client.post("/api/v1/ingest/run", json={})
    assert response.status_code == 200
    assert response.json()["documents_seen"] == 0


# --------------------------------------------------------------------------
# rescore and brief
# --------------------------------------------------------------------------

def test_rescore_endpoint(client: TestClient, session: Session) -> None:
    make_opportunity(session, score=85, base_score=85, signal_age_days=200)
    response = client.post("/api/v1/maintenance/rescore")
    assert response.status_code == 200
    body = response.json()
    assert body["examined"] == 1
    assert body["changed"] == 1


def test_brief_endpoint(client: TestClient, session: Session) -> None:
    make_opportunity(session, score=93, company_name="Hot Corp")
    make_opportunity(session, score=60, company_name="Cold Corp")

    body = client.get("/api/v1/brief/daily").json()
    assert body["qualifying_threshold"] == 70
    assert body["eligible_total"] == 1
    assert [o["company"]["name"] for o in body["top_new_opportunities"]] == ["Hot Corp"]
    assert [o["company"]["name"] for o in body["new_hot"]] == ["Hot Corp"]
    assert [o["company"]["name"] for o in body["current_top_50"]] == ["Hot Corp"]
    assert body["classification_counts"]["HOT"] == 1


def test_brief_movement_buckets(client: TestClient, session: Session) -> None:
    created = datetime.now(UTC) - timedelta(days=10)
    changed = datetime.now(UTC) - timedelta(hours=1)
    make_opportunity(session, score=92, previous_score=80, company_name="Rising Corp",
                     created_at=created, score_changed_at=changed)
    make_opportunity(session, score=50, previous_score=85, company_name="Expired Corp",
                     created_at=created, score_changed_at=changed)

    body = client.get("/api/v1/brief/daily").json()
    assert [o["opportunity"]["company"]["name"] for o in body["upgraded"]] == ["Rising Corp"]
    assert [o["opportunity"]["company"]["name"] for o in body["expired"]] == ["Expired Corp"]
    assert body["upgraded"][0]["delta"] == 12
    assert body["upgraded"][0]["change"] == "UPGRADED"


# --------------------------------------------------------------------------
# contract
# --------------------------------------------------------------------------

def test_openapi_documents_every_endpoint(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    for path in ("/api/v1/opportunities/top50", "/api/v1/opportunities",
                 "/api/v1/opportunities/{opportunity_id}", "/api/v1/companies",
                 "/api/v1/companies/sectors", "/api/v1/brief/daily",
                 "/api/v1/ingest/run", "/api/v1/ingest/documents",
                 "/api/v1/ingest/contacts", "/api/v1/maintenance/rescore",
                 "/health/live", "/health/ready"):
        assert path in spec["paths"], path


# --------------------------------------------------------------------------
# search and sorting (spec §22)
# --------------------------------------------------------------------------

def test_search_matches_company_name(client: TestClient, session: Session) -> None:
    make_opportunity(session, score=90, company_name="Elsewedy Electric")
    make_opportunity(session, score=88, company_name="Juhayna Food Industries")
    body = client.get("/api/v1/opportunities/top50", params={"search": "elsewedy"}).json()
    assert [i["company"]["name"] for i in body["items"]] == ["Elsewedy Electric"]


def test_search_matches_contact_name_and_email(client: TestClient, session: Session) -> None:
    """Searching by the person you remember, not the company you forgot."""
    company = make_company(session, "Elsewedy Electric")
    make_contact(session, company, name="Ahmed Hassan", email="a.hassan@elsewedy.test")
    make_opportunity(session, company=company, score=90)
    make_opportunity(session, score=92, company_name="Other Holdings")

    by_name = client.get("/api/v1/opportunities/top50", params={"search": "Ahmed"}).json()
    assert [i["company"]["name"] for i in by_name["items"]] == ["Elsewedy Electric"]

    by_email = client.get("/api/v1/opportunities/top50", params={"search": "a.hassan@"}).json()
    assert [i["company"]["name"] for i in by_email["items"]] == ["Elsewedy Electric"]


def test_search_returns_one_row_per_opportunity(client: TestClient, session: Session) -> None:
    """Three matching contacts must not triple the opportunity."""
    company = make_company(session, "Elsewedy Electric")
    for index in range(3):
        make_contact(session, company, name=f"Ahmed Hassan {index}",
                     email=f"ahmed{index}@elsewedy.test")
    make_opportunity(session, company=company, score=90)
    body = client.get("/api/v1/opportunities/top50", params={"search": "Ahmed"}).json()
    assert body["returned"] == 1


def test_search_finds_nothing_for_an_unknown_term(client: TestClient, session: Session) -> None:
    make_opportunity(session, score=90, company_name="Elsewedy Electric")
    body = client.get("/api/v1/opportunities/top50", params={"search": "zzzznothing"}).json()
    assert body["returned"] == 0


@pytest.mark.parametrize(
    "sort",
    ["score", "event_probability", "commercial_value", "contact_quality",
     "timing_score", "evidence_score", "created_at", "company"],
)
def test_every_sort_field_works(client: TestClient, session: Session, sort: str) -> None:
    make_opportunity(session, score=90, company_name="Beta Holdings")
    make_opportunity(session, score=80, company_name="Alpha Industries")
    response = client.get("/api/v1/opportunities/top50", params={"sort": sort})
    assert response.status_code == 200
    assert response.json()["returned"] == 2


def test_sort_by_company_ascending(client: TestClient, session: Session) -> None:
    make_opportunity(session, score=90, company_name="Zeta Holdings")
    make_opportunity(session, score=80, company_name="Alpha Industries")
    body = client.get(
        "/api/v1/opportunities/top50", params={"sort": "company", "order": "asc"}
    ).json()
    assert [i["company"]["name"] for i in body["items"]] == [
        "Alpha Industries", "Zeta Holdings"
    ]


def test_sort_order_is_honoured(client: TestClient, session: Session) -> None:
    for score in (95, 75, 85):
        make_opportunity(session, score=score)
    ascending = client.get(
        "/api/v1/opportunities/top50", params={"sort": "score", "order": "asc"}
    ).json()
    assert [i["score"] for i in ascending["items"]] == [75, 85, 95]


def test_invalid_sort_and_order_are_rejected(client: TestClient) -> None:
    assert client.get(
        "/api/v1/opportunities/top50", params={"sort": "nonsense"}
    ).status_code == 422
    assert client.get(
        "/api/v1/opportunities/top50", params={"order": "sideways"}
    ).status_code == 422


def test_rank_reflects_the_current_ordering(client: TestClient, session: Session) -> None:
    make_opportunity(session, score=90, company_name="Beta Holdings")
    make_opportunity(session, score=80, company_name="Alpha Industries")
    body = client.get(
        "/api/v1/opportunities/top50", params={"sort": "company", "order": "asc"}
    ).json()
    assert [(i["rank"], i["company"]["name"]) for i in body["items"]] == [
        (1, "Alpha Industries"), (2, "Beta Holdings")
    ]


# --------------------------------------------------------------------------
# the three statements and provenance on the wire
# --------------------------------------------------------------------------

def test_detail_carries_the_three_statements(client: TestClient, session: Session) -> None:
    from app.models import Opportunity as Opp

    opportunity = make_opportunity(session, score=90)
    stored = session.get(Opp, opportunity.id)
    assert stored is not None
    stored.fact = "The source states the partnership was signed."
    stored.inference = "A signing of this kind would typically be marked publicly."
    stored.prediction = "A ceremony may follow. Not confirmed."
    session.commit()

    body = client.get(f"/api/v1/opportunities/{opportunity.id}").json()
    assert body["fact"].startswith("The source states")
    assert "typically" in body["inference"]
    assert "Not confirmed" in body["prediction"]


def test_source_provenance_is_exposed(client: TestClient, session: Session) -> None:
    make_opportunity(session, score=90)
    item = client.get("/api/v1/opportunities/top50").json()["items"][0]
    assert item["signal"]["source"]["ingest_mode"] == "AUTOMATED"
    assert item["signal"]["source"]["source_url"]
    assert 0.0 <= item["signal"]["source"]["confidence"] <= 1.0


def test_test_data_is_hidden_unless_asked_for(client: TestClient, session: Session) -> None:
    from app.domain.enums import IngestMode

    make_opportunity(session, score=88, company_name="Real Corp")
    make_opportunity(session, score=95, company_name="Fixture Corp",
                     ingest_mode=IngestMode.TEST)

    default_view = client.get("/api/v1/opportunities/top50").json()
    assert [i["company"]["name"] for i in default_view["items"]] == ["Real Corp"]

    with_test = client.get(
        "/api/v1/opportunities/top50", params={"include_test": "true"}
    ).json()
    assert [i["company"]["name"] for i in with_test["items"]] == ["Fixture Corp", "Real Corp"]


# --------------------------------------------------------------------------
# company profile (spec §24)
# --------------------------------------------------------------------------

def test_company_profile_has_everything_an_am_needs(
    client: TestClient, session: Session
) -> None:
    company = make_company(session, "Elsewedy Electric", sector="Industrial")
    make_contact(session, company)
    make_opportunity(session, company=company, score=88)

    body = client.get(f"/api/v1/companies/{company.id}").json()
    assert body["sector"] == "Industrial"
    assert body["account_score"] == 88
    assert body["qualified_opportunity_count"] == 1
    assert len(body["opportunities"]) == 1
    assert len(body["recent_signals"]) == 1
    assert len(body["contacts"]) == 1
    assert body["parent"] is None
    assert body["subsidiaries"] == []


def test_company_event_history_is_only_reported_events(
    client: TestClient, session: Session
) -> None:
    """No event history is honest; inventing one is not."""
    from app.domain.enums import SignalType

    company = make_company(session, "Elsewedy Electric")
    make_opportunity(session, company=company, score=80)
    body = client.get(f"/api/v1/companies/{company.id}").json()
    assert body["event_history"] == []

    source = make_source(session)
    make_signal(session, company, source, signal_type=SignalType.CONFERENCE,
                title="Elsewedy hosts annual technical conference")
    session.commit()
    body = client.get(f"/api/v1/companies/{company.id}").json()
    assert len(body["event_history"]) == 1


def test_company_shows_its_parent_and_subsidiaries(
    client: TestClient, session: Session
) -> None:
    parent = make_company(session, "Elsewedy Electric")
    child = make_company(session, "Elsewedy Electric for Trading and Distribution")
    child.parent_company_id = parent.id
    session.commit()

    child_body = client.get(f"/api/v1/companies/{child.id}").json()
    assert child_body["parent"]["name"] == "Elsewedy Electric"

    parent_body = client.get(f"/api/v1/companies/{parent.id}").json()
    assert [s["name"] for s in parent_body["subsidiaries"]] == [
        "Elsewedy Electric for Trading and Distribution"
    ]


# --------------------------------------------------------------------------
# new ingestion endpoints
# --------------------------------------------------------------------------

def test_analyst_signal_endpoint(client: TestClient, session: Session) -> None:
    response = client.post(
        "/api/v1/ingest/signals",
        json={
            "source_url": "https://sis.gov.eg/en/media-center/news/example/",
            "source_title": "PM witnesses signing of a major agreement",
            "source_type": "GOVERNMENT",
            "publisher": "State Information Service",
            "published_at": "2026-09-10T00:00:00Z",
            "confidence": 0.95,
            "content": (
                "The State Information Service reports that the Prime Minister witnessed "
                "the signing of a major agreement between a consortium of companies to "
                "build new industrial capacity in Egypt, with investment of USD 200 "
                "million and a partnership covering technology transfer and local "
                "manufacturing across several governorates."
            ),
            "extraction": {
                "company_name": "Example Industrial Group",
                "company_sector": "Industrial",
                "signal_type": "PARTNERSHIP",
                "signal_title": "Example Industrial Group signs a major partnership",
                "possible_event": True,
                "event_type": "PARTNER_EVENT",
                "event_probability": 70,
                "commercial_value": 75,
                "opportunity_window": "DAYS_30_60",
                "fact": "The source states the agreement was signed before the Prime Minister.",
                "inference": "A signing of this scale is normally marked publicly.",
                "prediction": "A ceremony may follow. Not confirmed.",
                "why_now": "The agreement is recent and government-witnessed.",
                "sales_angle": "Signing ceremony production and VIP management.",
                "recommended_services": ["EVENT_MANAGEMENT", "VIP_MANAGEMENT"],
                "recommended_action": "CONTACT_COMMUNICATIONS",
                "confidence": 0.9,
            },
        },
    )
    assert response.status_code == 200
    stats = response.json()
    assert stats["signals_created"] == 1
    assert stats["opportunities_created"] == 1

    item = client.get("/api/v1/opportunities").json()[0]
    assert item["signal"]["source"]["ingest_mode"] == "ANALYST"
    assert item["fact"].startswith("The source states")


def test_analyst_signal_requires_a_source_url(client: TestClient) -> None:
    response = client.post(
        "/api/v1/ingest/signals",
        json={"content": "x", "extraction": {"company_name": "X"}},
    )
    assert response.status_code == 422


def test_analyst_extraction_is_schema_validated(client: TestClient) -> None:
    response = client.post(
        "/api/v1/ingest/signals",
        json={
            "source_url": "https://a.test/1",
            "content": "some content long enough to pass nothing in particular",
            "extraction": {"company_name": "X", "event_probability": 500},
        },
    )
    assert response.status_code == 422


def test_contact_discovery_endpoint_with_no_sources(client: TestClient) -> None:
    response = client.post("/api/v1/ingest/contacts/discover", json={})
    assert response.status_code == 200
    assert response.json()["contacts_found"] == 0


def test_scheduler_status_endpoint(client: TestClient) -> None:
    body = client.get("/api/v1/maintenance/scheduler").json()
    assert body["enabled"] is False
    assert "interval_hours" in body


def test_manual_cycle_endpoint(client: TestClient) -> None:
    body = client.post("/api/v1/maintenance/cycle").json()
    assert body["error"] is None
    for stage in ("ingestion", "contacts", "rescore"):
        assert stage in body
