#!/bin/bash

# This script builds the motor wheel package

# Clean up any existing build artifacts that might cause import issues
rm -rf build/
rm -rf motor.egg-info/
rm -rf dist/

# Build the wheel package
python setup.py bdist_wheel
