"""Migracion transparente de bcrypt a Argon2id (seccion 3.4 de la hoja de ruta).
No requiere base de datos."""

import bcrypt

from database import DUMMY_HASH, hash_pw, pw_necesita_rehash, verify_pw


def test_hash_nuevo_es_argon2id():
    h = hash_pw("Clave-Segura12!")
    assert h.startswith("$argon2id$")
    assert verify_pw("Clave-Segura12!", h)
    assert not verify_pw("otra-clave", h)
    assert not pw_necesita_rehash(h)


def test_bcrypt_legado_valida_y_pide_rehash():
    h = bcrypt.hashpw(b"Clave-Segura12!", bcrypt.gensalt()).decode()
    assert verify_pw("Clave-Segura12!", h)
    assert not verify_pw("otra-clave", h)
    assert pw_necesita_rehash(h)


def test_formatos_heredados_no_validan():
    # Texto plano y SHA-256 sin sal: nunca validan (requieren reset por un admin).
    assert not verify_pw("Clave-Segura12!", "Clave-Segura12!")
    assert not verify_pw("abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
    assert not verify_pw("x", "")


def test_bcrypt_malformado_no_valida_ni_rompe():
    assert not verify_pw("x", "$2b$12$roto")


def test_dummy_hash_es_argon2id():
    # El login verifica contra este hash cuando el DNI no existe: tiene que costar lo mismo
    # que una clave real.
    assert DUMMY_HASH.startswith("$argon2id$")
    assert not verify_pw("cualquier-cosa", DUMMY_HASH)
