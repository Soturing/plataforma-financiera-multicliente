from pathlib import Path

from app.storage import nombre_seguro, ruta_almacenada, ruta_para_guardar


def test_se_guarda_la_ruta_relativa_al_directorio_del_cliente(tmp_path):
    archivo = tmp_path / "lotes" / "abc" / "pagina-1.pdf"
    archivo.parent.mkdir(parents=True)
    archivo.write_bytes(b"%PDF-1.4")
    assert ruta_para_guardar(archivo, tmp_path) == "lotes/abc/pagina-1.pdf"
    assert ruta_para_guardar(str(archivo), tmp_path) == "lotes/abc/pagina-1.pdf"


def test_un_archivo_fuera_del_directorio_conserva_su_ruta(tmp_path):
    fuera = tmp_path.parent / "otro" / "x.pdf"
    assert ruta_para_guardar(fuera, tmp_path) == str(fuera)


def test_la_ruta_relativa_se_resuelve_dentro_del_directorio(tmp_path):
    assert ruta_almacenada("lotes/abc/pagina-1.pdf", tmp_path) == (tmp_path / "lotes" / "abc" / "pagina-1.pdf").resolve()


def test_una_ruta_absoluta_heredada_sigue_funcionando(tmp_path):
    heredada = (tmp_path / "viejo.pdf").resolve()
    assert ruta_almacenada(str(heredada), tmp_path) == heredada


def test_una_ruta_relativa_con_puntos_queda_fuera_y_el_llamador_la_rechaza(tmp_path):
    interior = tmp_path / "datos"
    interior.mkdir()
    escapada = ruta_almacenada("../secreto.txt", interior)
    assert not escapada.is_relative_to(interior.resolve())


def test_ida_y_vuelta_entre_guardar_y_resolver(tmp_path):
    archivo = tmp_path / "uno.pdf"
    assert ruta_almacenada(ruta_para_guardar(archivo, tmp_path), tmp_path) == archivo.resolve()


def test_el_nombre_no_conserva_directorios_ni_comillas():
    assert nombre_seguro("../../etc/passwd") == "passwd"
    assert nombre_seguro("C:\\Users\\yo\\factura.pdf") == "factura.pdf"
    assert nombre_seguro('fac"tura\r\nSet-Cookie: x=1.pdf') == "fac_tura_Set-Cookie_ x=1.pdf"
    assert nombre_seguro("a;b<c>.pdf") == "a_b_c_.pdf"


def test_un_nombre_vacio_o_solo_puntos_usa_el_valor_por_defecto():
    assert nombre_seguro(None) == "documento"
    assert nombre_seguro("  ..  ", "evidencia") == "evidencia"
    assert nombre_seguro("///") == "documento"


def test_un_nombre_largo_se_recorta_y_conserva_la_extension():
    largo = nombre_seguro("a" * 300 + ".pdf")
    assert len(largo) <= 120 and largo.endswith(".pdf")


def test_los_nombres_normales_no_cambian():
    assert nombre_seguro("Factura Proveedor Ñandú 2026.pdf") == "Factura Proveedor Ñandú 2026.pdf"
