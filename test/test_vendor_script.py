# Copyright 2026 Johan Ubbink
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""scripts/vendor.py: what it unpacks from a pinned wheel, without the network."""

import hashlib
import importlib.util
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

WHEEL_MEMBERS = [
    'pkg/__init__.py',
    'pkg/sub/mod.py',
    'pkg-1.0.dist-info/METADATA',
    'pkg-1.0.dist-info/RECORD',
    'pkg-1.0.dist-info/WHEEL',
    'pkg-1.0.dist-info/LICENSE.txt',
    'pkg-1.0.dist-info/licenses/COPYING',
    'pkg-1.0.data/scripts/tool',
]


def wheel_bytes():
    wheel = BytesIO()
    with zipfile.ZipFile(wheel, 'w') as archive:
        for member in WHEEL_MEMBERS:
            archive.writestr(member, member)
    return wheel.getvalue()


WHEEL = wheel_bytes()
WHEEL_SHA256 = hashlib.sha256(WHEEL).hexdigest()


@pytest.fixture
def vendor(tmp_path, monkeypatch):
    """The script as a module, its _vendor/ in tmp_path, and urlopen serving one in-memory wheel."""
    spec = importlib.util.spec_from_file_location(
        'vendor_script', Path(__file__).resolve().parents[1] / 'scripts' / 'vendor.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'VENDOR', tmp_path)
    monkeypatch.setattr(module, 'LOCK', tmp_path / 'vendor.lock')
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda url: BytesIO(WHEEL))
    return module


def files_under(root):
    return sorted(str(path.relative_to(root)) for path in root.rglob('*') if path.is_file())


def test_extract_keeps_the_package_metadata_and_licenses(vendor, tmp_path):
    (tmp_path / '__init__.py').write_text('')
    (tmp_path / 'stale').mkdir()
    (tmp_path / 'stale' / 'old.py').write_text('')
    (tmp_path / 'stale.py').write_text('')
    vendor.LOCK.write_text(f'# pinned\npkg==1.0  https://example.invalid/pkg.whl  sha256={WHEEL_SHA256}\n')
    vendor.extract()
    assert files_under(tmp_path) == ['__init__.py', 'pkg-1.0.dist-info/LICENSE.txt', 'pkg-1.0.dist-info/METADATA',
                                     'pkg-1.0.dist-info/licenses/COPYING', 'pkg/__init__.py', 'pkg/sub/mod.py',
                                     'vendor.lock']


def test_extract_refuses_a_wheel_with_the_wrong_hash(vendor, tmp_path):
    vendor.LOCK.write_text('pkg==1.0  https://example.invalid/pkg.whl  sha256=0000\n')
    with pytest.raises(SystemExit, match='pkg==1.0: sha256 mismatch for https://example.invalid/pkg.whl'):
        vendor.extract()
    assert files_under(tmp_path) == ['vendor.lock']
