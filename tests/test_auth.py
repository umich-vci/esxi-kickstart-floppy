"""Tests that API key authentication is enforced on protected endpoints."""

import io

import pytest

# A minimal valid payload for POST /ks.
_KS_PAYLOAD = {
    "hostname": "esxi01.example.com",
    "rootpw": "$1$salt$hashedpassword",
    "disk": "sda",
    "ip": "192.168.1.10",
    "netmask": "255.255.255.0",
    "gateway": "192.168.1.1",
    "nameserver": ["8.8.8.8"],
    "allowed_ip": "192.168.1.5",
}


@pytest.mark.parametrize(
    "headers",
    [
        {},  # no token at all
        {"X-API-Key": "wrong-token"},  # invalid token
    ],
    ids=["no_token", "wrong_token"],
)
def test_post_ks_rejects_bad_auth(client, headers):
    """POST /ks returns 401 when the token is missing or invalid."""
    resp = client.post("/ks", json=_KS_PAYLOAD, headers=headers)
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-API-Key": "wrong-token"},
    ],
    ids=["no_token", "wrong_token"],
)
def test_post_esxi_rejects_bad_auth(client, headers):
    """POST /esxi returns 401 when the token is missing or invalid."""
    data = {"file": (io.BytesIO(b"data"), "test.iso")}
    resp = client.post(
        "/esxi",
        data=data,
        content_type="multipart/form-data",
        headers=headers,
    )
    assert resp.status_code == 401


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-API-Key": "wrong-token"},
    ],
    ids=["no_token", "wrong_token"],
)
def test_delete_esxi_rejects_bad_auth(client, headers):
    """DELETE /esxi/<file> returns 401 when the token is missing or invalid."""
    resp = client.delete("/esxi/test.iso", headers=headers)
    assert resp.status_code == 401
