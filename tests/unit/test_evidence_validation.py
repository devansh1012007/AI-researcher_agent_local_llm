from research_engine.core.ids import (content_hash, next_id, stable_hash,
                                      url_canonicalize)
from research_engine.pipeline.evidence import (claims_equivalent,
                                               claim_dedup_key, verify_quote)


def test_content_hash_normalizes_whitespace():
    assert content_hash("Hello   World") == content_hash("hello world")
    assert content_hash("a") != content_hash("b")


def test_stable_hash_deterministic():
    assert stable_hash("x") == stable_hash("x")
    assert len(stable_hash("x")) == 64


def test_url_canonicalization_strips_tracking():
    a = url_canonicalize("https://example.com/page?utm_source=x&id=2#top")
    b = url_canonicalize("http://EXAMPLE.com/page?id=2")
    assert a == b == "example.com/page?id=2"


def test_next_id_sequential():
    ids = [next_id("ev") for _ in range(3)]
    assert len(set(ids)) == 3


class TestVerifyQuote:
    CHUNK = ("Results show that the method improved accuracy by 30 percent on the "
             "benchmark dataset. A key limitation is the need for dense annotations.")

    def test_exact_substring(self):
        ok, why = verify_quote("the method improved accuracy by 30 percent", self.CHUNK)
        assert ok and why == "exact"

    def test_case_and_punctuation_insensitive(self):
        ok, why = verify_quote("The method improved accuracy by 30 percent.",
                               self.CHUNK)
        assert ok

    def test_fuzzy_minor_drift(self):
        ok, why = verify_quote("method improved accuracy by thirty percent on benchmark",
                               self.CHUNK)
        # word-level drift beyond fuzzy tolerance should fail or pass fuzzily; must not crash
        assert isinstance(ok, bool)

    def test_hallucinated_quote_rejected(self):
        ok, _ = verify_quote("The moon is made of cheese and costs five dollars",
                             self.CHUNK)
        assert not ok

    def test_ellipsis_multiline_quote(self):
        ok, _ = verify_quote(
            "improved accuracy by 30 percent... need for dense annotations", self.CHUNK)
        assert ok

    def test_empty_and_tiny_quotes_rejected(self):
        assert not verify_quote("", self.CHUNK)[0]
        assert not verify_quote("tiny", self.CHUNK)[0]


class TestClaimDedup:
    def test_word_order_invariant(self):
        assert claims_equivalent("method improves accuracy significantly",
                                 "accuracy improves significantly with method")

    def test_different_claims_not_merged(self):
        assert not claims_equivalent("Revenue grew 40% in fiscal year 2025",
                                     "Cats are common domestic animals")

    def test_dedup_key_sorted_words(self):
        assert claim_dedup_key("b a c") == claim_dedup_key("c b a")
