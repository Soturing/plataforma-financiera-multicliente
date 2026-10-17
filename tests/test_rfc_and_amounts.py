from decimal import Decimal

from app.amount_words import amounts_in_words
from app.rfc import _check_digit, correct_rfc, find_rfcs, is_valid_rfc, similar


def make_rfc(body: str) -> str:
    """RFC sintético con dígito verificador válido."""
    return body + _check_digit(body)


def test_generated_rfc_validates_and_wrong_check_digit_does_not():
    rfc = make_rfc("ABC900101XY")
    assert is_valid_rfc(rfc)
    wrong = rfc[:-1] + ("1" if rfc[-1] != "1" else "2")
    assert not is_valid_rfc(wrong)


def test_ocr_confusions_in_numeric_part_are_corrected():
    rfc = make_rfc("ABC900101XY")
    garbled = rfc.replace("0", "O", 1)  # 0 leído como O
    corrected, valid, edits = correct_rfc(garbled)
    assert (corrected, valid, edits) == (rfc, True, 1)


def test_known_rfc_wins_over_a_close_misreading():
    known = make_rfc("QWE850505AB")
    misread = known[:3] + "8" + known[4:].replace("5", "6", 1)  # dos caracteres distintos
    corrected, _, _ = correct_rfc(misread, (known,))
    assert corrected == known


def test_find_rfcs_handles_hyphens_and_ignores_pipe_delimited_pac_values():
    rfc = make_rfc("ZZZ010203AB")
    text = f"R.F.C. {rfc[:3]}-{rfc[3:9]}-{rfc[9:]}\nCadena: ||1.1|abc|2026-01-01|LSO1306189R5|sello||\n|{rfc}|"
    found = {item["rfc"]: item for item in find_rfcs(text)}
    assert rfc in found
    assert found["LSO1306189R5"]["entre_barras"] is True


def test_similar_rfc_tolerates_two_character_differences():
    assert similar("ABC900101XY1", "ABC9OO101XY1", 2)
    assert not similar("ABC900101XY1", "XYZ900101XY1", 2)


def test_amount_in_words_parses_common_forms():
    assert amounts_in_words("CUATRO MIL OCHOCIENTOS OCHENTA Y CINCO PESOS 40/100 M.N.") == [Decimal("4885.40")]
    assert amounts_in_words("(***MIL QUINIENTOS CUARENTA MXN 00/100 ***)") == [Decimal("1540")]
    assert amounts_in_words("Siete mil ciento noventa y dos pesos con 00/100 MN") == [Decimal("7192")]
    assert amounts_in_words("TREINTA Y OCHO MIL SETECIENTOS CATORCE PESOS CON 81/100 M.N.") == [Decimal("38714.81")]


def test_amount_in_words_tolerates_ocr_typos():
    assert amounts_in_words("UN MIL SETECIENTOS SESENTAY TRES PESOS 32/100 M.N.") == [Decimal("1763.32")]


def test_numbers_without_currency_are_not_amounts():
    assert amounts_in_words("TRES PIEZAS DE CINCO KILOS") == []
