# Endpoint policy example

Build and install into the same Python environment as Motor:

```bash
pip wheel --no-deps ./examples/scheduler_plugin -w /tmp/motor-policies
pip install /tmp/motor-policies/acme_motor_policies-0.1.0-py3-none-any.whl
```

Add the following inside `motor_coordinator_config.scheduler_config` and restart
the inference workers:

```json
{
  "policy_plugin": {
    "name": "acme.weighted_load",
    "roles": ["prefill", "union"],
    "options": {"instance_weight": 0.05},
    "timeout_ms": 50
  }
}
```

The policy picks the minimum `active_tokens + instance_weight * instance_active_tokens`.
An optional `preferred_node` option narrows the candidates to the matching
`node_address` (currently the endpoint IP), when present. This field is an engine
address and does not necessarily identify a physical host behind Pod networking.
Pins and session affinity take precedence. The role's existing built-in policy is
used on plugin failure, timeout, cooldown or saturation.

See [the developer contract](../../docs/zh/design/scheduler_policy_plugin.md)
for API, isolation, metrics and limitations.
