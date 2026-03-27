"""
Pytest fixtures for the esxi-kickstart-floppy test suite.

The Flask app module is imported once per session.  Key challenges handled here:

1. APScheduler – ``scheduler.start()`` is called at module-import time.
   We patch ``APScheduler.start`` *before* the import so no background thread
   is ever started.

2. Flask-SQLAlchemy engine caching – ``db.init_app(app)`` bakes the engine for
   ``SQLALCHEMY_DATABASE_URI`` at call-time and caches it.  After we swap the
   URI to a per-session temp file we dispose the old engines, remove the
   extension marker, and call ``init_app`` again so every test uses an isolated
   database.

3. Filesystem isolation – ``KICKSTART_IMAGE_PATH`` and ``ESXI_ISOS_PATH`` are
   redirected to ``tmp_path_factory`` directories so generated floppies and
   uploaded ISOs never touch the real ``instance/`` tree.
"""

import os
from io import BytesIO
from unittest.mock import patch

import pycdlib
import pytest

# ── 1. Patch the scheduler before importing app ───────────────────────────────
with patch("flask_apscheduler.APScheduler.start"):
    import app as app_module
    from app import db

TEST_TOKEN = "test-token"


# ── 2. Session-scoped application fixture ────────────────────────────────────
@pytest.fixture(scope="session")
def app(tmp_path_factory):
    """Configure the Flask app for testing and yield it for the whole session."""
    db_path = str(tmp_path_factory.mktemp("db") / "test.db")
    ks_path = str(tmp_path_factory.mktemp("ks"))
    esxi_path = str(tmp_path_factory.mktemp("esxi"))

    inst = app_module.app

    # Update config BEFORE re-initialising the DB extension.
    inst.config.update(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            "KICKSTART_IMAGE_PATH": ks_path,
            "ESXI_ISOS_PATH": esxi_path,
            "BASE_URL": "http://localhost",
        }
    )

    # ``tokens`` in app.py is a module-level variable bound to the dict object
    # that existed at import time.  Assigning to app.config['TOKENS'] creates a
    # new dict and does not update the bound reference, so we must mutate the
    # existing dict in place.
    app_module.tokens.clear()
    app_module.tokens[TEST_TOKEN] = "test-user"

    # Dispose and remove the engine that was created at import time (pointing at
    # the production ``ks.db``), then re-register so the extension builds a new
    # engine for our temp database.
    # pylint: disable=protected-access
    if inst in db._app_engines:
        for engine in db._app_engines[inst].values():
            engine.dispose()
        db._app_engines[inst].clear()
    # pylint: enable=protected-access

    del inst.extensions["sqlalchemy"]
    db.init_app(inst)

    with inst.app_context():
        db.create_all()

    yield inst

    with inst.app_context():
        db.drop_all()


# ── 3. Per-test DB cleanup (autouse) ─────────────────────────────────────────
@pytest.fixture(autouse=True)
def _clean_db(app):  # pylint: disable=redefined-outer-name
    """Truncate all rows after every test to keep tests independent."""
    yield
    with app.app_context():
        db.session.remove()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()


# ── 4. Per-test filesystem cleanup (autouse) ─────────────────────────────────
@pytest.fixture(autouse=True)
def _clean_files(app):  # pylint: disable=redefined-outer-name
    """Remove any files written to the temp ks/esxi directories after each test."""
    yield
    for directory in [app.config["KICKSTART_IMAGE_PATH"], app.config["ESXI_ISOS_PATH"]]:
        for filename in os.listdir(directory):
            filepath = os.path.join(directory, filename)
            if os.path.isfile(filepath):
                os.remove(filepath)


# ── 5. Common fixtures ────────────────────────────────────────────────────────
@pytest.fixture
def client(app):  # pylint: disable=redefined-outer-name
    """Return a Flask test client."""
    return app.test_client()


@pytest.fixture
def auth_headers():
    """Return valid API key headers."""
    return {"X-API-Key": TEST_TOKEN}


@pytest.fixture
def blank_img(app):  # pylint: disable=redefined-outer-name
    """
    Return the path to ``blank.img`` in the application root.

    Since the image is committed to the repository this fixture will succeed on
    any normal checkout.  It calls ``pytest.skip`` only as a safety net in case
    the file is somehow absent (e.g. a shallow/partial clone).
    """
    path = os.path.join(app.root_path, "blank.img")
    if not os.path.exists(path):
        pytest.skip("blank.img not found in app root – see create-blank-floppy.md")
    return path


@pytest.fixture
def sample_iso(tmp_path):
    """
    Build a minimal ISO 9660 image using pycdlib and yield its path.

    The image contains ``/BOOT.CFG`` and ``/EFI/BOOT/BOOT.CFG``, each holding
    a single ``kernelopt=runweasel cdromBoot\\n`` line – the default content
    present in unmodified ESXi boot configuration files.

    In tests, this line is replaced with a shorter ``kernelopt=runweasel ks=usb``,
    which satisfies pycdlib's ``modify_file_in_place`` requirement that
    replacement content must not exceed the original file size.
    """
    boot_cfg_content = b"kernelopt=runweasel cdromBoot\n"

    iso = pycdlib.PyCdlib()
    iso.new()
    iso.add_directory("/EFI")
    iso.add_directory("/EFI/BOOT")
    iso.add_fp(BytesIO(boot_cfg_content), len(boot_cfg_content), iso_path="/BOOT.CFG;1")
    iso.add_fp(
        BytesIO(boot_cfg_content),
        len(boot_cfg_content),
        iso_path="/EFI/BOOT/BOOT.CFG;1",
    )

    iso_path = tmp_path / "test.iso"
    iso.write(str(iso_path))
    iso.close()

    yield str(iso_path)
