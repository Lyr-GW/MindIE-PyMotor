# Skill: GitHub ↔ Gitcode 同步操作 SOP

## 何时使用本 skill

- 需要把 GitHub 上的 PR / 分支同步到 Gitcode 同名分支以便在 Gitcode 上发起对 Ascend 上游的 PR；
- 用户反馈"Gitcode 上 PR diff 出现无关 commits"；
- 用户反馈"Gitcode 上 commits 提交人不是 LinWei100"；
- 修改 sync workflow 自身（`.github/workflows/sync-to-gitcode.yml` 等）；
- 合入会改变 sync 行为的 PR 后，需要把已存在的 feature 分支重新触发同步。

> 不要直接在 Gitcode 端对镜像分支提交，sync workflow 是 force-push，会被覆盖。所有修改都在 GitHub 侧进行，Gitcode 只用于 review 和发起到 Ascend 上游的 PR。

---

## 三套仓库的角色

| 仓库 | 角色 | 谁能写 |
| --- | --- | --- |
| `github.com/Lyr-GW/MindIE-PyMotor` | **真实开发仓**（cloud agent push 到这里） | cloud agent + 用户 |
| `gitcode.com/LinWei100/MindIE-PyMotor` | 用户的 Gitcode fork（sync workflow 推送目标，**镜像**） | sync workflow（force push） |
| `gitcode.com/Ascend/MindIE-PyMotor` | **业务上游主仓**（用户最终向这里提 PR） | Ascend 维护者 |

**用户在 Gitcode 发起 PR 的 source / target**：
- source = `LinWei100:cursor/<feature>-c6af`
- target = `Ascend:master`

---

## 当前 sync workflow 的核心机制（PR #5 / #7 / #8 已合入）

### 触发

`on: push` 任意分支，外加 `workflow_dispatch`。

### 三类分支的处理路径

| 分支类型 | 判定 | 处理 |
| --- | --- | --- |
| **`master`** | `github.ref_name == 'master'` | filter-repo 从历史中 strip `GITCODE_STRIP_PATHS`，force push 到 LinWei100/master。**LinWei100/master 与 Ascend/master 在 commit hash 层面是发散的**（filter-repo 重写过 hash），但内容等价。 |
| **业务 feature 分支** | `github.ref_name != 'master'` 且未触碰 `GITCODE_STRIP_PATHS` | rebase `--onto ascend/master` + `--exec 'git commit --amend --no-edit --reset-author'`，重写 author/committer 为 `LinWei100 <linwei100@huawei.com>`，force push 到 LinWei100/<branch>。`HEAD~N == ascend/master HEAD`，PR diff 干净。 |
| **GitHub-only feature 分支** | feature 分支独有 commits 触碰 `GITCODE_STRIP_PATHS` 中任一路径（如修改 sync workflow 自身） | "Decide" step 设 `skip=true`，跳过 rebase 和 push，仅打 notice。workflow run 仍 success。 |

### `GITCODE_STRIP_PATHS` 列表（同步基础设施文件，不进 Gitcode）

```
.github/workflows/sync-to-gitcode.yml
.github/workflows/pull-from-upstream.yml
scripts/sync-helpers.sh
```

### Author 重写

- 默认 `LinWei100 <linwei100@huawei.com>`（Ascend 历史 commit author 一致）；
- 可被 GitHub repo Secrets `GITCODE_AUTHOR_NAME` / `GITCODE_AUTHOR_EMAIL` 覆盖。

### 必需的 GitHub Repo Secret

| Secret | 用途 | 必需？ |
| --- | --- | --- |
| `GITCODE_TOKEN` | Gitcode personal access token（OAuth2），用于 `git push https://oauth2:$TOKEN@gitcode.com/...` | **必需** |
| `GITCODE_AUTHOR_NAME` | 覆盖默认 author name | 可选 |
| `GITCODE_AUTHOR_EMAIL` | 覆盖默认 author email | 可选 |

---

## Cloud Agent 的标准操作流程

### A. 推一个新 feature 分支到 Gitcode

```bash
# 1. 从最新 master 拉分支
git checkout master && git pull --ff-only origin master
git checkout -b cursor/<descriptive>-c6af   # 全小写, -c6af 后缀

# 2. 业务修改 + 提交（多 commit 可保留逻辑划分）
# ...
git add ... && git commit -m "..."

# 3. push
git push -u origin cursor/<descriptive>-c6af
```

push 后 sync workflow 自动跑。**等 ~30 秒**后验证：

```bash
RUN_ID=$(gh run list --workflow="Sync to Gitcode" --branch=cursor/<descriptive>-c6af --limit 1 --json databaseId -q '.[0].databaseId')
gh run view "$RUN_ID" --log 2>/dev/null | grep -E "Rebased|Synced|Skipping|::error" | head -10
```

期望日志：

```
✅ Rebased <branch> onto ascend/master (7a99645…) and rewrote author/committer to LinWei100 <linwei100@huawei.com>.
✅ Synced <branch> → gitcode.com/LinWei100/MindIE-PyMotor
```

### B. 合入了影响 sync workflow 的 PR 后，调整已有 feature 分支

每次合入下列任一 PR 后，所有 OPEN 的 feature 分支都需要 rebase 到新 master 并 force-push：

- 修改 `.github/workflows/sync-to-gitcode.yml` 的 PR；
- 修改 `GITCODE_STRIP_PATHS` 列表的 PR；
- 修改 sync 行为的任何 PR。

```bash
git checkout master && git pull --ff-only origin master
for branch in $(gh pr list --state=open --json headRefName -q '.[].headRefName'); do
  git checkout "$branch"
  git rebase origin/master
  git push --force-with-lease origin "$branch"
done
```

每条分支等 sync workflow 跑完，逐个验证（见下面"验证 Gitcode 上分支"）。

### C. 修改 sync workflow 本身

```bash
# 单独建分支，不要混入业务 PR
git checkout -b cursor/gitcode-sync-<改什么>-c6af

# 修改 .github/workflows/sync-to-gitcode.yml ...
git add .github/workflows/sync-to-gitcode.yml && git commit -m "ci(sync-to-gitcode): ..."
git push -u origin cursor/gitcode-sync-<改什么>-c6af
```

push 后 sync workflow 跑在**新版自身**上，"Decide" step 会识别为 GitHub-only PR 并 skip 整个 sync，run 仍 success（这是预期的，本 PR 在 Gitcode 上无意义）。

合入此类 PR 后，请按 B 调整其它 feature 分支。

---

## 验证 Gitcode 上分支正确性

```bash
# 1. clone Gitcode 镜像
rm -rf /tmp/gc-verify && cd /tmp
git clone --depth=8 --branch <branch> https://gitcode.com/LinWei100/MindIE-PyMotor.git gc-verify
cd gc-verify

# 2. fetch Ascend master 作对比
git remote add ascend https://gitcode.com/Ascend/MindIE-PyMotor.git
git fetch --no-tags --depth=2 ascend master

# 3. 检查 author/committer
git log -5 --format="%h%n  Author:    %an <%ae>%n  Committer: %cn <%ce>%n  Subject:   %s%n"
# 期望：feature 分支独有 commits 全部 LinWei100 <linwei100@huawei.com>

# 4. 检查 hash 对齐（N = 独有 commit 数）
N=$(git rev-list ascend/master..HEAD --count)
echo "HEAD~$N:        $(git rev-parse HEAD~$N)"
echo "ascend/master: $(git rev-parse ascend/master)"
# 期望两者完全相同 → Gitcode PR diff 只显示 N 条独有 commits
```

如果 `HEAD~N != ascend/master HEAD`，说明 sync workflow rebase 步未生效或被 skip，重新 push 触发或检查 workflow run 失败原因。

---

## 已知问题与历史决策

### 1. "Gitcode PR diff 出现无关 commits"（PR #7 解决）

- **症状**：在 Gitcode 上发起 `LinWei100:cursor/* → Ascend:master` PR 时，diff 列表包含上百条与本 PR 无关的 commits。
- **原因**：早期 sync workflow（PR #5）用 `git filter-repo` 镜像 master，重写了所有 commit 的 hash。LinWei100/master 与 Ascend/master 内容相同但 hash 全不同 → Git 找不到 commit 级 merge-base → 把 LinWei100 这边的整段历史都视作 PR 引入的新 commit。
- **修复**（PR #7）：feature 分支 push 前**自动 rebase 到 Ascend/master HEAD**，让分支祖先 hash 与 Ascend 严格对齐。

### 2. "Gitcode commits 提交人不是 LinWei100"（PR #8 解决）

- **症状**：Gitcode 上 cursor 分支顶部 commits 显示 `Cursor Agent <cursoragent@cursor.com>`。
- **修复**（PR #8）：rebase 时用 `--exec 'git commit --amend --no-edit --reset-author'`，配合预设 `git config user.name/email = LinWei100`，让 author + committer 都重写。

### 3. "Sync workflow 自身的 PR 触发 rebase 冲突"（PR #7 解决）

- **症状**：修改 `.github/workflows/sync-to-gitcode.yml` 的 PR push 后 workflow rebase 失败：`CONFLICT (modify/delete): .github/workflows/sync-to-gitcode.yml deleted in HEAD and modified in <commit>`。
- **原因**：Ascend/master 上根本不存在这个文件，rebase 必然冲突。
- **修复**：rebase 之前先用 "Decide" step 检测分支是否触碰 `GITCODE_STRIP_PATHS`，触碰则整体 skip 同步（不当作错误）。

### 4. force-push 风险（设计接受）

- 每次 sync workflow 都对 Gitcode 同名分支 force-push（rebase 必然改 hash）。
- 因此**不要在 Gitcode 端直接对镜像分支提交**，会被下次 sync 覆盖。
- 所有修改在 GitHub 侧进行，Gitcode 端仅做 review 和向 Ascend 提 PR。

### 5. master 同步的 hash 发散（设计接受）

- LinWei100/master 仍走 filter-repo strip 路径，与 Ascend/master 在 commit hash 上是发散的。
- 这是**有意保留**的：feature 分支不再以 LinWei100/master 为 base（PR #7 以后改为基于 Ascend/master），所以 LinWei100/master 的 hash 是否与 Ascend 一致已无所谓，仅作为本地参考镜像。

---

## 故障排查清单

| 现象 | 可能原因 | 排查命令 |
| --- | --- | --- |
| `gh run list` 显示 sync workflow `failure` | rebase 冲突；fetch ascend 失败；token 失效 | `gh run view <id> --log-failed \| tail -50` |
| Gitcode 上分支没更新 | feature 分支被识别为 GitHub-only（PR 触碰 strip 列表） | 找 `notice::Feature branch ... modifies GitHub-only path(s)` |
| Gitcode commits 仍是 cursoragent | feature 分支基于的 master 早于 PR #8，新规则未生效 | rebase 到最新 master 后重新 push |
| Gitcode PR 仍含无关 commits | feature 分支基于的 master 早于 PR #7 | rebase 到最新 master 后重新 push |
| `git push gitcode` 401/403 | `GITCODE_TOKEN` 失效或未配置 | GitHub Settings → Secrets → 重新设置 |
| `git fetch ascend master` 超时 | Gitcode 网络抖动 | re-run workflow（Actions UI → re-run failed jobs） |

---

## 关键命令速查

### 等 sync workflow 跑完

```bash
for i in 1 2 3 4 5 6 7; do
  out=$(gh run list --workflow="Sync to Gitcode" --branch=<branch> --limit 1 --json databaseId,status,conclusion 2>/dev/null)
  status=$(echo "$out" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d[0].get("status","")+"|"+(d[0].get("conclusion","") or ""))' 2>/dev/null)
  echo "[try $i] $status"
  case "$status" in completed*) break ;; esac
  sleep 12
done
```

### 一键 rebase + push 已有 feature 分支

```bash
git checkout master && git pull --ff-only origin master
git checkout <branch> && git rebase origin/master && git push --force-with-lease origin <branch>
```

### 查看 sync workflow 关键日志行

```bash
gh run view <RUN_ID> --log 2>/dev/null | \
  grep -E "OLD_BASE \(merge|NEW_BASE \(Asc|✅ Rebased|✅ Synced|Skipping|::error" | head -15
```

### 模拟 Gitcode PR diff（应只含本特性 commit）

```bash
cd /tmp/gc-verify   # 见上面"验证"段
git log --oneline ascend/master..HEAD
```

---

## 不要做的事

1. **不要** 把 sync workflow 修改和业务修改放在同一个 PR（业务 PR 会被识别为 GitHub-only 跳过同步，业务变更上不了 Gitcode）。
2. **不要** 在 Gitcode 端的镜像分支直接 commit / merge（force-push 会覆盖）。
3. **不要** 把 `LinWei100/master` 的 commit hash 当作"上游引用"——它是 filter 后的镜像，hash 与 Ascend 不一致。永远以 `Ascend/master` 为 base。
4. **不要** 在 sync workflow 里 push 到 GitHub `origin`（filter-repo 已主动移除 origin remote 防止误操作）。
5. **不要** 用 `--force-with-lease` 推到 Gitcode：filter-repo / rebase 后没有 tracking ref，必须 `--force`。

---

## 相关 PR 与设计文档

| PR | 内容 |
| --- | --- |
| #5 | 初版 sync workflow：filter-repo strip GitHub-only paths |
| #7 | feature 分支 sync 前 rebase 到 Ascend/master，根除"无关 commit"问题；GitHub-only PR 整体跳过 |
| #8 | rebase 时重写 author/committer 为 LinWei100 |
