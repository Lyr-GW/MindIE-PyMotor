#!/usr/bin/env bash
#
# GitCode 同步辅助脚本
# 用法: source scripts/sync-helpers.sh
#
# 远程仓库说明:
#   origin   → gitcode.com/Ascend/MindIE-PyMotor       (业务上游仓)
#   own      → gitcode.com/LinWei100/MindIE-PyMotor     (个人 Gitcode 镜像)
#   github   → github.com/Lyr-GW/MindIE-PyMotor         (主要开发仓)
#

set -euo pipefail

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ─── sync-status: 查看所有远程同步状态 ──────────────────────────
sync-status() {
    cd "$REPO_DIR"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  远程仓库同步状态${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    # 先 fetch 所有远程
    echo -e "\n${YELLOW}↻ 正在 fetch 所有远程...${NC}"
    git fetch --all --prune 2>/dev/null || true

    local current_branch
    current_branch=$(git rev-parse --abbrev-ref HEAD)

    echo -e "\n当前分支: ${GREEN}$current_branch${NC}"

    for remote in github own origin; do
        if git remote get-url "$remote" &>/dev/null; then
            local url
            url=$(git remote get-url "$remote" | sed 's|https://oauth2:[^@]*@|https://***@|')

            echo -e "\n${CYAN}[$remote]${NC} $url"

            # 检查该远程是否有此分支
            if git ls-remote --heads "$remote" "refs/heads/$current_branch" 2>/dev/null | grep -q .; then
                local local_head remote_head
                local_head=$(git rev-parse HEAD)
                remote_head=$(git rev-parse "$remote/$current_branch" 2>/dev/null || echo "")

                if [ -z "$remote_head" ]; then
                    echo -e "  状态: ${YELLOW}⚠ 本地有此分支，远程无${NC}"
                elif [ "$local_head" = "$remote_head" ]; then
                    echo -e "  状态: ${GREEN}✓ 已同步${NC}"
                else
                    local behind ahead
                    behind=$(git rev-list --count HEAD.."$remote/$current_branch" 2>/dev/null || echo "?")
                    ahead=$(git rev-list --count "$remote/$current_branch"..HEAD 2>/dev/null || echo "?")
                    echo -e "  状态: ${YELLOW}↕ 本地领先 $ahead / 落后 $behind${NC}"
                fi
            else
                echo -e "  状态: ${YELLOW}○ 远程无此分支${NC}"
            fi
        fi
    done
    echo ""
}

# ─── sync-push: 推送当前分支到 Gitcode 个人仓 ──────────────────
sync-push() {
    cd "$REPO_DIR"
    local branch
    branch=$(git rev-parse --abbrev-ref HEAD)

    echo -e "${YELLOW}↗ 推送 $branch → gitcode.com/LinWei100/MindIE-PyMotor${NC}"
    git push own "$branch" --force-with-lease

    # 同时推送 tags
    git push own --tags

    echo -e "${GREEN}✓ 推送完成${NC}"
}

# ─── sync-push-github: 推送当前分支到 GitHub ────────────────────
sync-push-github() {
    cd "$REPO_DIR"
    local branch
    branch=$(git rev-parse --abbrev-ref HEAD)

    echo -e "${YELLOW}↗ 推送 $branch → github.com/Lyr-GW/MindIE-PyMotor${NC}"
    git push github "$branch" --force-with-lease
    git push github --tags

    echo -e "${GREEN}✓ 推送完成${NC}"
}

# ─── sync-pull-upstream: 从 Ascend 上游拉取更新 ────────────────
sync-pull-upstream() {
    cd "$REPO_DIR"

    local upstream_branch="${1:-master}"
    local target_branch="${2:-$(git rev-parse --abbrev-ref HEAD)}"

    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  从上游拉取更新${NC}"
    echo -e "${CYAN}  上游分支: $upstream_branch → 目标: $target_branch${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    # Fetch 上游
    echo -e "\n${YELLOW}↻ Fetch origin/$upstream_branch...${NC}"
    git fetch origin "$upstream_branch"

    # 保存当前分支
    local original_branch
    original_branch=$(git rev-parse --abbrev-ref HEAD)

    # 切换到目标分支
    if [ "$original_branch" != "$target_branch" ]; then
        echo -e "${YELLOW}↻ 切换到 $target_branch...${NC}"
        git checkout "$target_branch"
    fi

    # 对比差异
    local behind
    behind=$(git rev-list --count HEAD.."origin/$upstream_branch" 2>/dev/null || echo "0")
    if [ "$behind" -eq 0 ]; then
        echo -e "${GREEN}✓ 已是最新，无需同步${NC}"
    else
        echo -e "${YELLOW}📊 上游领先 $behind 个提交${NC}"
        echo ""
        echo "上游新增提交:"
        git log --oneline HEAD.."origin/$upstream_branch" | head -20
        echo ""

        read -r -p "是否合并这些变更到 $target_branch? [y/N] " confirm
        if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
            if git merge "origin/$upstream_branch" --no-edit; then
                echo -e "${GREEN}✓ 合并成功${NC}"
                echo ""
                read -r -p "是否推送到 GitHub? [y/N] " push_confirm
                if [ "$push_confirm" = "y" ] || [ "$push_confirm" = "Y" ]; then
                    git push github "$target_branch"
                    echo -e "${GREEN}✓ 已推送到 GitHub${NC}"
                fi
            else
                echo -e "${RED}✗ 合并冲突！请手动解决后执行:${NC}"
                echo "  git add ."
                echo "  git commit"
                echo "  git push github $target_branch"
            fi
        else
            echo -e "${YELLOW}已取消${NC}"
        fi
    fi

    # 切回原分支
    if [ "$original_branch" != "$target_branch" ] && [ "$original_branch" != "$(git rev-parse --abbrev-ref HEAD)" ]; then
        git checkout "$original_branch"
    fi
}

# ─── sync-setup-token: 配置 Gitcode Token ──────────────────────
sync-setup-token() {
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  配置 Gitcode Personal Access Token${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    echo ""
    echo "1. 打开 https://gitcode.com/-/user_settings/personal_access_tokens"
    echo "2. 点击 'Add new token'"
    echo "3. Token name: github-sync"
    echo "4. 勾选以下权限:"
    echo "   ☑ read_repository"
    echo "   ☑ write_repository"
    echo "5. 点击 'Create personal access token'"
    echo "6. 复制生成的 Token"
    echo ""

    read -r -s -p "粘贴 Gitcode Token (输入不可见): " token
    echo ""

    if [ -z "$token" ]; then
        echo -e "${RED}Token 不能为空${NC}"
        return 1
    fi

    # 更新 own remote 的 URL 以包含 token
    local current_url
    current_url=$(cd "$REPO_DIR" && git remote get-url own)
    local new_url="https://oauth2:${token}@gitcode.com/LinWei100/MindIE-PyMotor.git"

    cd "$REPO_DIR"
    git remote set-url own "$new_url"

    # 测试连接
    echo -e "${YELLOW}↻ 测试连接...${NC}"
    if git ls-remote own HEAD &>/dev/null; then
        echo -e "${GREEN}✓ Token 配置成功${NC}"
    else
        echo -e "${RED}✗ Token 验证失败，请检查${NC}"
        git remote set-url own "$current_url"
        return 1
    fi

    echo ""
    echo -e "${YELLOW}⚠  接下来还需要在 GitHub 仓库设置中添加 GITCODE_TOKEN secret:${NC}"
    echo "  https://github.com/Lyr-GW/MindIE-PyMotor/settings/secrets/actions"
    echo "  Name:  GITCODE_TOKEN"
    echo "  Value: $token"
}

# ─── sync-setup-github-token: 配置 GitHub Token ────────────────
sync-setup-github-token() {
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  配置 GitHub Personal Access Token${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    echo ""
    echo "1. 打开 https://github.com/settings/tokens"
    echo "2. 点击 'Generate new token' → 'Generate new token (classic)'"
    echo "3. Note: hermes-sync"
    echo "4. 勾选 repo (全部)"
    echo "5. 点击 'Generate token'"
    echo "6. 复制生成的 Token"
    echo ""

    read -r -s -p "粘贴 GitHub Token (输入不可见): " token
    echo ""

    if [ -z "$token" ]; then
        echo -e "${RED}Token 不能为空${NC}"
        return 1
    fi

    # 更新 github remote
    local new_url="https://oauth2:${token}@github.com/Lyr-GW/MindIE-PyMotor.git"

    cd "$REPO_DIR"
    git remote set-url github "$new_url"

    # 测试连接
    echo -e "${YELLOW}↻ 测试连接...${NC}"
    if git ls-remote github HEAD &>/dev/null; then
        echo -e "${GREEN}✓ Token 配置成功${NC}"
    else
        echo -e "${RED}✗ Token 验证失败${NC}"
        return 1
    fi
}

# ─── 帮助信息 ──────────────────────────────────────────────────
sync-help() {
    echo -e "${CYAN}GitCode 同步命令:${NC}"
    echo ""
    echo "  sync-status          查看所有远程同步状态"
    echo "  sync-push            推送当前分支到 Gitcode 个人仓 (own)"
    echo "  sync-push-github     推送当前分支到 GitHub"
    echo "  sync-pull-upstream   [上游分支] [目标分支]  从 Ascend 上游拉取更新"
    echo "  sync-setup-token     配置 Gitcode Personal Access Token"
    echo "  sync-setup-github-token  配置 GitHub Personal Access Token"
    echo "  sync-help            显示此帮助"
    echo ""
    echo -e "${YELLOW}使用前请执行: source scripts/sync-helpers.sh${NC}"
}

echo -e "${GREEN}GitCode 同步工具已加载。运行 sync-help 查看命令。${NC}"
