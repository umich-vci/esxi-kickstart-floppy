# Running Tests

## Prerequisites

Install the application dependencies and the test-only dependencies:

```bash
pip install -r requirements.txt -r requirements-test.txt
```

The test suite also uses `blank.img`, which is committed to the repository, so
no extra setup is needed for that file.

## Running the Tests

**Run the full test suite:**

```bash
pytest
```

**Run with coverage:**

```bash
pytest --cov=app --cov-report=term-missing
```

**Run only fast unit tests (skip integration tests):**

```bash
pytest -m "not integration"
```

**Run only integration tests:**

```bash
pytest -m integration
```

## Test Markers

| Marker | Meaning |
|---|---|
| `integration` | Tests that perform real filesystem I/O — writing a kickstart floppy image or parsing/modifying an ISO. These require `blank.img` to be present in the repository root (it is committed, so they run on all normal checkouts). |

## Test Layout

```
tests/
  conftest.py         # Shared fixtures (app, client, auth_headers, blank_img, sample_iso)
  test_auth.py        # API key authentication enforcement
  test_kickstart.py   # POST /ks input validation and floppy generation; GET /ks/<file>
  test_esxi.py        # GET /esxi listing; POST /esxi upload and ISO modification; DELETE /esxi/<file>
```

## GitHub Actions

Tests run automatically on every pull request and on every push to `main`.
The workflow is defined in [`.github/workflows/tests.yml`](.github/workflows/tests.yml)
and tests against Python 3.12, 3.13, 3.14, and 3.15.

## Notes

- A `ks.db` file may be created in the project root when the test suite is run.
  It is an empty database produced as a side-effect of the application module
  being imported and is not used by the tests (which write to a temporary
  database). It is safe to delete and is listed in `.gitignore`.
- The `sample_iso` fixture builds a minimal ISO image programmatically using
  `pycdlib`, so no real ESXi ISO is required for any test.
