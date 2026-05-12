# MindIE PyMotor

Huawei Ascend NPU inference cluster management framework for LLMs (PD-disaggregated inference).

## Cursor Cloud specific instructions

### Project Overview

This is a Python (>= 3.11) project using FastAPI/uvicorn for REST APIs, gRPC for etcd communication, and pytest for testing. The codebase has four main service components: **Controller**, **Coordinator**, **NodeManager**, and **EngineServer**, plus shared libraries in `motor/common/`.

### Key Commands

| Task | Command |
|---|---|
| Run all tests | `pytest tests/ -p no:xdist -q` or `./tests/run_tests.sh --serial` |
| Run tests (parallel) | `pytest tests/ -n 6` or `./tests/run_tests.sh` |
| Run specific tests | `pytest tests/controller/ -v` |
| Build wheel | `bash build.sh` |
| Generate protobuf | `bash scripts/generate_proto.sh` |
| Lint (basic) | `flake8 motor/ --max-line-length=120 --select=E9,F63,F7,F82` |

### Environment Notes

- `$HOME/.local/bin` must be on `PATH` for pip-installed tools (pytest, uvicorn, flake8). The update script handles this via `export PATH="$HOME/.local/bin:$PATH"`.
- `build.sh` requires a `python` command (not just `python3`). A symlink `ln -sf $(which python3) /usr/local/bin/python` resolves this.
- Protobuf files (`*_pb2.py`, `*_pb2_grpc.py`) are generated artifacts in `motor/common/etcd/proto/` — they must be regenerated after any `.proto` file changes via `bash scripts/generate_proto.sh`.
- No dedicated linter is configured in the repo. The repository has no `.flake8`, `ruff.toml`, or `pyproject.toml` linting config.
- Tests are fully self-contained with mocks — no external services (etcd, K8s, Ascend NPU) are needed.
- `PYTHONPATH` must include the repo root and `motor/` subdirectory: `export PYTHONPATH="/workspace:/workspace/motor:$PYTHONPATH"`.
- `run_tests.sh` treats warnings as failures (exit code 1) — this is by design; use `pytest` directly if you want warnings-as-warnings behavior.

### Starting Services Locally

Services can be started locally for dev/testing. Example for Controller:

```bash
export PYTHONPATH="/workspace:/workspace/motor:$PYTHONPATH"
python3 -m motor.controller.main
```

This starts the Controller API on `http://127.0.0.1:1026` with health endpoints at `/startup`, `/readiness`, `/liveness` and instance management at `/controller/register`, `/controller/heartbeat`, etc.

Full inference requires Ascend NPU hardware and Kubernetes — not available in cloud agent VMs. Unit tests cover all functionality via mocks.
