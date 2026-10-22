"""The ``AdLibraryV3AdDetailsQuery`` payload: parsing, enrichment, client composition and export."""

from __future__ import annotations

import csv
import json
import time
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest

from meta_ads_collector.async_client import AsyncMetaAdsClient
from meta_ads_collector.client import MetaAdsClient, parse_ad_details_response
from meta_ads_collector.collector import MetaAdsCollector
from meta_ads_collector.constants import DOC_ID_AD_DETAILS
from meta_ads_collector.exceptions import MetaAdsError, RateLimitError
from meta_ads_collector.exports import CSV_COLUMNS, ad_to_csv_row
from meta_ads_collector.models import Ad, PageInfo

from .meta_detail_samples import COMMERCIAL_EU_DETAILS, POLITICAL_US_DETAILS


def _combined(sample: dict) -> dict:
    data = deepcopy(sample["search_row"])
    data["ad_details"] = deepcopy(sample["ad_details"])
    return data


def _graphql_reply(details, errors=None) -> dict:
    reply: dict = {"data": {"ad_library_main": {"ad_details": details}}, "extensions": {"is_final": True}}
    if errors is not None:
        reply["errors"] = errors
    return reply


# ---------------------------------------------------------------------------
# Model parsing
# ---------------------------------------------------------------------------


def test_commercial_eu_details_populate_transparency_targeting_and_payers():
    data = _combined(COMMERCIAL_EU_DETAILS)
    details = COMMERCIAL_EU_DETAILS["ad_details"]
    eu = details["transparency_by_location"]["eu_transparency"]
    ad = Ad.from_graphql_response(data)

    assert ad.ad_details == details
    assert ad.eu_transparency == eu
    assert ad.uk_transparency == details["transparency_by_location"]["uk_transparency"]
    assert ad.br_transparency is None
    assert ad.eu_total_reach == eu["eu_total_reach"]
    assert ad.targets_eu is True
    assert ad.targeting is not None
    assert ad.targeting.age_min == eu["age_audience"]["min"]
    assert ad.targeting.age_max == eu["age_audience"]["max"]
    assert ad.targeting.genders == [eu["gender_audience"]]
    assert ad.targeting.locations == [item["name"] for item in eu["location_audience"] if not item["excluded"]]
    assert ad.targeting.excluded_locations == [item["name"] for item in eu["location_audience"] if item["excluded"]]
    expected_types: list[str] = []
    for item in eu["location_audience"]:
        if item["type"] not in expected_types:
            expected_types.append(item["type"])
    assert ad.targeting.location_types == expected_types
    assert ad.payer_beneficiary_data == details["aaa_info"]["payer_beneficiary_data"]
    assert ad.aaa_info == details["aaa_info"]
    expected_names: list[str] = []
    for item in details["aaa_info"]["payer_beneficiary_data"]:
        for key in ("payer", "beneficiary"):
            if item[key] not in expected_names:
                expected_names.append(item[key])
    assert ad.beneficiary_payers == expected_names
    assert ad.verified_voice_context == details["verified_voice_context"]
    assert ad.violation_types == details["violation_types"]
    assert ad.is_violating_eu_siep is details["is_violating_eu_siep"]
    assert ad.page_spend == details["advertiser"]["ad_library_page_info"]["page_spend"]


def test_details_fill_advertiser_page_fields_without_overwriting_search_row_values():
    data = _combined(COMMERCIAL_EU_DETAILS)
    page_info = COMMERCIAL_EU_DETAILS["ad_details"]["advertiser"]["ad_library_page_info"]["page_info"]
    data["page_like_count"] = page_info["likes"] + 5  # the search row wins for shared fields
    ad = Ad.from_graphql_response(data)

    assert ad.page is not None
    assert ad.page.id == data["page_id"]
    assert ad.page.name == data["page_name"]
    assert ad.page.likes == page_info["likes"] + 5
    assert ad.page.verification == page_info["page_verification"]
    assert ad.page.verified is (page_info["page_verification"] != "NOT_VERIFIED")
    assert ad.page.category == page_info["page_category"]
    assert ad.page.entity_type == page_info["entity_type"]
    assert ad.page.is_restricted is page_info["page_is_restricted"]
    assert ad.page.cover_photo_url == page_info["page_cover_photo"]
    assert ad.page.profile_picture_url == page_info["profile_photo"]
    assert ad.page.about == COMMERCIAL_EU_DETAILS["ad_details"]["advertiser"]["page"]["about"]["text"]


def test_political_details_build_audience_distributions_from_insights():
    data = _combined(POLITICAL_US_DETAILS)
    insights = POLITICAL_US_DETAILS["ad_details"]["insights"]
    page_info = POLITICAL_US_DETAILS["ad_details"]["advertiser"]["ad_library_page_info"]["page_info"]
    ad = Ad.from_graphql_response(data)

    assert ad.insights == insights
    expected_rows = sum(
        1 for item in insights["age_gender_data"] for gender in ("female", "male", "unknown")
        if item.get(gender) is not None
    )
    assert len(ad.age_gender_distribution) == expected_rows
    first = insights["age_gender_data"][0]
    assert ad.age_gender_distribution[0].category == f"{first['age_range']}_female"
    assert ad.age_gender_distribution[0].percentage == pytest.approx(first["female"])
    regions = [item["region"] for item in insights["location_data"]]
    assert [entry.category for entry in ad.region_distribution] == regions
    assert ad.page is not None
    assert ad.page.verified is True
    assert ad.page.verification == "BLUE_VERIFIED"
    assert ad.page.ig_username == page_info["ig_username"]
    assert ad.page.ig_followers == page_info["ig_followers"]
    assert ad.page.ig_verified is page_info["ig_verification"]
    assert ad.page.alias == page_info["page_alias"]
    assert ad.eu_transparency is None
    assert ad.eu_total_reach is None
    assert ad.bylines == [data["byline"]]
    assert ad.disclaimer == data["disclaimer_label"]
    assert ad.impressions_text == data["impressions_with_index"]["impressions_text"]
    assert ad.impressions_index == data["impressions_with_index"]["impressions_index"]


def test_details_only_payload_builds_page_from_advertiser_block():
    details = deepcopy(COMMERCIAL_EU_DETAILS["ad_details"])
    page_info = details["advertiser"]["ad_library_page_info"]["page_info"]
    ad = Ad.from_graphql_response({"ad_archive_id": "42", "page_id": page_info["page_id"], "ad_details": details})

    assert ad.id == "42"
    assert ad.page is not None
    assert ad.page.id == page_info["page_id"]
    assert ad.page.name == page_info["page_name"]
    assert ad.page.likes == page_info["likes"]
    assert ad.page.page_url == page_info["page_profile_uri"]
    assert all(creative.to_dict() == {} for creative in ad.creatives)  # no creative content without a row


def test_details_parsing_is_lossless_and_does_not_mutate_input():
    data = _combined(COMMERCIAL_EU_DETAILS)
    snapshot = deepcopy(data)
    ad = Ad.from_graphql_response(data)

    assert data == snapshot
    assert ad.api_fields == snapshot
    exported = json.loads(ad.to_json())
    assert exported["api_fields"] == snapshot
    assert exported["ad_details"] == snapshot["ad_details"]
    assert exported["eu_total_reach"] == ad.eu_total_reach
    assert exported["payer_beneficiary_data"] == ad.payer_beneficiary_data
    assert exported["page"]["verification"] == ad.page.verification
    ad.ad_details["advertiser"] = None
    assert ad.api_fields["ad_details"]["advertiser"] is not None


@pytest.mark.parametrize("value", [None, {}, [], "text", 5])
def test_absent_or_malformed_details_leave_search_row_parsing_unchanged(value):
    data = deepcopy(COMMERCIAL_EU_DETAILS["search_row"])
    baseline = Ad.from_graphql_response(deepcopy(data))
    data["ad_details"] = value
    ad = Ad.from_graphql_response(data)
    assert ad.ad_details is None
    assert ad.eu_transparency is None
    assert ad.targeting is None
    assert ad.page == baseline.page
    assert ad.payer_beneficiary_data == []
    assert ad.api_fields == data


def test_partial_details_tolerate_missing_sections():
    details = {"advertiser": {"page": {"id": "9", "about": {"text": ""}}}, "insights": None,
               "transparency_by_location": None, "aaa_info": None, "violation_types": None}
    ad = Ad.from_graphql_response({"ad_archive_id": "1", "page_id": "9", "ad_details": details})
    assert ad.ad_details == details
    assert ad.page is not None and ad.page.id == "9"
    assert ad.insights is None
    assert ad.violation_types == []
    assert ad.targeting is None


# ---------------------------------------------------------------------------
# Enrichment merges detail fields into sparse ads
# ---------------------------------------------------------------------------


def test_enrich_ad_fills_detail_fields_and_preserves_original():
    collector = MetaAdsCollector.__new__(MetaAdsCollector)
    collector.client = MagicMock()
    collector.client.get_ad_details.return_value = _combined(COMMERCIAL_EU_DETAILS)
    row = COMMERCIAL_EU_DETAILS["search_row"]
    sparse = Ad(id=row["ad_archive_id"], page=PageInfo(id=row["page_id"], name=""))

    enriched = collector.enrich_ad(sparse)

    assert enriched is not sparse
    assert sparse.page.name == "" and sparse.ad_details is None
    assert enriched.page.name == row["page_name"]
    assert enriched.eu_total_reach == COMMERCIAL_EU_DETAILS["ad_details"]["transparency_by_location"][
        "eu_transparency"]["eu_total_reach"]
    assert enriched.targeting is not None and enriched.targeting.age_min is not None
    assert enriched.payer_beneficiary_data
    assert enriched.ad_details == COMMERCIAL_EU_DETAILS["ad_details"]
    assert enriched.raw_data["ad_details"] == COMMERCIAL_EU_DETAILS["ad_details"]
    collector.client.get_ad_details.assert_called_once_with(ad_archive_id=row["ad_archive_id"], page_id=row["page_id"])


# ---------------------------------------------------------------------------
# Client composition
# ---------------------------------------------------------------------------


def _sync_client(search_rows, reply, status=200):
    client = MetaAdsClient.__new__(MetaAdsClient)
    client._initialized = True
    client._doc_ids = {}
    client._tokens = {"lsd": "lsd-token", "x-asbd-id": "359341"}
    client._fingerprint = MagicMock()
    client._fingerprint.get_graphql_headers.return_value = {"content-type": "application/x-www-form-urlencoded"}
    client._fingerprint.get_default_headers.return_value = {}
    client._consecutive_errors = 3
    client._init_time = time.time()
    client._max_session_age = 1800
    captured: dict = {}

    def build(doc_id, variables, friendly_name):
        captured.update(doc_id=doc_id, variables=variables, friendly_name=friendly_name)
        return {"doc_id": doc_id, "variables": json.dumps(variables)}

    client._build_graphql_payload = build
    client.search_ads = MagicMock(return_value=({"ads": search_rows}, None))
    client._make_graphql_request = MagicMock(
        return_value=MagicMock(status_code=status, text="for (;;);" + json.dumps(reply)),
    )
    client._make_request = MagicMock(return_value=MagicMock(status_code=403, text=""))
    return client, captured


def test_get_ad_insights_sends_the_details_query_and_returns_the_payload():
    details = COMMERCIAL_EU_DETAILS["ad_details"]
    client, captured = _sync_client([], _graphql_reply(details))

    result = client.get_ad_insights("123", "456")

    assert result == details
    assert captured["doc_id"] == DOC_ID_AD_DETAILS
    assert captured["friendly_name"] == "AdLibraryV3AdDetailsQuery"
    variables = captured["variables"]
    assert variables["adArchiveID"] == "123" and variables["pageID"] == "456"
    assert variables["country"] == "ALL"
    assert variables["isAdNonPolitical"] is False and variables["isAdNotAAAEligible"] is False
    assert variables["sessionID"]
    headers = client._make_graphql_request.call_args.args[1]
    assert headers["x-fb-friendly-name"] == "AdLibraryV3AdDetailsQuery"
    assert headers["x-fb-lsd"] == "lsd-token"
    assert headers["referer"].endswith("?id=123")
    assert client._consecutive_errors == 0


def test_get_ad_insights_prefers_a_dynamically_extracted_doc_id():
    client, captured = _sync_client([], _graphql_reply(COMMERCIAL_EU_DETAILS["ad_details"]))
    client._doc_ids = {"AdLibraryV3AdDetailsQuery": "999"}
    client.get_ad_insights("1", "2", country="DE")
    assert captured["doc_id"] == "999"
    assert captured["variables"]["country"] == "DE"


def test_get_ad_insights_raises_when_meta_returns_no_details():
    client, _ = _sync_client([], _graphql_reply(None, errors=[{"message": "field_exception", "code": 1}]))
    with pytest.raises(MetaAdsError, match="field_exception"):
        client.get_ad_insights("1", "2")


def test_get_ad_insights_raises_rate_limit_error():
    client, _ = _sync_client([], _graphql_reply(None, errors=[{"message": "Rate limit exceeded", "code": 1675004}]))
    with pytest.raises(RateLimitError):
        client.get_ad_insights("1", "2")


def test_get_ad_insights_raises_on_http_error():
    client, _ = _sync_client([], {}, status=500)
    with pytest.raises(MetaAdsError, match="500"):
        client.get_ad_insights("1", "2")


def test_parse_ad_details_response_keeps_partial_payloads_with_field_errors():
    details = {"advertiser": {"page": {"id": "1"}}, "insights": None}
    reply = _graphql_reply(details, errors=[{"message": "field_exception", "code": 1}])
    assert parse_ad_details_response(reply, "1") == details
    with pytest.raises(MetaAdsError):
        parse_ad_details_response({"data": None}, "1")
    with pytest.raises(MetaAdsError):
        parse_ad_details_response("not json", "1")


def test_get_ad_details_combines_search_row_and_details():
    row = deepcopy(COMMERCIAL_EU_DETAILS["search_row"])
    details = COMMERCIAL_EU_DETAILS["ad_details"]
    client, _ = _sync_client([{"ad_archive_id": "other"}, row], _graphql_reply(details))

    result = client.get_ad_details(row["ad_archive_id"], page_id=row["page_id"])

    assert result == {**row, "ad_details": details}
    assert client.search_ads.call_args.kwargs["page_ids"] == [row["page_id"]]
    assert client._make_request.call_count == 0  # the HTML fallback is not needed


def test_get_ad_details_returns_details_when_the_row_is_not_in_the_page_search():
    details = COMMERCIAL_EU_DETAILS["ad_details"]
    client, _ = _sync_client([{"ad_archive_id": "other"}], _graphql_reply(details))
    result = client.get_ad_details("123", page_id="456")
    assert result == {"ad_archive_id": "123", "page_id": "456", "ad_details": details}
    ad = Ad.from_graphql_response(result)
    assert ad.page.name == details["advertiser"]["ad_library_page_info"]["page_info"]["page_name"]


def test_get_ad_details_returns_the_row_when_the_details_query_fails():
    row = deepcopy(COMMERCIAL_EU_DETAILS["search_row"])
    client, _ = _sync_client([row], _graphql_reply(None, errors=[{"message": "down", "code": 2}]))
    assert client.get_ad_details(row["ad_archive_id"], page_id=row["page_id"]) == row


def test_get_ad_details_without_page_id_falls_back_to_the_html_page():
    client, _ = _sync_client([], _graphql_reply(COMMERCIAL_EU_DETAILS["ad_details"]))
    with pytest.raises(NotImplementedError):
        client.get_ad_details("123")
    client.search_ads.assert_not_called()
    client._make_graphql_request.assert_not_called()
    assert client._make_request.call_count == 1


def test_get_ad_details_raises_when_every_approach_fails():
    client, _ = _sync_client([], _graphql_reply(None, errors=[{"message": "down", "code": 2}]))
    client.search_ads.side_effect = MetaAdsError("search down")
    with pytest.raises(NotImplementedError):
        client.get_ad_details("123", page_id="456")


def _async_client(search_rows, reply, status=200):
    client = AsyncMetaAdsClient.__new__(AsyncMetaAdsClient)
    client._initialized = True
    client._doc_ids = {}
    client._tokens = {"lsd": "lsd-token"}
    client._fingerprint = MagicMock()
    client._fingerprint.get_graphql_headers.return_value = {}
    client._fingerprint.get_default_headers.return_value = {}
    captured: dict = {}

    def build(doc_id, variables, friendly_name):
        captured.update(doc_id=doc_id, variables=variables, friendly_name=friendly_name)
        return {"doc_id": doc_id}

    client._build_graphql_payload = build
    client.search_ads = AsyncMock(return_value=({"ads": search_rows}, None))
    graphql = MagicMock(status_code=status, text="for (;;);" + json.dumps(reply))
    html = MagicMock(status_code=403, text="")

    async def request(method, url, **kwargs):
        return graphql if method == "POST" else html

    client._make_request = AsyncMock(side_effect=request)
    return client, captured


@pytest.mark.asyncio
async def test_async_get_ad_details_combines_search_row_and_details():
    row = deepcopy(COMMERCIAL_EU_DETAILS["search_row"])
    details = COMMERCIAL_EU_DETAILS["ad_details"]
    client, captured = _async_client([row], _graphql_reply(details))

    result = await client.get_ad_details(row["ad_archive_id"], page_id=row["page_id"])

    assert result == {**row, "ad_details": details}
    assert captured["doc_id"] == DOC_ID_AD_DETAILS
    assert captured["variables"]["adArchiveID"] == row["ad_archive_id"]
    assert captured["variables"]["pageID"] == row["page_id"]
    assert client._make_request.await_count == 1


@pytest.mark.asyncio
async def test_async_get_ad_insights_raises_on_missing_details():
    client, _ = _async_client([], _graphql_reply(None, errors=[{"message": "nope", "code": 3}]))
    with pytest.raises(MetaAdsError, match="nope"):
        await client.get_ad_insights("1", "2")


@pytest.mark.asyncio
async def test_async_get_ad_details_raises_when_every_approach_fails():
    client, _ = _async_client([], _graphql_reply(None, errors=[{"message": "nope", "code": 3}]))
    with pytest.raises(NotImplementedError):
        await client.get_ad_details("1", page_id="2")


# ---------------------------------------------------------------------------
# CSV export of the flattened schema
# ---------------------------------------------------------------------------


def test_csv_row_matches_the_shared_columns_and_exposes_detail_fields(tmp_path):
    ad = Ad.from_graphql_response(_combined(COMMERCIAL_EU_DETAILS))
    row = ad_to_csv_row(ad)

    assert tuple(row) == CSV_COLUMNS
    assert row["eu_total_reach"] == ad.eu_total_reach
    assert row["page_like_count"] == ad.page.likes
    assert row["payer_beneficiary"] == ";".join(
        f"{item['payer']}|{item['beneficiary']}" for item in ad.payer_beneficiary_data
    )
    assert json.loads(row["api_fields"]) == ad.api_fields

    path = tmp_path / "details.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(CSV_COLUMNS))
        writer.writeheader()
        writer.writerow(row)
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
    assert reader.fieldnames == list(CSV_COLUMNS)
    assert json.loads(rows[0]["api_fields"])["ad_details"] == COMMERCIAL_EU_DETAILS["ad_details"]


def test_csv_row_blanks_missing_values():
    row = ad_to_csv_row(Ad(id="1"))
    assert tuple(row) == CSV_COLUMNS
    assert row["page_like_count"] == "" and row["eu_total_reach"] == "" and row["payer_beneficiary"] == ""
    assert row["api_fields"] == "null"


# ---------------------------------------------------------------------------
# Live checks against the real Ad Library
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_live_ad_insights_return_the_details_panel_for_an_actual_ad(collected_ads):
    source = next(ad for ad in collected_ads if ad.page and ad.page.id and ad.raw_data)
    with MetaAdsClient(timeout=30, max_retries=2) as client:
        details = client.get_ad_insights(source.id, source.page.id)
    page_info = details["advertiser"]["ad_library_page_info"]["page_info"]
    assert page_info["page_id"] == source.page.id
    assert page_info["page_name"]
    assert "transparency_by_location" in details and "aaa_info" in details

    enriched = Ad.from_graphql_response({**deepcopy(source.raw_data), "ad_details": details})
    assert enriched.ad_details == details
    assert enriched.page.verification
    assert enriched.page.category or enriched.page.about or enriched.page.likes is not None
    assert enriched.to_dict()["api_fields"]["ad_details"] == details
    if enriched.eu_transparency:
        assert enriched.targeting is not None
        assert enriched.eu_total_reach == enriched.eu_transparency.get("eu_total_reach")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_async_ad_insights_match_the_sync_payload_shape(collected_ads):
    source = next(ad for ad in collected_ads if ad.page and ad.page.id)
    async with AsyncMetaAdsClient(timeout=30, max_retries=2) as client:
        details = await client.get_ad_insights(source.id, source.page.id)
    assert details["advertiser"]["ad_library_page_info"]["page_info"]["page_id"] == source.page.id
    assert set(details) >= {"advertiser", "transparency_by_location", "violation_types"}
