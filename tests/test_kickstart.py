"""Tests for the kickstart floppy endpoints: POST /ks and GET /ks/<image_file>."""

import datetime
import os
import shutil

import fs as pyfs
import pytest

from app import KickstartFloppyModel, db

# ── Shared test data ──────────────────────────────────────────────────────────

_VALID_PAYLOAD = {
    "hostname": "esxi01.example.com",
    "rootpw": "$1$salt$hashedpassword",
    "disk": "sda",
    "ip": "192.168.1.10",
    "netmask": "255.255.255.0",
    "gateway": "192.168.1.1",
    "nameserver": ["8.8.8.8"],
    "allowed_ip": "192.168.1.5",
}


# ── Input validation ──────────────────────────────────────────────────────────


def test_post_ks_missing_hostname(client, auth_headers):
    """POST /ks returns 422 when hostname is absent."""
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "hostname"}
    assert client.post("/ks", json=payload, headers=auth_headers).status_code == 422


def test_post_ks_newline_in_hostname(client, auth_headers):
    """POST /ks returns 422 when hostname contains a newline."""
    payload = {**_VALID_PAYLOAD, "hostname": "host\ninjected=value"}
    assert client.post("/ks", json=payload, headers=auth_headers).status_code == 422


def test_post_ks_control_char_in_rootpw(client, auth_headers):
    """POST /ks returns 422 when rootpw contains a null byte."""
    payload = {**_VALID_PAYLOAD, "rootpw": "pass\x00word"}
    assert client.post("/ks", json=payload, headers=auth_headers).status_code == 422


def test_post_ks_both_disk_and_firstdisk(client, auth_headers):
    """POST /ks returns 422 when both disk and firstdisk are supplied."""
    payload = {**_VALID_PAYLOAD, "firstdisk": "local"}
    assert client.post("/ks", json=payload, headers=auth_headers).status_code == 422


def test_post_ks_neither_disk_nor_firstdisk(client, auth_headers):
    """POST /ks returns 422 when neither disk nor firstdisk is supplied."""
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "disk"}
    assert client.post("/ks", json=payload, headers=auth_headers).status_code == 422


def test_post_ks_vlanid_too_low(client, auth_headers):
    """POST /ks returns 422 when vlanid is below the minimum (1)."""
    payload = {**_VALID_PAYLOAD, "vlanid": 0}
    assert client.post("/ks", json=payload, headers=auth_headers).status_code == 422


def test_post_ks_vlanid_too_high(client, auth_headers):
    """POST /ks returns 422 when vlanid is above the maximum (4094)."""
    payload = {**_VALID_PAYLOAD, "vlanid": 4095}
    assert client.post("/ks", json=payload, headers=auth_headers).status_code == 422


def test_post_ks_invalid_ip(client, auth_headers):
    """POST /ks returns 422 when ip is not a valid IPv4 address."""
    payload = {**_VALID_PAYLOAD, "ip": "not-an-ip"}
    assert client.post("/ks", json=payload, headers=auth_headers).status_code == 422


def test_post_ks_invalid_nameserver(client, auth_headers):
    """POST /ks returns 422 when nameserver list contains an invalid address."""
    payload = {**_VALID_PAYLOAD, "nameserver": ["not-an-ip"]}
    assert client.post("/ks", json=payload, headers=auth_headers).status_code == 422


# ── Successful creation ───────────────────────────────────────────────────────


@pytest.mark.integration
def test_post_ks_success(client, auth_headers, blank_img, app):  # pylint: disable=unused-argument
    """POST /ks returns 201 and writes a valid FAT floppy with ks.cfg inside."""
    resp = client.post("/ks", json=_VALID_PAYLOAD, headers=auth_headers)
    assert resp.status_code == 201

    data = resp.get_json()
    assert data["image_file"].endswith(".img")
    assert "image_url" in data
    assert data["allowed_ip"] == _VALID_PAYLOAD["allowed_ip"]
    assert "expires_at" in data

    # The floppy image must exist on disk.
    floppy_path = os.path.join(app.config["KICKSTART_IMAGE_PATH"], data["image_file"])
    assert os.path.exists(floppy_path)

    # ks.cfg inside the floppy must contain the expected network parameters.
    floppy_fs = pyfs.open_fs(f"fat://{floppy_path}?offset=512")
    assert floppy_fs.exists("ks.cfg")
    ks_contents = floppy_fs.readtext("ks.cfg")
    floppy_fs.close()

    assert _VALID_PAYLOAD["hostname"] in ks_contents
    assert _VALID_PAYLOAD["ip"] in ks_contents
    assert _VALID_PAYLOAD["gateway"] in ks_contents
    assert _VALID_PAYLOAD["nameserver"][0] in ks_contents


@pytest.mark.integration
def test_post_ks_with_firstdisk(client, auth_headers, blank_img, app):  # pylint: disable=unused-argument
    """firstdisk is accepted as an alternative to disk."""
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "disk"}
    payload["firstdisk"] = "local"

    resp = client.post("/ks", json=payload, headers=auth_headers)
    assert resp.status_code == 201

    data = resp.get_json()
    floppy_path = os.path.join(app.config["KICKSTART_IMAGE_PATH"], data["image_file"])
    floppy_fs = pyfs.open_fs(f"fat://{floppy_path}?offset=512")
    ks_contents = floppy_fs.readtext("ks.cfg")
    floppy_fs.close()
    assert "--firstdisk=local" in ks_contents


@pytest.mark.integration
def test_post_ks_with_vlanid(client, auth_headers, blank_img, app):  # pylint: disable=unused-argument
    """An optional vlanid is included in the network line."""
    payload = {**_VALID_PAYLOAD, "vlanid": 100}
    resp = client.post("/ks", json=payload, headers=auth_headers)
    assert resp.status_code == 201

    data = resp.get_json()
    floppy_path = os.path.join(app.config["KICKSTART_IMAGE_PATH"], data["image_file"])
    floppy_fs = pyfs.open_fs(f"fat://{floppy_path}?offset=512")
    ks_contents = floppy_fs.readtext("ks.cfg")
    floppy_fs.close()
    assert "--vlanid=100" in ks_contents


@pytest.mark.integration
def test_post_ks_with_clearpart_disk(client, auth_headers, blank_img, app):  # pylint: disable=unused-argument
    """clearpart=True with disk uses --drives= and appears before install."""
    payload = {**_VALID_PAYLOAD, "clearpart": True}
    resp = client.post("/ks", json=payload, headers=auth_headers)
    assert resp.status_code == 201

    data = resp.get_json()
    floppy_path = os.path.join(app.config["KICKSTART_IMAGE_PATH"], data["image_file"])
    floppy_fs = pyfs.open_fs(f"fat://{floppy_path}?offset=512")
    ks_contents = floppy_fs.readtext("ks.cfg")
    floppy_fs.close()

    assert "clearpart --drives=sda" in ks_contents
    assert "--overwritevmfs" not in ks_contents.split("install")[0]
    assert ks_contents.index("clearpart") < ks_contents.index("install")


@pytest.mark.integration
def test_post_ks_with_clearpart_firstdisk(client, auth_headers, blank_img, app):  # pylint: disable=unused-argument
    """clearpart=True with firstdisk uses --firstdisk=."""
    payload = {k: v for k, v in _VALID_PAYLOAD.items() if k != "disk"}
    payload["firstdisk"] = "local"
    payload["clearpart"] = True

    resp = client.post("/ks", json=payload, headers=auth_headers)
    assert resp.status_code == 201

    data = resp.get_json()
    floppy_path = os.path.join(app.config["KICKSTART_IMAGE_PATH"], data["image_file"])
    floppy_fs = pyfs.open_fs(f"fat://{floppy_path}?offset=512")
    ks_contents = floppy_fs.readtext("ks.cfg")
    floppy_fs.close()

    assert "clearpart --firstdisk=local" in ks_contents
    assert ks_contents.index("clearpart") < ks_contents.index("install")


@pytest.mark.integration
def test_post_ks_with_clearpart_overwritevmfs(client, auth_headers, blank_img, app):  # pylint: disable=unused-argument
    """clearpart_overwritevmfs=True appends --overwritevmfs to the clearpart line."""
    payload = {**_VALID_PAYLOAD, "clearpart": True, "clearpart_overwritevmfs": True}
    resp = client.post("/ks", json=payload, headers=auth_headers)
    assert resp.status_code == 201

    data = resp.get_json()
    floppy_path = os.path.join(app.config["KICKSTART_IMAGE_PATH"], data["image_file"])
    floppy_fs = pyfs.open_fs(f"fat://{floppy_path}?offset=512")
    ks_contents = floppy_fs.readtext("ks.cfg")
    floppy_fs.close()

    assert "clearpart --drives=sda --overwritevmfs" in ks_contents


def test_post_ks_clearpart_overwritevmfs_without_clearpart(client, auth_headers):
    """POST /ks returns 422 when clearpart_overwritevmfs=True but clearpart=False."""
    payload = {**_VALID_PAYLOAD, "clearpart_overwritevmfs": True}
    assert client.post("/ks", json=payload, headers=auth_headers).status_code == 422


# ── GET /ks/<image_file> ──────────────────────────────────────────────────────


def test_get_kickstart_floppy_not_found(client):
    """GET /ks/<file> returns 404 when the image does not exist."""
    assert client.get("/ks/doesnotexist.img").status_code == 404


def test_get_kickstart_floppy_wrong_ip(client, app):
    """A request from an IP that does not match allowed_ip is rejected."""
    with app.app_context():
        record = KickstartFloppyModel(
            "wrong.img",
            "http://localhost/ks/wrong.img",
            "10.0.0.99",  # ≠ test-client default 127.0.0.1
            datetime.datetime.now() + datetime.timedelta(hours=1),
        )
        db.session.add(record)
        db.session.commit()

    resp = client.get("/ks/wrong.img")
    assert resp.status_code == 401


@pytest.mark.integration
def test_get_kickstart_floppy_correct_ip(client, app, blank_img):
    """A request from the allowed IP receives the floppy image."""
    # Seed a real floppy file so send_file has something to serve.
    floppy_name = "serve_me.img"
    floppy_path = os.path.join(app.config["KICKSTART_IMAGE_PATH"], floppy_name)
    shutil.copyfile(blank_img, floppy_path)

    with app.app_context():
        record = KickstartFloppyModel(
            floppy_name,
            f"http://localhost/ks/{floppy_name}",
            "127.0.0.1",  # Flask test client default REMOTE_ADDR
            datetime.datetime.now() + datetime.timedelta(hours=1),
        )
        db.session.add(record)
        db.session.commit()

    resp = client.get(f"/ks/{floppy_name}")
    assert resp.status_code == 200
    assert resp.content_type == "application/octet-stream"
