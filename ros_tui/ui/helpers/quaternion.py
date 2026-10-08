#!/usr/bin/env python3
# Copyright 2026 Jonas Vervoort
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

"""Quaternion maths for the Quaternion helper: from roll / pitch / yaw, from an axis and an angle,
normalised, and rounded for display.

Conventions match ROS (tf2 / tf_transformations): roll, pitch and yaw rotate about the fixed X, Y
and Z axes in that order ('sxyz'), angles are in radians, and quaternions are (x, y, z, w).
"""

import math


def quat_from_euler(roll: float, pitch: float, yaw: float) -> tuple[float, float, float, float]:
    """(x, y, z, w) from ROS RPY: roll=X, pitch=Y, yaw=Z, intrinsic ZYX ('sxyz'), radians."""
    cr, sr = math.cos(roll / 2.0), math.sin(roll / 2.0)
    cp, sp = math.cos(pitch / 2.0), math.sin(pitch / 2.0)
    cy, sy = math.cos(yaw / 2.0), math.sin(yaw / 2.0)
    return (sr * cp * cy - cr * sp * sy,
            cr * sp * cy + sr * cp * sy,
            cr * cp * sy - sr * sp * cy,
            cr * cp * cy + sr * sp * sy)


def quat_about_axis(ax: float, ay: float, az: float, angle: float) -> tuple[float, float, float, float]:
    """(x, y, z, w) for a rotation of ``angle`` rad about axis (ax, ay, az); zero axis -> identity."""
    norm = math.sqrt(ax * ax + ay * ay + az * az)
    if norm == 0.0:
        return 0.0, 0.0, 0.0, 1.0
    scale = math.sin(angle / 2.0) / norm
    return ax * scale, ay * scale, az * scale, math.cos(angle / 2.0)


def normalize_quat(x: float, y: float, z: float, w: float) -> tuple[float, float, float, float]:
    """Scale (x, y, z, w) to unit length; a zero-length quaternion becomes the identity."""
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm == 0.0:
        return 0.0, 0.0, 0.0, 1.0
    return x / norm, y / norm, z / norm, w / norm


def clean_quat(x: float, y: float, z: float, w: float, ndigits: int = 6) -> dict[str, float]:
    """Round to ``ndigits`` and collapse ``-0.0`` to ``0.0`` so the dumped YAML stays tidy."""
    def clean(value: float) -> float:
        rounded = round(value, ndigits)
        return 0.0 if rounded == 0.0 else rounded

    return {'x': clean(x), 'y': clean(y), 'z': clean(z), 'w': clean(w)}


def yaw_of(x: float, y: float, z: float, w: float) -> float:
    """The yaw (rotation about Z, radians) of a quaternion that only turns about Z."""
    return 2 * math.atan2(z, w)
