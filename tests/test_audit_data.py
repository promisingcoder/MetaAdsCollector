"""Regression probes for model, filtering, and URL edge cases.

These controlled checks mutate captured public Meta rows. They supplement the
live suite; they do not establish that Meta currently returns each mutation.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from meta_ads_collector.filters import FilterConfig, passes_filter
from meta_ads_collector.models import Ad, ImpressionRange, SpendRange
from tests.audit_meta_samples import CAPTURED_ADS
from tests.meta_full_sample import FULL_META_AD


def _captured_ad_raw() -> dict:
    """Return an isolated copy of a real Meta row for controlled mutations."""
    return deepcopy(CAPTURED_ADS[0])




def test_graphql_parser_preserves_zero_impression_lower_bound():
    raw = _captured_ad_raw()
    raw["impressions"] = {"lower_bound": 0, "upper_bound": 25}
    ad = Ad.from_graphql_response(raw)

    assert ad.impressions == ImpressionRange(lower_bound=0, upper_bound=25)


def test_graphql_parser_preserves_zero_spend_lower_bound():
    raw = _captured_ad_raw()
    raw["spend"] = {"lower_bound": 0, "upper_bound": 10}
    ad = Ad.from_graphql_response(raw)

    assert ad.spend == SpendRange(lower_bound=0, upper_bound=10, currency=raw.get("currency"))


def test_graphql_parser_preserves_zero_reach_bounds():
    raw = _captured_ad_raw()
    raw["reach"] = {"lower_bound": 0, "upper_bound": 25}
    ad = Ad.from_graphql_response(raw)

    assert ad.reach == ImpressionRange(lower_bound=0, upper_bound=25)


def test_numeric_string_bounds_are_normalized_for_range_filtering():
    raw = _captured_ad_raw()
    raw["impressions"] = {"lower_bound": "0", "upper_bound": "250"}
    raw["spend"] = {"lower_bound": "12", "upper_bound": "99"}
    raw["reach"] = {"lower_bound": "1,000", "upper_bound": "2,000"}
    ad = Ad.from_graphql_response(raw)

    assert ad.impressions == ImpressionRange(lower_bound=0, upper_bound=250)
    assert ad.spend == SpendRange(lower_bound=12, upper_bound=99, currency=raw.get("currency"))
    assert ad.reach == ImpressionRange(lower_bound=1_000, upper_bound=2_000)


def test_large_integer_metric_bounds_keep_exact_precision():
    raw = _captured_ad_raw()
    precise = 9_007_199_254_740_999
    raw["impressions"] = {
        "lower_bound": precise,
        "upper_bound": str(precise + 1),
    }
    ad = Ad.from_graphql_response(raw)

    assert ad.impressions == ImpressionRange(
        lower_bound=precise,
        upper_bound=precise + 1,
    )


def test_ad_dict_serialization_preserves_zero_estimated_audience():
    ad = Ad.from_graphql_response(_captured_ad_raw())
    ad.estimated_audience_size_lower = 0
    ad.estimated_audience_size_upper = 10

    assert ad.to_dict()["estimated_audience_size"] == {
        "lower_bound": 0,
        "upper_bound": 10,
    }




def test_explicit_inactive_boolean_is_not_treated_as_missing():
    raw = _captured_ad_raw()
    raw["is_active"] = False
    ad = Ad.from_graphql_response(raw)

    assert ad.is_active is False


def test_integer_epoch_dates_are_utc_aware():
    raw = _captured_ad_raw()
    ad = Ad.from_graphql_response(raw)
    timestamp = raw["start_date"]

    assert ad.delivery_start_time == datetime.fromtimestamp(timestamp, timezone.utc)
    assert ad.delivery_stop_time == datetime.fromtimestamp(raw["end_date"], timezone.utc)


def test_epoch_zero_start_time_is_not_treated_as_missing():
    raw = _captured_ad_raw()
    raw["start_date"] = 0
    ad = Ad.from_graphql_response(raw)

    assert ad.delivery_start_time == datetime(1970, 1, 1, tzinfo=timezone.utc)


def test_upper_only_estimated_audience_is_serialized():
    ad = Ad.from_graphql_response(_captured_ad_raw())
    ad.estimated_audience_size_upper = 10

    assert ad.to_dict()["estimated_audience_size"] == {
        "lower_bound": None,
        "upper_bound": 10,
    }


def test_partial_estimated_audience_raw_bounds_are_parsed():
    raw = _captured_ad_raw()
    raw["estimated_audience_size"] = {"upperBound": "50"}
    ad = Ad.from_graphql_response(raw)

    assert ad.estimated_audience_size_lower is None
    assert ad.estimated_audience_size_upper == 50
    assert ad.to_dict()["estimated_audience_size"] == {
        "lower_bound": None,
        "upper_bound": 50,
    }




def test_nullable_demographic_percentage_does_not_abort_ad_parsing():
    raw = _captured_ad_raw()
    raw["demographic_distribution"] = [
        {"age": "25-34", "gender": "female", "percentage": None},
        {"age": "35-44", "gender": "male", "percentage": 0.25},
    ]
    ad = Ad.from_graphql_response(raw)

    assert [(row.category, row.percentage) for row in ad.age_gender_distribution] == [
        ("35-44_male", 0.25),
    ]


def test_nullable_or_malformed_distribution_rows_are_skipped_individually():
    raw = _captured_ad_raw()
    raw["demographic_distribution"] = [
        None,
        {"age": "25-34", "gender": "female", "percentage": None},
        {"age": "35-44", "gender": "male", "percentage": "0.25"},
        {"age": "45-54", "gender": "female", "percentage": "not-a-number"},
    ]
    raw["delivery_by_region"] = [
        None,
        {"region": "CA", "percentage": None},
        {"region": "NY", "percentage": "0.5"},
    ]
    ad = Ad.from_graphql_response(raw)

    assert [(row.category, row.percentage) for row in ad.age_gender_distribution] == [
        ("35-44_male", 0.25),
    ]
    assert [(row.category, row.percentage) for row in ad.region_distribution] == [
        ("NY", 0.5),
    ]


def test_null_only_media_entries_do_not_satisfy_media_filters():
    raw = _captured_ad_raw()
    raw["cards"] = []
    raw["videos"] = [None]
    raw["images"] = [None]
    ad = Ad.from_graphql_response(raw)

    assert not passes_filter(ad, FilterConfig(has_video=True))
    assert not passes_filter(ad, FilterConfig(has_image=True))
    assert passes_filter(ad, FilterConfig(has_video=False, has_image=False))


def test_targeting_is_normalized_only_from_supplied_fields():
    raw = _captured_ad_raw()
    assert Ad.from_graphql_response(raw).targeting is None

    raw["targeting"] = {
        "ageMin": "18",
        "age_max": 65,
        "genders": ["female", "male"],
        "locations": [{"name": "United States"}],
        "locationTypes": ["home"],
        "interests": ["running"],
        "excludedLocations": ["California"],
    }
    targeting = Ad.from_graphql_response(raw).targeting
    assert targeting is not None
    assert targeting.to_dict() == {
        "age_min": 18,
        "age_max": 65,
        "genders": ["female", "male"],
        "locations": ["United States"],
        "location_types": ["home"],
        "interests": ["running"],
        "excluded_locations": ["California"],
    }


def test_documented_range_text_formats_keep_their_bounds():
    raw = _captured_ad_raw()
    raw.update(impressions=">1M", spend="$9K-$10K", currency=None)
    ad = Ad.from_graphql_response(raw)

    assert ad.impressions == ImpressionRange(lower_bound=1_000_000, upper_bound=None)
    assert ad.spend == SpendRange(lower_bound=9_000, upper_bound=10_000, currency=None)


def test_ad_json_serialization_keeps_timestamp_offsets_and_raw_payload_on_request():
    raw = _captured_ad_raw()
    timestamp = datetime(2024, 5, 6, 7, 8, tzinfo=timezone(timedelta(hours=3)))
    ad = Ad(id=raw["ad_archive_id"], delivery_start_time=timestamp, raw_data=raw)

    assert ad.to_dict(include_raw=True)["delivery_start_time"] == "2024-05-06T07:08:00+03:00"
    assert ad.to_dict(include_raw=True)["raw_data"] == raw


def test_empty_raw_payload_is_retained_when_raw_export_is_requested():
    ad = Ad(id="empty-raw", raw_data={})

    assert ad.to_dict(include_raw=True)["raw_data"] == {}


def test_full_meta_api_fields_are_preserved_by_default_export():
    raw = deepcopy(FULL_META_AD)
    ad = Ad.from_graphql_response(raw)
    exported = ad.to_dict()

    assert exported["api_fields"] == raw
    assert ad.api_fields == raw
    assert ad.ad_id == raw["ad_id"]
    assert ad.display_format == raw["display_format"]
    assert ad.country_iso_code == raw["country_iso_code"]
    assert ad.targeted_or_reached_countries == raw["targeted_or_reached_countries"]
    assert ad.total_active_time == raw["total_active_time"]
    assert ad.regional_regulation_data == raw["regional_regulation_data"]
    assert ad.additional_info == raw["additional_info"]
    assert ad.ec_certificates == raw["ec_certificates"]
    assert ad.brazil_tax_id == raw["brazil_tax_id"]
    assert ad.page_is_deleted is raw["page_is_deleted"]
    assert ad.contains_sensitive_content is raw["contains_sensitive_content"]
    assert ad.contains_digital_created_media is raw["contains_digital_created_media"]
    assert ad.is_aaa_eligible is raw["is_aaa_eligible"]
    assert ad.collation_count == raw["collation_count"]
    assert ad.bylines == []
    assert ad.disclaimer == raw["disclaimer_label"]


def test_api_fields_accessor_and_raw_export_are_deep_copied():
    raw = deepcopy(FULL_META_AD)
    ad = Ad.from_graphql_response(raw)
    raw["regional_regulation_data"]["mutated_by_caller"] = True
    fields = ad.api_fields
    assert fields is not None
    fields["regional_regulation_data"]["mutated_by_accessor"] = True
    exported = ad.to_dict(include_raw=True)

    assert "mutated_by_caller" not in ad.raw_data["regional_regulation_data"]
    assert "mutated_by_accessor" not in exported["api_fields"]["regional_regulation_data"]
    assert exported["raw_data"] == exported["api_fields"]


def test_nested_snapshot_fields_normalize_without_changing_raw_input():
    raw = deepcopy(FULL_META_AD)
    snapshot = raw["snapshot"]
    for key in (
        "page_id", "page_name", "body", "caption", "title", "link_url",
        "link_description", "cards", "images", "videos", "page_profile_uri",
    ):
        raw.pop(key, None)
    ad = Ad.from_graphql_response(raw)
    snapshot_videos = snapshot.get("videos") or []
    expected_video = next(
        (video.get("video_hd_url") or video.get("video_sd_url") for video in snapshot_videos),
        None,
    )

    assert ad.page is not None
    assert ad.page.id == snapshot["page_id"]
    assert ad.page.name == snapshot["page_name"]
    assert expected_video is not None
    assert any(
        creative.video_hd_url == expected_video or creative.video_sd_url == expected_video
        for creative in ad.creatives
    )
    assert ad.api_fields == raw


def test_byline_and_disclaimer_label_aliases_are_normalized_from_response():
    raw = deepcopy(FULL_META_AD)
    raw["byline"] = "Paid for by Example Organization"
    raw["disclaimer_label"] = "Paid for by Example Organization"
    ad = Ad.from_graphql_response(raw)

    assert ad.bylines == ["Paid for by Example Organization"]
    assert ad.disclaimer == "Paid for by Example Organization"
    assert ad.api_fields["byline"] == raw["byline"]
    assert ad.api_fields["disclaimer_label"] == raw["disclaimer_label"]


def test_zero_and_false_transparency_alias_values_are_retained():
    raw = deepcopy(FULL_META_AD)
    raw["collation_count"] = 0
    raw["total_active_time"] = 0
    raw["page_is_deleted"] = False
    raw["is_aaa_eligible"] = False
    raw["contains_sensitive_content"] = False
    ad = Ad.from_graphql_response(raw)

    assert ad.collation_count == 0
    assert ad.total_active_time == 0
    assert ad.page_is_deleted is False
    assert ad.is_aaa_eligible is False
    assert ad.contains_sensitive_content is False
    assert ad.to_dict()["api_fields"] == raw
