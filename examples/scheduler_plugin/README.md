# Endpoint policy example

Build and install into the same Python environment as Motor:

```bash
pip wheel --no-deps ./examples/scheduler_plugin -w /tmp/motor-policies
pip install /tmp/motor-policies/acme_motor_policies-0.1.0-py3-none-any.whl
```

Add the following inside `motor_coordinator_config.scheduler_config` and restart
the inference workers. This reuses configuration for P/D; each role still gets an
independent policy instance, subprocess, lock, cooldown, recovery task and metrics:

```json
{
  "policy_plugin": [
    {
      "role": ["prefill", "decode"],
      "name": "acme.weighted_load",
      "options": {"instance_weight": 0.05},
      "timeout_ms": 50
    }
  ]
}
```

To use different names and options for P/D, the plugin package author can register
additional Entry Points in its `pyproject.toml`. The following names are illustrative
and are **not registered by the example wheel as shipped**. They can point to the
same example class, or to separate customer implementations:

```toml
[project.entry-points."mindie_motor.scheduling_policies"]
"acme.prefill_weighted" = "acme_motor_policies:WeightedLoadPolicy"
"acme.decode_weighted" = "acme_motor_policies:WeightedLoadPolicy"
```

After registering, rebuilding and installing that package, use:

```json
{
  "policy_plugin": [
    {"role": ["prefill"], "name": "acme.prefill_weighted", "options": {"instance_weight": 0.05}},
    {"role": ["decode"], "name": "acme.decode_weighted", "options": {"instance_weight": 0.2}}
  ]
}
```

Two items may also use the existing `acme.weighted_load` name with different options
or budgets. A shared name never shares runtime state. Union does not inherit the
Prefill plugin: add `"union"` explicitly to a `role` array to cover hybrid routing;
Encode is explicit as well. `role` must be a non-empty array. Duplicate roles within
an item or overlapping roles across items, missing role/name and unknown keys are
configuration errors. The old single-object `policy_plugin` with a `roles` key is
rejected: wrap it in a list and rename `roles` to `role`.

The policy picks the minimum `active_tokens + instance_weight * instance_active_tokens`.
An optional `preferred_node` option narrows the candidates to the matching
`node_address` (currently the endpoint IP), when present. This field is an engine
address and does not necessarily identify a physical host behind Pod networking.
Pins and session affinity take precedence. `prefill_scheduler_type` remains the
P/U/E default and fallback; `decode_scheduler_type` remains the D default and
fallback. An unconfigured role runs its built-in policy directly. Plugin failure,
timeout, cooldown or saturation falls back only for that role.

Omitting `policy_plugin` or setting it to `[]` creates no plugin subprocesses. Each
worker has at most four, one per configured role. Worker `/metrics` exposes
`motor_policy_*` samples with `policy` and `role` labels; scrape every worker.

See [the developer contract](../../docs/zh/design/scheduler_policy_plugin.md)
for API, isolation, metrics, migration and validation requirements. Historical
single-runner cluster results do not validate the role-isolated runtime.

中文快速接入指南：[编写、安装和启用自定义选点插件](../../docs/zh/user_guide/features/inference_scheduling/scheduler_policy_plugin.md)。
