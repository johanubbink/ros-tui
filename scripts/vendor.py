#!/usr/bin/env python3
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

"""Fill ros_tui/_vendor/ (textual and its dependencies) from ros_tui/_vendor/requirements.txt.

The lock is a pip requirements file with hashes, one ``name==version --hash=sha256:<hash>`` per
package (Dependabot keeps it up to date). For each pin, PyPI's JSON API gives the release's files;
the pure-Python (py3-none-any) wheel whose sha256 is pinned is downloaded, its hash checked, and
unpacked into ros_tui/_vendor/. Each ``*.dist-info`` keeps only its METADATA and license files.
Last, requirements.sha256 records the hash of the lock the copy came from, so a stale copy is
cheap to spot (setup.py refuses to build one). Only ``__init__.py`` and the lock are in git.

    scripts/vendor.py             # unpack exactly what the lock pins
    scripts/vendor.py --if-stale  # the same, unless the copy already matches the lock
    scripts/vendor.py --relock    # after editing a version by hand: re-pin each version's wheel hash

Only the standard library is used (no pip, which the ROS base images may lack). Only pure-Python
wheels are accepted, so one copy works on every Python a ROS distro ships.
"""

import argparse
import hashlib
import json
import re
import shutil
import sys
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

VENDOR = Path(__file__).resolve().parent.parent / 'ros_tui' / '_vendor'
LOCK = VENDOR / 'requirements.txt'
STAMP = VENDOR / 'requirements.sha256'
KEEP = {'__init__.py', 'requirements.txt'}  # The files in _vendor/ that are ours, not unpacked wheels.
LICENSE_FILE = re.compile(r'(LICEN[CS]E|COPYING|NOTICE|AUTHORS)', re.IGNORECASE)
HASH = re.compile(r'--hash=sha256:(\w+)')


def read_lock() -> list[tuple[str, str, set[str]]]:
    """(name, version, pinned sha256s) for every requirement in the lock."""
    text = LOCK.read_text(encoding='utf-8').replace('\\\n', ' ')
    entries = []
    for line in text.splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        pin = line.split()[0]
        hashes = set(HASH.findall(line))
        if not hashes:
            sys.exit(f'{pin}: no --hash=sha256 in {LOCK}')
        name, version = pin.split('==')
        entries.append((name, version, hashes))
    return entries


def pure_wheels(name: str, version: str) -> list[tuple[str, str]]:
    """(url, sha256) of every py3-none-any wheel PyPI has for ``name==version``."""
    with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json') as response:
        files = json.load(response)['urls']
    return [(file['url'], file['digests']['sha256']) for file in files
            if file['packagetype'] == 'bdist_wheel' and file['filename'].endswith('-none-any.whl')]


def relock() -> None:
    """Pin each locked version to the hash of its pure-Python wheel on PyPI; keeps the comments."""
    lines = [line for line in LOCK.read_text(encoding='utf-8').splitlines() if line.startswith('#')]
    for name, version, _ in read_lock():
        wheels = pure_wheels(name, version)
        if not wheels:
            sys.exit(f'{name}=={version}: no pure-Python (py3-none-any) wheel on PyPI')
        lines.append(f'{name}=={version} --hash=sha256:{wheels[0][1]}')
    LOCK.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def extract() -> None:
    """Empty _vendor/ (but for our own files), unpack every pinned wheel into it, then stamp it."""
    for path in VENDOR.iterdir():
        if path.name not in KEEP:
            shutil.rmtree(path) if path.is_dir() else path.unlink()
    for name, version, hashes in read_lock():
        with zipfile.ZipFile(BytesIO(download(name, version, hashes))) as wheel:
            for member in filter(vendored, wheel.namelist()):
                wheel.extract(member, VENDOR)
        print(f'vendored {name}=={version}')
    STAMP.write_text(lock_hash() + '\n', encoding='utf-8')


def download(name: str, version: str, hashes: set[str]) -> bytes:
    """The pure-Python wheel of ``name==version`` whose hash is pinned; exits when there is none, or
    when the bytes downloaded are not the pinned ones."""
    url = next((url for url, sha256 in pure_wheels(name, version) if sha256 in hashes), None)
    if url is None:
        sys.exit(f'{name}=={version}: no pure-Python (py3-none-any) wheel on PyPI has a pinned hash')
    with urllib.request.urlopen(url) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() not in hashes:
        sys.exit(f'{name}=={version}: sha256 mismatch for {url}')
    return data


def vendored(member: str) -> bool:
    """Whether a wheel's ``member`` is unpacked: the package itself, and of its ``*.dist-info`` only
    METADATA and the license files; never ``*.data`` (scripts, headers)."""
    top, _, rest = member.partition('/')
    if top.endswith('.dist-info'):
        return rest == 'METADATA' or bool(LICENSE_FILE.search(rest))
    return not top.endswith('.data')


def lock_hash() -> str:
    return hashlib.sha256(LOCK.read_bytes()).hexdigest()


def is_fresh() -> bool:
    """Whether _vendor/ was unpacked from the lock as it is now."""
    return STAMP.is_file() and STAMP.read_text(encoding='utf-8').strip() == lock_hash()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--relock', action='store_true', help="re-pin each locked version's wheel hash first")
    parser.add_argument('--if-stale', action='store_true', help='do nothing when the copy matches the lock')
    args = parser.parse_args()
    if args.relock:
        relock()
    if args.if_stale and is_fresh():
        return
    extract()


if __name__ == '__main__':
    main()
