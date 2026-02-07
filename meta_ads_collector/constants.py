"""Constants and default configuration for Meta Ads Collector."""

# ---------------------------------------------------------------------------
# HTTP / browser fingerprint
# ---------------------------------------------------------------------------
CHROME_VERSION = "131"
CHROME_FULL_VERSION = "131.0.6778.140"
USER_AGENT = (
    f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    f"(KHTML, like Gecko) Chrome/{CHROME_VERSION}.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Request defaults
# ---------------------------------------------------------------------------
DEFAULT_TIMEOUT = 30  # seconds
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 2.0  # seconds, base for exponential backoff

# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------
MAX_SESSION_AGE = 1800  # seconds – re-initialize after 30 minutes

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
DEFAULT_RATE_LIMIT_DELAY = 2.0  # seconds between requests
DEFAULT_JITTER = 1.0  # seconds of random jitter added to delay
RATE_LIMIT_BACKOFF_BASE = 5  # seconds, multiplied by retry count
RATE_LIMIT_JITTER_RANGE = (1, 3)  # uniform random jitter bounds

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
DEFAULT_PAGE_SIZE = 10  # results per API request (max ~30)

# ---------------------------------------------------------------------------
# GraphQL document IDs (may change with Facebook updates)
# ---------------------------------------------------------------------------
DOC_ID_SEARCH = "25464068859919530"  # AdLibrarySearchPaginationQuery
DOC_ID_TYPEAHEAD = "9755915494515334"  # useAdLibraryTypeaheadSuggestionDataSourceQuery

# ---------------------------------------------------------------------------
# Fallback token values
# Used when fresh values cannot be extracted from the page HTML.
# ---------------------------------------------------------------------------
FALLBACK_DYN = (
    "7xeUmwlECdwn8K2Wmh0no6u5U4e1Fx-ewSAwHwNw9G2S2q0_EtxG4o0B-qbwgE1EEb87C"
    "1xwEwgo9oO0n24oaEd86a3a1YwBgao6C0Mo6i588Etw8WfK1LwPxe2GewbCXwJwmE2eUlwh"
    "E2Lw6OyES0gq0K-1LwqobU3Cwr86C1nwf6Eb87u1rwGwto461ww"
)
FALLBACK_CSR = (
    "gjSxK8GXhkbjAmy4j8gBkiHG8FVCIJBHjpXUrByK5HxuquEyUK5Emz8Oaw9G3S5UoyUK588"
    "E4a2W0C8eEcE4S2m12wg8O1fwau1IwiEow9qE5S3KUK320g-1fDw49w2v80PS07XU0ptw2Ao"
    "05Ey02zC0aFw0hIQ00BPo06XK6k00CSo072W09xw4jw"
)
FALLBACK_REV = "1032373751"

# ---------------------------------------------------------------------------
# Ad type constants
# ---------------------------------------------------------------------------
AD_TYPE_ALL = "ALL"
AD_TYPE_POLITICAL = "POLITICAL_AND_ISSUE_ADS"
AD_TYPE_HOUSING = "HOUSING_ADS"
AD_TYPE_EMPLOYMENT = "EMPLOYMENT_ADS"
AD_TYPE_CREDIT = "CREDIT_ADS"

VALID_AD_TYPES = frozenset({
    AD_TYPE_ALL,
    AD_TYPE_POLITICAL,
    AD_TYPE_HOUSING,
    AD_TYPE_EMPLOYMENT,
    AD_TYPE_CREDIT,
})

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------
STATUS_ACTIVE = "ACTIVE"
STATUS_INACTIVE = "INACTIVE"
STATUS_ALL = "ALL"

VALID_STATUSES = frozenset({STATUS_ACTIVE, STATUS_INACTIVE, STATUS_ALL})

# ---------------------------------------------------------------------------
# Search type constants
# ---------------------------------------------------------------------------
SEARCH_KEYWORD = "KEYWORD_EXACT_PHRASE"
SEARCH_EXACT = "KEYWORD_EXACT_PHRASE"
SEARCH_UNORDERED = "KEYWORD_UNORDERED"
SEARCH_PAGE = "PAGE"

VALID_SEARCH_TYPES = frozenset({
    SEARCH_KEYWORD,
    SEARCH_UNORDERED,
    SEARCH_PAGE,
})

# ---------------------------------------------------------------------------
# Sort constants
# ---------------------------------------------------------------------------
SORT_RELEVANCY = None  # Omit sortData for server-default relevancy
SORT_IMPRESSIONS = "SORT_BY_TOTAL_IMPRESSIONS"

VALID_SORT_MODES = frozenset({None, SORT_IMPRESSIONS})

# ---------------------------------------------------------------------------
# Media type constants
# ---------------------------------------------------------------------------
MEDIA_TYPE_ALL = "ALL"
MEDIA_TYPE_IMAGE = "IMAGE"
MEDIA_TYPE_VIDEO = "VIDEO"
MEDIA_TYPE_MEME = "MEME"
MEDIA_TYPE_NONE = "NONE"
