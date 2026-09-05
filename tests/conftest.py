import os
import sys
import tempfile
from pathlib import Path

# isolate config and data before the package is imported anywhere
_TMP = tempfile.mkdtemp(prefix="genesis-desktop-test-")
os.environ["GENESIS_DESKTOP_CONFIG_DIR"] = os.path.join(_TMP, "cfg")
os.environ["GENESIS_DESKTOP_DATA_DIR"] = os.path.join(_TMP, "data")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import fake_backend  # noqa: E402


@pytest.fixture(scope="session")
def backend():
    srv, url = fake_backend.start(token="user-token", admin="admin-token")
    yield url
    srv.shutdown()


@pytest.fixture
def clean_config():
    from genesis_desktop import config
    config.load(force=True)
    for k in list(config._file_layer):
        config._file_layer.pop(k)
    config.save()
    yield config
