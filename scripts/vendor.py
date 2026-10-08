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

"""Rebuild ros_tui/_vendor/ (textual and its dependencies) from ros_tui/_vendor/vendor.lock.

Each lock line is ``name==version  <wheel url>  sha256=<hash>``. Every wheel is downloaded, its
hash checked, and unpacked into ros_tui/_vendor/; each ``*.dist-info`` keeps only its METADATA
and license files. Commit the result: the package carries its own copy, so neither apt nor colcon
users need pip.

    scripts/vendor.py           # re-extract exactly what vendor.lock pins
    scripts/vendor.py --relock  # after editing a version in vendor.lock: refresh urls + hashes

Only the standard library is used. Only pure-Python (py3-none-any) wheels are accepted, so one
copy works on every Python a ROS distro ships.
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
LOCK = VENDOR / 'vendor.lock'
KEEP = {'__init__.py', 'vendor.lock'}  # The files in _vendor/ that are ours, not unpacked wheels.
LICENSE_FILE = re.compile(r'(LICEN[CS]E|COPYING|NOTICE|AUTHORS)', re.IGNORECASE)


def read_lock() -> list[tuple[str, str, str, str]]:
    """(name, version, url, sha256) for every pinned line of vendor.lock."""
    entries = []
    for line in LOCK.read_text(encoding='utf-8').splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        pin, *rest = line.split()
        name, version = pin.split('==')
        url = rest[0] if rest else ''
        sha256 = rest[1].removeprefix('sha256=') if len(rest) > 1 else ''
        entries.append((name, version, url, sha256))
    return entries


def pure_wheel(name: str, version: str) -> tuple[str, str]:
    """The (url, sha256) of the py3-none-any wheel PyPI has for ``name==version``."""
    with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json') as response:
        files = json.load(response)['urls']
    for file in files:
        if file['packagetype'] == 'bdist_wheel' and file['filename'].endswith('-none-any.whl'):
            return file['url'], file['digests']['sha256']
    sys.exit(f'{name}=={version}: no pure-Python wheel on PyPI')


def relock() -> None:
    lines = [line for line in LOCK.read_text(encoding='utf-8').splitlines() if line.startswith('#')]
    for name, version, _, _ in read_lock():
        url, sha256 = pure_wheel(name, version)
        lines.append(f'{name}=={version}  {url}  sha256={sha256}')
    LOCK.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def extract() -> None:
    for path in VENDOR.iterdir():
        if path.name not in KEEP:
            shutil.rmtree(path) if path.is_dir() else path.unlink()
    for name, version, url, sha256 in read_lock():
        with urllib.request.urlopen(url) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != sha256:
            sys.exit(f'{name}=={version}: sha256 mismatch for {url}')
        with zipfile.ZipFile(BytesIO(data)) as wheel:
            for member in wheel.namelist():
                top, _, rest = member.partition('/')
                if top.endswith('.dist-info') and rest != 'METADATA' \
                        and not LICENSE_FILE.search(rest):
                    continue
                if top.endswith('.data'):
                    continue
                wheel.extract(member, VENDOR)
        print(f'vendored {name}=={version}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--relock', action='store_true', help='refresh the urls and hashes in vendor.lock first')
    args = parser.parse_args()
    if args.relock:
        relock()
    extract()


if __name__ == '__main__':
    main()
