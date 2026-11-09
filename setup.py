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

import importlib.util
import sys
from pathlib import Path

from setuptools import find_packages, setup

package_name = 'ros_tui'

# The bundled textual stack (ros_tui/_vendor) is not in git: scripts/vendor.py unpacks it from the
# lock and stamps it with the lock's hash. Refuse to build without it, or from an older lock.
vendor_script = Path(__file__).resolve().parent / 'scripts' / 'vendor.py'
spec = importlib.util.spec_from_file_location('vendor_script', vendor_script)
vendor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vendor)
if not vendor.is_fresh():
    # Printed rather than passed to sys.exit: colcon runs this file through distutils' run_setup,
    # which swallows a SystemExit's message.
    print(f'ros_tui: the bundled textual is missing or out of date; run {vendor_script} first', file=sys.stderr)
    sys.exit(1)

setup(
    name=package_name,
    version='0.2.0',
    packages=find_packages(exclude=['test']),
    # The bundled textual stack also ships its non-Python files and licenses.
    package_data={package_name: ['_vendor/**/*']},
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Johan Ubbink',
    maintainer_email='johanubbink@users.noreply.github.com',
    description='Terminal UI for exploring and exercising ROS 2 topics, services, actions and nodes',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'ros_tui = ros_tui.main:main',
        ],
    },
)
