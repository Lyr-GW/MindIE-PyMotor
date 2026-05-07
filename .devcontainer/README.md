# DevContainer 分步指南

本指南旨在解决"在我的机器上快速搭建构建环境，并正常运行"问题，帮助你实现一个隔离且可复现的开发环境。下面，我们将按步骤完成该开发容器的搭建。

## 步骤1：安装必须的软件与相关插件

- [Docker Desktop](https://www.docker.com/products/docker-desktop)
- [Visual Studio Code](https://code.visualstudio.com/)
- [Visual Studio 扩展插件Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)

## 启动

1. 克隆代码仓

    ```bash
    git clone MindIE-PyMotor代码仓地址
    cd MindIE-PyMotor
    ```

2. 用VS Code打开项目

    ```Shell
    code .
    ```

3. 按 `F1` 或 `Ctrl + Shift + P`， 输入 `Dev Containers: Reopen in Container`

4. 选择配置方式

5. 容器启动，等待启动完成

## 开发

容器启动后会自动安装 `requirements.txt` 中的依赖并以 editable 模式安装 `motor` 包。

### 生成 protobuf 文件

```bash
./scripts/generate_proto.sh
```

### 构建 wheel 包

```bash
./build.sh
```

### 运行测试

```bash
pytest
```
