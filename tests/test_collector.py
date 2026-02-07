"""Tests for meta_ads_collector.collector (validation and export logic)."""

import pytest

from meta_ads_collector.collector import MetaAdsCollector
from meta_ads_collector.exceptions import InvalidParameterError


class TestParameterValidation:
    def test_valid_params_pass(self):
        MetaAdsCollector._validate_params(
            ad_type="ALL",
            status="ACTIVE",
            search_type="KEYWORD_EXACT_PHRASE",
            sort_by="SORT_BY_TOTAL_IMPRESSIONS",
            country="US",
        )

    def test_valid_params_none_sort(self):
        MetaAdsCollector._validate_params(
            ad_type="ALL",
            status="ACTIVE",
            search_type="KEYWORD_EXACT_PHRASE",
            sort_by=None,
            country="EG",
        )

    def test_invalid_ad_type(self):
        with pytest.raises(InvalidParameterError, match="ad_type"):
            MetaAdsCollector._validate_params("NOPE", "ACTIVE", "KEYWORD_EXACT_PHRASE", None, "US")

    def test_invalid_status(self):
        with pytest.raises(InvalidParameterError, match="status"):
            MetaAdsCollector._validate_params("ALL", "NOPE", "KEYWORD_EXACT_PHRASE", None, "US")

    def test_invalid_search_type(self):
        with pytest.raises(InvalidParameterError, match="search_type"):
            MetaAdsCollector._validate_params("ALL", "ACTIVE", "NOPE", None, "US")

    def test_invalid_sort_by(self):
        with pytest.raises(InvalidParameterError, match="sort_by"):
            MetaAdsCollector._validate_params("ALL", "ACTIVE", "KEYWORD_EXACT_PHRASE", "NOPE", "US")

    def test_invalid_country_too_short(self):
        with pytest.raises(InvalidParameterError, match="country"):
            MetaAdsCollector._validate_params("ALL", "ACTIVE", "KEYWORD_EXACT_PHRASE", None, "X")

    def test_invalid_country_too_long(self):
        with pytest.raises(InvalidParameterError, match="country"):
            MetaAdsCollector._validate_params("ALL", "ACTIVE", "KEYWORD_EXACT_PHRASE", None, "USA")

    def test_invalid_country_numeric(self):
        with pytest.raises(InvalidParameterError, match="country"):
            MetaAdsCollector._validate_params("ALL", "ACTIVE", "KEYWORD_EXACT_PHRASE", None, "12")

    def test_all_ad_types_valid(self):
        for ad_type in ["ALL", "POLITICAL_AND_ISSUE_ADS", "HOUSING_ADS", "EMPLOYMENT_ADS", "CREDIT_ADS"]:
            MetaAdsCollector._validate_params(ad_type, "ACTIVE", "KEYWORD_EXACT_PHRASE", None, "US")

    def test_all_statuses_valid(self):
        for status in ["ACTIVE", "INACTIVE", "ALL"]:
            MetaAdsCollector._validate_params("ALL", status, "KEYWORD_EXACT_PHRASE", None, "US")

    def test_all_search_types_valid(self):
        for search_type in ["KEYWORD_EXACT_PHRASE", "KEYWORD_UNORDERED", "PAGE"]:
            MetaAdsCollector._validate_params("ALL", "ACTIVE", search_type, None, "US")


class TestCollectorConstants:
    """Verify class-level constant aliases match the module constants."""

    def test_ad_type_constants(self):
        assert MetaAdsCollector.AD_TYPE_ALL == "ALL"
        assert MetaAdsCollector.AD_TYPE_POLITICAL == "POLITICAL_AND_ISSUE_ADS"
        assert MetaAdsCollector.AD_TYPE_HOUSING == "HOUSING_ADS"

    def test_status_constants(self):
        assert MetaAdsCollector.STATUS_ACTIVE == "ACTIVE"
        assert MetaAdsCollector.STATUS_INACTIVE == "INACTIVE"

    def test_search_type_constants(self):
        assert MetaAdsCollector.SEARCH_KEYWORD == "KEYWORD_EXACT_PHRASE"
        assert MetaAdsCollector.SEARCH_PAGE == "PAGE"

    def test_sort_constants(self):
        assert MetaAdsCollector.SORT_RELEVANCY is None
        assert MetaAdsCollector.SORT_IMPRESSIONS == "SORT_BY_TOTAL_IMPRESSIONS"
