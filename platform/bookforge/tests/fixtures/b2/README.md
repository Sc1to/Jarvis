# b2: the second real test book

Drop the real files of book b2 here (from `<series>/books/b2/`): `synopsis.md`, `ledger.yaml`, `acts.yaml`, `chapters.yaml`, and the cast (`bible/constants.yaml`
or the series `bible/constants.yaml`). `tests/test_b2_known_bad.py` runs every check on them as soon as they exist; until then it uses the synthetic
stand-in `tests/fixtures/known_bad/b2_standin.py`, which reproduces each problem b2 showed (test data, not b2's text).
