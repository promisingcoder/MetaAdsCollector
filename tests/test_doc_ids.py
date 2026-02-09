"""Tests for dynamic doc_id extraction in MetaAdsClient."""


from meta_ads_collector.client import MetaAdsClient


def _make_client() -> MetaAdsClient:
    """Create a minimal client for testing _extract_doc_ids."""
    client = MetaAdsClient.__new__(MetaAdsClient)
    return client


class TestExtractDocIds:
    """Tests for MetaAdsClient._extract_doc_ids."""

    def test_pattern1_relay_registration(self):
        """Pattern 1: __d("AdLibrary...Query") with nearby numeric ID."""
        html = (
            'some preamble __d("AdLibrarySearchPaginationQuery_abcdef",[],{}) '
            'blah blah "25464068859919530" more stuff'
        )
        client = _make_client()
        doc_ids = client._extract_doc_ids(html)
        assert doc_ids.get("AdLibrarySearchPaginationQuery") == "25464068859919530"

    def test_pattern2_name_then_queryid(self):
        """Pattern 2: 'name':'...Query' ... 'queryID':'...'."""
        html = (
            '{"name":"AdLibrarySearchPaginationQuery","other":"value",'
            '"queryID":"99887766554433"}'
        )
        client = _make_client()
        doc_ids = client._extract_doc_ids(html)
        assert doc_ids.get("AdLibrarySearchPaginationQuery") == "99887766554433"

    def test_pattern3_queryid_then_name(self):
        """Pattern 3: 'queryID':'...' then 'name':'...Query'."""
        html = (
            '{"queryID":"11223344556677","some":"stuff",'
            '"name":"AdLibraryMobileSearchQuery"}'
        )
        client = _make_client()
        doc_ids = client._extract_doc_ids(html)
        assert doc_ids.get("AdLibraryMobileSearchQuery") == "11223344556677"

    def test_multiple_queries_extracted(self):
        """Multiple different queries should all be extracted."""
        html = (
            '{"name":"AdLibrarySearchPaginationQuery","queryID":"1111111111"}'
            '{"name":"AdLibraryTypeaheadQuery","queryID":"2222222222"}'
        )
        client = _make_client()
        doc_ids = client._extract_doc_ids(html)
        assert doc_ids.get("AdLibrarySearchPaginationQuery") == "1111111111"
        assert doc_ids.get("AdLibraryTypeaheadQuery") == "2222222222"

    def test_fallback_on_no_patterns_found(self):
        """If no patterns match, return empty dict."""
        html = "<html><body>Hello World, no doc_ids here</body></html>"
        client = _make_client()
        doc_ids = client._extract_doc_ids(html)
        assert doc_ids == {}

    def test_fallback_on_empty_html(self):
        """Empty HTML returns empty dict."""
        client = _make_client()
        doc_ids = client._extract_doc_ids("")
        assert doc_ids == {}

    def test_fallback_on_none_html(self):
        """None HTML returns empty dict."""
        client = _make_client()
        doc_ids = client._extract_doc_ids(None)
        assert doc_ids == {}

    def test_extracted_ids_used_when_available(self):
        """Verify the client stores extracted doc_ids on its instance."""
        client = MetaAdsClient()
        # Simulate what initialize() does
        client._doc_ids = {"AdLibrarySearchPaginationQuery": "9999999999"}
        assert client._doc_ids["AdLibrarySearchPaginationQuery"] == "9999999999"

    def test_pattern2_with_doc_id_key(self):
        """Pattern 2 also matches 'doc_id' as the key name."""
        html = (
            '{"operationName":"AdLibrarySearchPaginationQuery",'
            '"doc_id":"55555555555555"}'
        )
        client = _make_client()
        doc_ids = client._extract_doc_ids(html)
        assert doc_ids.get("AdLibrarySearchPaginationQuery") == "55555555555555"

    def test_short_numbers_not_matched(self):
        """Numbers shorter than 10 digits should not be matched as doc_ids."""
        html = '{"name":"AdLibrarySearchPaginationQuery","queryID":"12345"}'
        client = _make_client()
        doc_ids = client._extract_doc_ids(html)
        assert "AdLibrarySearchPaginationQuery" not in doc_ids
