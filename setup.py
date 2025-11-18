# coding=utf-8
# Copyright (c) 2025, HUAWEI CORPORATION.  All rights reserved.

import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from setuptools import setup, find_packages
from setuptools.command.build_py import build_py
from setuptools.command.build import build

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)


def generate_proto_files():
    """Generate Python code from .proto files."""
    try:
        # Check if grpcio-tools is available
        import grpc_tools.protoc
    except ImportError:
        logging.warning("grpcio-tools is not installed. Skipping protobuf generation.")
        logging.info("Please install it with: pip install grpcio-tools>=1.40.0")
        return
    
    # Get the project root directory
    root_dir = Path(__file__).parent.absolute()
    
    # Find all .proto files
    proto_files = list(root_dir.rglob("*.proto"))
    
    if not proto_files:
        logging.info("No .proto files found.")
        return
    
    # Generate Python code for each .proto file
    for proto_file in proto_files:
        logging.info(f"Generating code from {proto_file.relative_to(root_dir)}...")
        
        proto_dir = proto_file.parent
        proto_base = proto_file.stem  # filename without extension
        
        # Generate _pb2.py and _pb2_grpc.py files
        # Change to proto directory for protoc execution (protoc requires proto_path to match file location)
        original_cwd = os.getcwd()
        try:
            os.chdir(proto_dir)
            subprocess.check_call([
                sys.executable, "-m", "grpc_tools.protoc",
                "--proto_path=.",
                "--python_out=.",
                "--grpc_python_out=.",
                proto_file.name
            ])
        finally:
            os.chdir(original_cwd)
        
        # Fix import paths in _pb2_grpc.py if it exists
        pb2_grpc_file = proto_dir / f"{proto_base}_pb2_grpc.py"
        if pb2_grpc_file.exists():
            # Get the directory path, not the file path
            proto_rel_path = proto_file.relative_to(root_dir)
            package_path = str(proto_rel_path.parent).replace('/', '.').replace('\\', '.')
            
            # Read the file and fix imports
            content = pb2_grpc_file.read_text(encoding='utf-8')
            # Replace relative import with absolute import
            if package_path:
                # Use regex-like replacement to avoid double replacement
                content = re.sub(
                    rf'^import {re.escape(proto_base)}_pb2\b',
                    f'from {package_path} import {proto_base}_pb2',
                    content,
                    flags=re.MULTILINE
                )
                content = re.sub(
                    rf'^import {re.escape(proto_base)}_pb2 as',
                    f'from {package_path} import {proto_base}_pb2 as',
                    content,
                    flags=re.MULTILINE
                )
            pb2_grpc_file.write_text(content, encoding='utf-8')
            logging.info(f"  Fixed import paths in {proto_base}_pb2_grpc.py")
        
        logging.info(f"✓ Successfully generated code from {proto_file.name}")


class BuildCommand(build):
    """Custom build command to generate protobuf files before building."""
    
    def run(self):
        # Generate protobuf files before building
        generate_proto_files()
        # Run the standard build command
        super().run()


class BuildPyCommand(build_py):
    """Custom build_py command to generate protobuf files before building."""
    
    def run(self):
        # Generate protobuf files before building
        generate_proto_files()
        # Run the standard build_py command
        super().run()


setup(
    name="motor",
    version="0.1.0",
    description="A Python package named motor.",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        
    ],
    include_package_data=True,
    zip_safe=False,
    cmdclass={
        'build': BuildCommand,
        'build_py': BuildPyCommand,
    },
    entry_points={
        "console_scripts": [
            "engine_server = motor.engine_server.cli.main:main",
        ]
    }
)
