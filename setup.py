# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.

from setuptools import setup, find_packages


setup(
    name="motor",
    version="0.1.0",
    description="A Python package named motor.",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[

    ],
    include_package_data=True,
    zip_safe=False,
    entry_points={
        "console_scripts": [
            "engine_server = motor.engine_server.cli.main:main",
        ]
    }
)
