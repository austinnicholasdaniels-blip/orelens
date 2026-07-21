"""
Regression tests for the attribution guard.

These exist because a GlobeNewswire release about IperionX was once recorded
as an Aya Gold & Silver financing, and The Assayer reported it to a member as
fact. Any change that lets a source document be bound to a company it never
names must fail here.
"""
from app.services.attribution import (
    distinctive_tokens, source_names_company,
)

IPERIONX = ("IperionX Announces Pricing of Public Offering of American "
            "Depositary Shares")


# ---------------------------------------------------------------- the incident
def test_iperionx_release_is_not_an_aya_financing():
    assert source_names_company(IPERIONX, "AYA", "Aya Gold & Silver") is False


def test_iperionx_release_still_matches_iperionx():
    assert source_names_company(IPERIONX, "IPX", "IperionX") is True


def test_short_db_name_cannot_substring_match():
    # the original enabler: company name stored as bare "AYA"
    assert source_names_company(IPERIONX, "AYA", "AYA") is False


# ------------------------------------------------------------- substring traps
def test_substring_inside_word_never_matches():
    for text in ["Himalaya Shipping reports", "playa del carmen project",
                 "Depositary Shares", "Ayahuasca Ventures Inc"]:
        assert source_names_company(text, "AYA", "Aya Gold & Silver") is False


def test_generic_sector_words_are_not_identification():
    # "Gold"/"Mining" must never bind a release to a company
    assert source_names_company(
        "Barrick Gold Mining reports record quarter", "XYZ",
        "Gold Mining Corp") is False


def test_company_with_only_generic_words_requires_ticker():
    assert distinctive_tokens("Gold Resources Corp") == []
    assert source_names_company("Some gold resources news", "GRC",
                                "Gold Resources Corp") is False
    assert source_names_company("(TSXV: GRC) announces placement", "GRC",
                                "Gold Resources Corp") is True


# ------------------------------------------------------------- true positives
def test_exchange_parenthetical_matches():
    for text in ["(TSX: AYA) announces results",
                 "(TSXV:ABC) closes financing",
                 "(NYSE American: IPX) prices offering",
                 "(CSE: XYZ) engages IR firm"]:
        tick = text.split(":")[1].split(")")[0].strip()
        assert source_names_company(text, tick, "Some Name") is True


def test_distinctive_name_word_matches():
    assert source_names_company(
        "Aya Gold & Silver Announces Q2 Production at Zgounder",
        "AYA", "Aya Gold & Silver") is True


def test_standalone_ticker_token_matches():
    assert source_names_company("Shares of AYA rose after the print",
                                "AYA", "Aya Gold & Silver") is True


def test_lowercase_ticker_in_word_does_not_match():
    # case-sensitive ticker matching prevents "aya" inside prose from binding
    assert source_names_company("the papaya harvest", "AYA", "AYA") is False


# ------------------------------------------------------------------- hygiene
def test_empty_and_missing_inputs_are_safe():
    assert source_names_company("", "AYA", "Aya Gold & Silver") is False
    assert source_names_company(IPERIONX, "", "") is False


# ---------------------------------------------------- commodity classification
from app.services.classify import (  # noqa: E402
    infer_commodity, name_states_commodity,
)


def test_copper_company_is_not_gold():
    # the Copper Giant incident: default "Gold" stamped on a copper explorer
    assert infer_commodity("Copper Giant Resources",
                           "copper porphyry exploration") == "Copper"
    assert name_states_commodity("Copper Giant Resources") == "Copper"


def test_never_defaults_to_gold_without_evidence():
    assert infer_commodity("Generic Ventures Corp", "") is None
    assert name_states_commodity("Generic Ventures Corp") is None


def test_ambiguous_name_is_left_for_a_human():
    # "Gold & Silver" in the name must never be auto-corrected either way
    assert name_states_commodity("Aya Gold & Silver") is None


def test_description_classifies_when_name_is_silent():
    assert infer_commodity("Boss Energy", "uranium producer") == "Uranium"
    assert infer_commodity("Ramaco Resources",
                           "metallurgical coal producer") == "Coal"
