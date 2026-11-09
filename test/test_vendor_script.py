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

"""scripts/vendor.py: how it reads the lock, finds a pinned wheel on PyPI and unpacks it, without the network."""

import hashlib
import importlib.util
import json
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
SDIST_SHA256 = 'a' * 64
NATIVE_SHA256 = 'b' * 64
WRONG_SHA256 = '0' * 64
WHEEL_URL = 'https://files.example.invalid/pkg-1.0-py3-none-any.whl'


def pypi_release(wheel_sha256=WHEEL_SHA256):
    """What https://pypi.org/pypi/pkg/1.0/json lists: an sdist, a native wheel and the pure wheel."""
    return {'urls': [
        {'packagetype': 'sdist', 'filename': 'pkg-1.0.tar.gz',
         'url': 'https://files.example.invalid/pkg-1.0.tar.gz', 'digests': {'sha256': SDIST_SHA256}},
        {'packagetype': 'bdist_wheel', 'filename': 'pkg-1.0-cp312-cp312-manylinux_2_17_x86_64.whl',
         'url': 'https://files.example.invalid/pkg-native.whl', 'digests': {'sha256': NATIVE_SHA256}},
        {'packagetype': 'bdist_wheel', 'filename': 'pkg-1.0-py3-none-any.whl',
         'url': WHEEL_URL, 'digests': {'sha256': wheel_sha256}},
    ]}


@pytest.fixture
def vendor(tmp_path, monkeypatch):
    """The script as a module, its _vendor/ in tmp_path, and urlopen serving PyPI's JSON and one wheel.

    ``vendor.fetched`` records every url opened; ``vendor.release`` is the JSON PyPI answers with."""
    spec = importlib.util.spec_from_file_location(
        'vendor_script', Path(__file__).resolve().parents[1] / 'scripts' / 'vendor.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'VENDOR', tmp_path)
    monkeypatch.setattr(module, 'LOCK', tmp_path / 'requirements.txt')
    monkeypatch.setattr(module, 'STAMP', tmp_path / 'requirements.sha256')
    module.fetched = []
    module.release = pypi_release()

    def urlopen(url):
        module.fetched.append(url)
        if url == 'https://pypi.org/pypi/pkg/1.0/json':
            return BytesIO(json.dumps(module.release).encode())
        if url == WHEEL_URL:
            return BytesIO(WHEEL)
        raise AssertionError(f'unexpected url {url}')

    monkeypatch.setattr(module.urllib.request, 'urlopen', urlopen)
    return module


def files_under(root):
    return sorted(str(path.relative_to(root)) for path in root.rglob('*') if path.is_file())


@pytest.mark.parametrize('lock, expected', [
    ('pkg==1.0 --hash=sha256:abc\n', [('pkg', '1.0', {'abc'})]),
    # The multi-line form Dependabot writes when a release has several files.
    ('# pinned\npkg==1.0 \\\n    --hash=sha256:abc \\\n    --hash=sha256:def\n\nother==2.0 --hash=sha256:123  # why\n',
     [('pkg', '1.0', {'abc', 'def'}), ('other', '2.0', {'123'})]),
])
def test_read_lock_takes_every_pin_with_its_hashes(vendor, lock, expected):
    vendor.LOCK.write_text(lock)
    assert vendor.read_lock() == expected


def test_read_lock_refuses_a_pin_without_a_hash(vendor):
    vendor.LOCK.write_text('pkg==1.0\n')
    with pytest.raises(SystemExit, match='pkg==1.0: no --hash=sha256'):
        vendor.read_lock()


def test_extract_keeps_the_package_metadata_and_licenses(vendor, tmp_path):
    (tmp_path / '__init__.py').write_text('')
    (tmp_path / 'stale').mkdir()
    (tmp_path / 'stale' / 'old.py').write_text('')
    (tmp_path / 'stale.py').write_text('')
    vendor.LOCK.write_text(f'# pinned\npkg==1.0 --hash=sha256:{SDIST_SHA256} --hash=sha256:{WHEEL_SHA256}\n')
    vendor.extract()
    assert vendor.fetched == ['https://pypi.org/pypi/pkg/1.0/json', WHEEL_URL]
    assert files_under(tmp_path) == ['__init__.py', 'pkg-1.0.dist-info/LICENSE.txt', 'pkg-1.0.dist-info/METADATA',
                                     'pkg-1.0.dist-info/licenses/COPYING', 'pkg/__init__.py', 'pkg/sub/mod.py',
                                     'requirements.sha256', 'requirements.txt']


def test_extract_stamps_the_copy_with_the_lock_it_came_from(vendor):
    vendor.LOCK.write_text(f'pkg==1.0 --hash=sha256:{WHEEL_SHA256}\n')
    assert not vendor.is_fresh()
    vendor.extract()
    assert vendor.is_fresh()
    vendor.LOCK.write_text(f'# edited\npkg==1.0 --hash=sha256:{WHEEL_SHA256}\n')
    assert not vendor.is_fresh()


def test_if_stale_unpacks_only_when_the_lock_changed(vendor, monkeypatch):
    monkeypatch.setattr(vendor.sys, 'argv', ['vendor.py', '--if-stale'])
    vendor.LOCK.write_text(f'pkg==1.0 --hash=sha256:{WHEEL_SHA256}\n')
    vendor.main()
    assert len(vendor.fetched) == 2
    vendor.main()
    assert len(vendor.fetched) == 2
    vendor.LOCK.write_text(f'# edited\npkg==1.0 --hash=sha256:{WHEEL_SHA256}\n')
    vendor.main()
    assert len(vendor.fetched) == 4


@pytest.mark.parametrize('pinned', [NATIVE_SHA256, WRONG_SHA256])
def test_extract_refuses_a_pin_that_matches_no_pure_wheel(vendor, tmp_path, pinned):
    vendor.LOCK.write_text(f'pkg==1.0 --hash=sha256:{pinned}\n')
    with pytest.raises(SystemExit, match=r'pkg==1.0: no pure-Python \(py3-none-any\) wheel on PyPI has a pinned hash'):
        vendor.extract()
    assert files_under(tmp_path) == ['requirements.txt']


def test_extract_refuses_a_download_with_the_wrong_hash(vendor, tmp_path):
    vendor.release = pypi_release(wheel_sha256=WRONG_SHA256)  # PyPI lists the pinned hash; the bytes differ.
    vendor.LOCK.write_text(f'pkg==1.0 --hash=sha256:{WRONG_SHA256}\n')
    with pytest.raises(SystemExit, match=f'pkg==1.0: sha256 mismatch for {WHEEL_URL}'):
        vendor.extract()
    assert files_under(tmp_path) == ['requirements.txt']


def test_relock_pins_the_pure_wheel_of_each_version(vendor):
    vendor.LOCK.write_text('# pinned\npkg==1.0 \\\n    --hash=sha256:stale \\\n    --hash=sha256:older\n')
    vendor.relock()
    assert vendor.LOCK.read_text() == f'# pinned\npkg==1.0 --hash=sha256:{WHEEL_SHA256}\n'
