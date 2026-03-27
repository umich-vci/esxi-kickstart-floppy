"""Tests for the ESXi ISO endpoints: GET /esxi, POST /esxi, DELETE /esxi/<iso_file>."""

import io
import os

import pycdlib
import pytest


# ── GET /esxi ─────────────────────────────────────────────────────────────────


def test_get_esxi_isos_empty(client):
    """GET /esxi returns an empty list when no ISOs are present."""
    resp = client.get("/esxi")
    assert resp.status_code == 200
    assert resp.get_json()["iso_urls"] == []


def test_get_esxi_isos_lists_iso_files(client, app):
    """ISO files in the esxi directory appear in the returned URL list."""
    iso_path = os.path.join(app.config["ESXI_ISOS_PATH"], "myesxi.iso")
    with open(iso_path, "wb") as f:
        f.write(b"dummy")

    resp = client.get("/esxi")
    assert resp.status_code == 200
    urls = resp.get_json()["iso_urls"]
    assert any("myesxi.iso" in url for url in urls)
    # URLs must use the configured BASE_URL, not a raw Host header.
    assert all(url.startswith("http://localhost/") for url in urls)


def test_get_esxi_isos_ignores_non_iso_files(client, app):
    """Non-.iso files in the esxi directory are not included."""
    txt_path = os.path.join(app.config["ESXI_ISOS_PATH"], "readme.txt")
    with open(txt_path, "w", encoding='utf-8') as f:
        f.write("not an iso")

    resp = client.get("/esxi")
    assert resp.status_code == 200
    urls = resp.get_json()["iso_urls"]
    assert not any("readme.txt" in url for url in urls)


# ── DELETE /esxi/<iso_file> ───────────────────────────────────────────────────


def test_delete_esxi_iso_not_found(client, auth_headers):
    """DELETE /esxi/<file> returns 404 when the file does not exist."""
    resp = client.delete("/esxi/nonexistent.iso", headers=auth_headers)
    assert resp.status_code == 404


def test_delete_esxi_iso_success(client, app, auth_headers):
    """DELETE /esxi/<file> removes the file and returns 204."""
    iso_path = os.path.join(app.config["ESXI_ISOS_PATH"], "delete_me.iso")
    with open(iso_path, "wb") as f:
        f.write(b"dummy")

    resp = client.delete("/esxi/delete_me.iso", headers=auth_headers)
    assert resp.status_code == 204
    assert not os.path.exists(iso_path)


# ── POST /esxi ────────────────────────────────────────────────────────────────


def test_post_esxi_rejects_non_iso_data(client, auth_headers):
    """Uploading arbitrary bytes that are not a valid ISO returns 400."""
    resp = client.post(
        "/esxi",
        data={"file": (io.BytesIO(b"this is not an iso file"), "fake.iso")},
        content_type="multipart/form-data",
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_post_esxi_rejects_empty_filename(client, auth_headers):
    """A filename that reduces to empty after secure_filename() returns 400."""
    resp = client.post(
        "/esxi",
        data={"file": (io.BytesIO(b"data"), ".")},
        content_type="multipart/form-data",
        headers=auth_headers,
    )
    assert resp.status_code == 400


@pytest.mark.integration
def test_post_esxi_valid_iso_returns_201(client, auth_headers, sample_iso):
    """A valid ISO is accepted and returns 201."""
    with open(sample_iso, "rb") as f:
        iso_data = f.read()

    resp = client.post(
        "/esxi",
        data={"file": (io.BytesIO(iso_data), "esxi.iso")},
        content_type="multipart/form-data",
        headers=auth_headers,
    )
    assert resp.status_code == 201


@pytest.mark.integration
def test_post_esxi_modifies_boot_cfg(client, app, auth_headers, sample_iso):
    """After upload, both BOOT.CFG files must contain ``kernelopt=runweasel ks=usb``."""
    with open(sample_iso, "rb") as f:
        iso_data = f.read()

    client.post(
        "/esxi",
        data={"file": (io.BytesIO(iso_data), "esxi.iso")},
        content_type="multipart/form-data",
        headers=auth_headers,
    )

    saved_path = os.path.join(app.config["ESXI_ISOS_PATH"], "esxi.iso")
    assert os.path.exists(saved_path)

    iso = pycdlib.PyCdlib()
    iso.open(saved_path)

    boot_cfg = io.BytesIO()
    efi_boot_cfg = io.BytesIO()
    iso.get_file_from_iso_fp(boot_cfg, iso_path="/BOOT.CFG;1")
    iso.get_file_from_iso_fp(efi_boot_cfg, iso_path="/EFI/BOOT/BOOT.CFG;1")
    iso.close()

    assert b"kernelopt=runweasel ks=usb" in boot_cfg.getvalue()
    assert b"kernelopt=runweasel ks=usb" in efi_boot_cfg.getvalue()
    # Original cdromBoot option must be gone.
    assert b"cdromBoot" not in boot_cfg.getvalue()
