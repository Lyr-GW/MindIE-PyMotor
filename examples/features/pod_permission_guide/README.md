# Pod 权限说明（seccomp 与 clone3）

## 1. 默认配置说明

本仓库部署模板中，容器 `securityContext.seccompProfile` 默认使用 **`Unconfined`**，即不启用 seccomp 系统调用过滤。此配置可避免因 seccomp 拦截导致的线程创建失败（如 `RuntimeError: can't start new thread`），适用于大多数部署场景。

## 2. seccomp 与 clone3 背景

### 2.1 seccomp 简介

seccomp（secure computing mode）是 Linux 内核的系统调用过滤机制。Kubernetes 中 `securityContext.seccompProfile.type` 常见取值：

| 类型 | 说明 |
|------|------|
| **Unconfined** | 不启用 seccomp 过滤 |
| **RuntimeDefault** | 使用容器运行时（containerd/docker 等）自带的默认策略 |
| **Localhost** | 使用节点本地自定义 seccomp JSON 文件 |

### 2.2 不同架构下 clone3 的差异

线程创建依赖的 syscall 在不同架构上存在差异：

| 架构 | 常用 syscall | 说明 |
|------|--------------|------|
| x86_64 / AMD64 | `clone`, `clone3` | glibc 新版本可能优先使用 clone3 |
| AArch64 / ARM64 | `clone`, `clone3` | 昇腾等 ARM 环境同样可能使用 clone3 |
| 其他 (MIPS, PPC, S390 等) | `clone`, `clone3` | 取决于 glibc 与内核版本 |

**RuntimeDefault** 的默认策略在部分运行时/版本组合下**未放行 clone3**，导致 Python 等使用 pthread 的程序报 `can't start new thread`。该问题与内核版本、containerd/docker、runc/crun、glibc 版本均相关，不同节点表现可能不一致。

## 3. 可选配置方案

### 3.1 方案一：Unconfined（默认）

当前模板默认配置，无需额外操作，兼容性最好。

### 3.2 方案二：RuntimeDefault

若您的集群在 `seccompProfile.type: RuntimeDefault` 下运行正常，可直接使用 RuntimeDefault，以获得运行时默认的安全过滤：

```yaml
securityContext:
  seccompProfile:
    type: RuntimeDefault
```

建议先在测试环境验证，确认无 `can't start new thread` 等问题后再用于生产。

### 3.3 方案三：Localhost 自定义 profile（更高安全等级）

若需在保证 clone3 可用的前提下提升安全等级，可使用 Localhost 方式，配合自定义 seccomp profile。

**步骤：**

1. 将 profile JSON 放到各节点：`/var/lib/kubelet/seccomp/profiles/mindie/mindie-motor-seccomp-blacklist.json`（可通过 DaemonSet 或人工拷贝实现）
2. 在业务 Pod 的 `securityContext` 中配置：

```yaml
securityContext:
  seccompProfile:
    type: Localhost
    localhostProfile: profiles/mindie/mindie-motor-seccomp-blacklist.json
```

**Profile 黑名单参考（仅供参考，请根据实际需求调整）：**

```json
{
  "defaultAction": "SCMP_ACT_ALLOW",
  "architectures": [
    "SCMP_ARCH_X86_64",
    "SCMP_ARCH_X86",
    "SCMP_ARCH_X32",
    "SCMP_ARCH_AARCH64",
    "SCMP_ARCH_ARM",
    "SCMP_ARCH_MIPS",
    "SCMP_ARCH_MIPS64",
    "SCMP_ARCH_MIPS64N32",
    "SCMP_ARCH_MIPSEL",
    "SCMP_ARCH_MIPSEL64",
    "SCMP_ARCH_MIPSEL64N32",
    "SCMP_ARCH_PPC64LE",
    "SCMP_ARCH_S390X",
    "SCMP_ARCH_RISCV64"
  ],
  "syscalls": [
    {
      "names": [
        "bpf",
        "kexec_file_load",
        "kexec_load",
        "open_by_handle_at",
        "perf_event_open",
        "personality",
        "pivot_root",
        "ptrace",
        "reboot",
        "setdomainname",
        "sethostname",
        "setns",
        "syslog",
        "unshare"
      ],
      "action": "SCMP_ACT_ERRNO",
      "errnoRet": 1
    },
    {
      "names": ["finit_module", "init_module", "delete_module"],
      "action": "SCMP_ACT_ERRNO",
      "errnoRet": 1
    },
    {
      "names": ["mount", "umount", "umount2"],
      "action": "SCMP_ACT_ERRNO",
      "errnoRet": 1
    },
    {
      "names": ["adjtimex", "clock_adjtime", "clock_settime", "settimeofday", "stime"],
      "action": "SCMP_ACT_ERRNO",
      "errnoRet": 1
    }
  ]
}
```

该 profile 采用「默认允许 + 黑名单」方式，仅显式拒绝部分高危 syscall，clone3 等常用 syscall 默认放行。

## 4. 故障排查

若出现 `RuntimeError: can't start new thread`：

- 检查 `seccompProfile.type`，可先改为 `Unconfined` 验证
- 查看节点 `dmesg`/audit 日志中是否有 seccomp 拒绝记录
- 对比异常节点与正常节点的内核、containerd、glibc 版本
