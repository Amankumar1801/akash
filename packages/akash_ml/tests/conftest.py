import importlib.util
import warnings

import pytest
from akash_ml.transit.splits import SplitManifest
from akash_ml.transit.synthetic_set import make_synthetic_transit_dataset

warnings.filterwarnings("ignore")

# PyTorch is an optional extra. Without it the autoencoder tests cannot even be imported, so they are
# left out of collection (install with: uv sync --all-packages --extra torch).
collect_ignore = [] if importlib.util.find_spec("torch") else ["test_anomaly.py"]


@pytest.fixture(scope="session")
def ds():
    return make_synthetic_transit_dataset(320, seed=1)


@pytest.fixture(scope="session")
def manifest(ds):
    return SplitManifest.build(ds.star_ids, salt="akash-test-v1")


@pytest.fixture(scope="session")
def parts(ds, manifest):
    idx = manifest.indices(ds.star_ids)
    return {k: ds.subset(v) for k, v in idx.items()}
