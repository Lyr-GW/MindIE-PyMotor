#!/bin/bash

# Script to generate Python code from .proto files
# This script generates _pb2.py and _pb2_grpc.py files from .proto files

set -e  # Exit on error

# Get the project root directory
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

# Check if grpcio-tools is installed
if ! python3 -c "import grpc_tools.protoc" 2>/dev/null; then
    echo "Error: grpcio-tools is not installed."
    echo "Please install it with: pip install grpcio-tools>=1.40.0"
    exit 1
fi

# Find all .proto files
PROTO_FILES=$(find . -name "*.proto" -type f)

if [ -z "$PROTO_FILES" ]; then
    echo "No .proto files found."
    exit 0
fi

# Generate Python code for each .proto file
for proto_file in $PROTO_FILES; do
    echo "Generating code from $proto_file..."
    
    # Get the directory containing the .proto file
    proto_dir=$(dirname "$proto_file")
    
    # Get the base name of the .proto file (without extension)
    proto_base=$(basename "$proto_file" .proto)
    
    # Generate _pb2.py and _pb2_grpc.py files
    # Change to proto directory for protoc execution (protoc requires proto_path to match file location)
    cd "$proto_dir"
    python3 -m grpc_tools.protoc \
        --proto_path="." \
        --python_out="." \
        --grpc_python_out="." \
        "$(basename "$proto_file")"
    cd "$ROOT_DIR"
    
    if [ $? -eq 0 ]; then
        echo "✓ Successfully generated code from $proto_file"
        
        # Fix import paths in _pb2_grpc.py if it exists
        pb2_grpc_file="${proto_dir}/${proto_base}_pb2_grpc.py"
        if [ -f "$pb2_grpc_file" ]; then
            # Get the Python package path (e.g., motor/controller/ft/cluster_grpc/cluster_fault.proto -> motor.controller.ft.cluster_grpc)
            # Remove leading ./ and .proto extension, get directory path, then convert / to .
            proto_rel_path=$(echo "$proto_file" | sed 's|^\./||' | sed 's|\.proto$||')
            package_path=$(dirname "$proto_rel_path" | sed 's|/|.|g')
            if [ "$package_path" = "." ]; then
                package_path=""
            fi
            
            # Replace relative import with absolute import
            # Pattern: import cluster_fault_pb2 -> from motor.controller.ft.cluster_grpc import cluster_fault_pb2
            # Use sed with word boundary to avoid double replacement
            if [ -n "$package_path" ]; then
                # First check if already replaced to avoid double replacement
                if ! grep -q "^from ${package_path} import ${proto_base}_pb2" "$pb2_grpc_file"; then
                    sed -i "s|^import ${proto_base}_pb2\([^_]\)|from ${package_path} import ${proto_base}_pb2\1|g" "$pb2_grpc_file"
                    sed -i "s|^import ${proto_base}_pb2 as|from ${package_path} import ${proto_base}_pb2 as|g" "$pb2_grpc_file"
                fi
            fi
            
            echo "  Fixed import paths in ${proto_base}_pb2_grpc.py"
        fi
    else
        echo "✗ Failed to generate code from $proto_file"
        exit 1
    fi
done

echo "All protobuf files generated successfully."

