# Endpoint policy example

This example ranks endpoints by `active_tokens + instance_weight * instance_active_tokens`.
The optional `preferred_node` selects matching candidates when available. It matches the
endpoint IP, which may not identify the physical host in a Pod network.

## Use the example

1. Build and install the package in the Python environment used by every Inference Worker:

   ```bash
   python -m pip wheel --no-deps ./examples/scheduler_plugin -w /tmp/motor-policies
   python -m pip install /tmp/motor-policies/acme_motor_policies-0.1.0-py3-none-any.whl
   ```

2. Add the following to `motor_coordinator_config.scheduler_config` in the existing
   `user_config.json`:

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

3. Restart all affected Inference Workers. Check their logs for `Scheduling plugin loaded`,
   then send a request and check that its `scheduled` log shows `policy=plugin:acme.weighted_load`.
   Worker `/metrics` also exposes `motor_policy_*` samples labeled by policy and role.

The configuration above gives Prefill and Decode independent plugin processes and state.
For different options or budgets, use separate items with the same registered name.
Add `union` or `encode` explicitly when those roles need the plugin. Each role may occur
only once in the list.

The built-in policy handles unconfigured roles and plugin failures. Pins and session
affinity take precedence. Remove `policy_plugin` or set it to `[]` and restart the
workers to disable plugins.

For the full steps, validation and troubleshooting, see the [Chinese quick-start guide](../../docs/zh/user_guide/features/inference_scheduling/scheduler_policy_plugin.md).
For API and configuration details, see the [design](../../docs/zh/design/scheduler_policy_plugin.md).
