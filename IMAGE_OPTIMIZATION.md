# 容器镜像大小优化指南

本文档总结了在构建 LSP 服务器容器镜像时使用的各种镜像大小优化策略和技术。

## 目录

- [核心原则](#核心原则)
- [优化策略](#优化策略)
  - [1. 多阶段构建](#1-多阶段构建)
  - [2. 选择精简的基础镜像](#2-选择精简的基础镜像)
  - [3. 依赖项优化](#3-依赖项优化)
  - [4. 静态链接与独立二进制](#4-静态链接与独立二进制)
  - [5. 删除不必要的文件](#5-删除不必要的文件)
  - [6. 运行时优化](#6-运行时优化)
  - [7. 层缓存优化](#7-层缓存优化)
- [语言特定的优化技术](#语言特定的优化技术)
- [最佳实践](#最佳实践)
- [常见问题](#常见问题)

## 核心原则

容器镜像大小优化的核心目标是：

1. **最小化最终镜像大小** - 只包含运行时必需的文件
2. **减少层数和层大小** - 优化构建指令以减少镜像层
3. **提高传输效率** - 更小的镜像意味着更快的下载和部署
4. **提升安全性** - 更少的依赖和工具意味着更小的攻击面

## 优化策略

### 1. 多阶段构建

多阶段构建是最重要的优化技术，它允许我们将构建环境和运行环境分离。

#### 原理

- **构建阶段**：包含所有编译工具、依赖项和源代码
- **运行阶段**：仅包含运行时必需的二进制文件和依赖

#### 示例：Go 语言服务器 (gopls)

```dockerfile
# 构建阶段 - 包含完整的 Go 编译环境
FROM docker.io/library/golang:alpine AS builder
ARG VERSION
ENV CGO_ENABLED=0
RUN go install -ldflags="-s -w" golang.org/x/tools/gopls@${VERSION}

# 运行阶段 - 仅包含编译后的二进制文件
FROM gcr.io/distroless/static-debian12
ARG VERSION
LABEL org.opencontainers.image.version="${VERSION}"
COPY --from=builder /go/bin/gopls /usr/local/bin/gopls
WORKDIR /workspace
USER 65532:65532
ENTRYPOINT ["/usr/local/bin/gopls"]
```

**效果**：构建阶段可能有几百 MB，但最终镜像只有几十 MB。

### 2. 选择精简的基础镜像

选择合适的基础镜像对最终镜像大小有重大影响。

#### 基础镜像选择指南

| 基础镜像类型 | 大小 | 用途 | 优点 | 缺点 |
|------------|------|------|------|------|
| **distroless/static** | ~2MB | 静态链接的二进制文件 | 极小、安全 | 无 shell、无调试工具 |
| **distroless/cc** | ~20MB | 需要 libc 的二进制文件 | 很小、安全 | 无 shell、无调试工具 |
| **alpine** | ~5MB | 通用场景 | 小巧、有包管理器 | 使用 musl libc（可能有兼容性问题） |
| **debian:slim** | ~80MB | 需要更多系统工具 | 兼容性好 | 相对较大 |
| **ubuntu** | ~150MB+ | 需要完整系统 | 最佳兼容性 | 大 |

#### 示例对比

**Rust Analyzer (使用 distroless/cc)**
```dockerfile
FROM gcr.io/distroless/cc-debian12
COPY --from=builder /usr/local/bin/rust-analyzer /usr/local/bin/rust-analyzer
```
- 原因：rust-analyzer 需要 libc 动态链接

**Ruff (使用 distroless/static)**
```dockerfile
FROM gcr.io/distroless/static-debian12
COPY --from=builder /root/.local/share/uv/tools/ruff/bin/ruff /usr/local/bin/ruff
```
- 原因：ruff 是静态链接的二进制文件

**TypeScript LSP (使用 node:alpine)**
```dockerfile
FROM docker.io/library/node:22-alpine
COPY --from=builder /app/node_modules ./node_modules
```
- 原因：需要 Node.js 运行时环境

### 3. 依赖项优化

#### 3.1 Node.js 项目优化

Node.js 项目的 `node_modules` 目录通常非常大，需要特别优化。

**技术：node-prune**

```dockerfile
FROM docker.io/library/node:22-alpine AS builder
WORKDIR /app
RUN apk add --no-cache curl && \
    curl -sf https://gobinaries.com/tj/node-prune | sh && \
    npm install pyright@${VERSION} && \
    npm prune --production && \
    /usr/local/bin/node-prune
```

**优化效果**：
- `npm prune --production`：删除 devDependencies，通常减少 30-50%
- `node-prune`：删除不必要的文件（测试文件、文档等），额外减少 20-40%

#### 3.2 Python 项目优化

使用 `uv` 工具代替 `pip` 可以显著减小镜像大小。

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-alpine AS builder
RUN uv tool install ruff==${VERSION}

FROM gcr.io/distroless/static-debian12
COPY --from=builder /root/.local/share/uv/tools/ruff/bin/ruff /usr/local/bin/ruff
```

**优点**：
- `uv` 比 `pip` 更快
- 可以直接安装工具而不需要整个 Python 环境
- 支持静态二进制，可以使用 distroless

### 4. 静态链接与独立二进制

#### 4.1 Go 语言：完全静态链接

```dockerfile
ENV CGO_ENABLED=0
RUN go install -ldflags="-s -w" golang.org/x/tools/gopls@${VERSION}
```

**编译标志说明**：
- `CGO_ENABLED=0`：禁用 CGO，确保完全静态链接
- `-s`：去除符号表
- `-w`：去除 DWARF 调试信息

**效果**：生成完全独立的二进制，可以在 distroless/static 中运行。

#### 4.2 Rust：静态链接

Rust 默认生成静态链接的二进制文件（除非显式使用动态链接）。

```dockerfile
# 从 GitHub 下载预编译的静态二进制
RUN curl -L "https://github.com/rust-lang/rust-analyzer/releases/download/${VERSION}/${bin}" | \
    gunzip -c - > /usr/local/bin/rust-analyzer
```

### 5. 删除不必要的文件

#### 5.1 平台特定文件

**Java/Eclipse JDTLS 示例**：

```dockerfile
RUN rm -rf /opt/jdtls/config_mac /opt/jdtls/config_win /opt/jdtls/jdtls.bat && \
    find /opt/jdtls -name "*.md" -delete \
                    -o -name "README*" -delete \
                    -o -name "about.*" -delete \
                    -o -name "*.html" -delete \
                    -o -name "*.source_*.jar" -delete && \
    find /opt/jdtls -name "org.eclipse.equinox.launcher.cocoa.*" -delete && \
    find /opt/jdtls -name "org.eclipse.equinox.launcher.win32.*" -delete
```

**删除内容**：
- macOS 和 Windows 特定的配置和启动器
- 文档文件（.md, README, HTML）
- 源代码 JAR 包
- 不需要的平台特定组件

#### 5.2 文档和示例文件

在生产镜像中，这些文件通常不需要：
- README、LICENSE 等文档
- 示例代码和测试文件
- Markdown 文档
- 源代码（已编译的情况下）

### 6. 运行时优化

#### 6.1 Java：使用 jlink 创建自定义 JRE

标准 JDK/JRE 包含许多模块，但 LSP 服务器通常只需要其中一部分。

```dockerfile
RUN jlink \
    --add-modules java.base,java.compiler,java.desktop,java.instrument,java.logging,java.management,java.management.rmi,java.naming,java.net.http,java.prefs,java.rmi,java.scripting,java.security.jgss,java.security.sasl,java.sql,java.xml,jdk.unsupported,jdk.jfr \
    --strip-debug \
    --no-man-pages \
    --no-header-files \
    --compress=2 \
    --output /opt/jre
```

**jlink 选项说明**：
- `--add-modules`：仅包含需要的 Java 模块
- `--strip-debug`：去除调试信息
- `--no-man-pages`：不包含手册页
- `--no-header-files`：不包含头文件
- `--compress=2`：使用最高压缩级别

**效果**：完整 JDK 可能有 300-400MB，自定义 JRE 可以减少到 50-100MB。

#### 6.2 使用非 root 用户

虽然不直接减小镜像大小，但这是安全最佳实践：

```dockerfile
USER 65532:65532  # distroless 的 nonroot 用户
# 或
USER node         # Node.js 镜像的预定义用户
```

### 7. 层缓存优化

#### 7.1 合并 RUN 命令

将相关的命令合并到一个 RUN 语句中：

```dockerfile
# 不推荐 - 创建多个层
RUN apk add --no-cache curl
RUN apk add --no-cache tar
RUN apk add --no-cache binutils

# 推荐 - 单个层，并在同一层清理
RUN apk add --no-cache curl tar binutils && \
    # ... 使用工具 ... && \
    rm -rf /var/cache/apk/*
```

#### 7.2 在同一层清理

```dockerfile
RUN apt-get update && \
    apt-get install -y curl && \
    # ... 下载和安装 ... && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
```

**重要**：如果在不同的 RUN 命令中清理，之前层的大小不会减少。

## 语言特定的优化技术

### Node.js / TypeScript

| 技术 | 实现 | 减少大小 |
|------|------|---------|
| 使用 alpine 基础镜像 | `node:22-alpine` | ~50% |
| npm prune --production | 删除 devDependencies | 30-50% |
| node-prune | 删除不必要文件 | 20-40% |
| 仅复制 node_modules | 不复制源代码 | - |

### Python

| 技术 | 实现 | 减少大小 |
|------|------|---------|
| 使用 uv 代替 pip | `uv tool install` | ~30% |
| 使用 alpine 基础镜像 | `python:3.12-alpine` | ~50% |
| 编译为静态二进制 | PyInstaller、Nuitka | 可使用 distroless |
| 删除 .pyc 和 __pycache__ | `PYTHONDONTWRITEBYTECODE=1` | 5-10% |

### Go

| 技术 | 实现 | 减少大小 |
|------|------|---------|
| 静态链接 | `CGO_ENABLED=0` | 可使用 distroless |
| 去除符号 | `-ldflags="-s -w"` | 30-40% |
| 使用 distroless/static | 最小运行时 | ~95% (vs 完整镜像) |

### Rust

| 技术 | 实现 | 减少大小 |
|------|------|---------|
| 使用预编译二进制 | 从 GitHub releases 下载 | 避免构建依赖 |
| 使用 distroless/cc | 最小运行时 | ~95% |
| strip 二进制 | `strip` 命令 | 30-40% |

### Java

| 技术 | 实现 | 减少大小 |
|------|------|---------|
| jlink 自定义 JRE | 仅包含需要的模块 | 60-70% |
| 删除平台特定文件 | 删除 Windows/Mac 文件 | 10-20% |
| 删除源码 JAR | 删除 *.source_*.jar | 5-10% |
| 使用 Alpine | `amazoncorretto:21-alpine` | ~30% |

## 最佳实践

### 1. 构建顺序

优化的 Dockerfile 通常遵循这个顺序：

```dockerfile
# 1. 定义版本参数
ARG VERSION=x.y.z

# 2. 构建阶段 - 使用功能完整的基础镜像
FROM builder-image AS builder
ARG VERSION

# 3. 安装构建依赖（如果需要）
RUN install-build-deps

# 4. 构建/下载应用
RUN build-or-download-app

# 5. 优化依赖（如果适用）
RUN npm prune --production && node-prune

# 6. 删除不必要的文件
RUN remove-unnecessary-files

# 7. 运行阶段 - 使用最小的基础镜像
FROM minimal-runtime-image
ARG VERSION

# 8. 添加元数据
LABEL org.opencontainers.image.version="${VERSION}"

# 9. 仅复制必要的文件
COPY --from=builder /path/to/binary /path/to/binary

# 10. 设置工作目录和用户
WORKDIR /workspace
USER nonroot

# 11. 定义入口点
ENTRYPOINT ["/path/to/binary"]
```

### 2. 使用 .dockerignore

创建 `.dockerignore` 文件以排除不必要的文件：

```
.git
.github
*.md
docs/
tests/
*.pyc
__pycache__/
node_modules/
```

### 3. 选择合适的压缩

对于需要下载的文件，使用合适的解压方式：

```dockerfile
# 直接解压到标准输出，避免中间文件
RUN curl -L "https://example.com/file.tar.gz" | tar -xz -C /dest
```

### 4. 架构感知的构建

为不同架构构建时，确保下载正确的二进制：

```dockerfile
RUN arch=$(uname -m); \
    case "$arch" in \
        x86_64) bin="app-x86_64.gz" ;; \
        aarch64) bin="app-aarch64.gz" ;; \
        *) echo "Unsupported arch"; exit 1 ;; \
    esac; \
    curl -L "https://example.com/${bin}" | gunzip > /usr/local/bin/app
```

### 5. 版本固定

始终固定版本以确保可重现的构建：

```dockerfile
ARG VERSION=1.2.3
FROM node:22-alpine  # 使用主版本号
RUN npm install package@${VERSION}  # 使用精确版本
```

## 常见问题

### Q: 何时使用 alpine vs distroless？

**A:** 
- **使用 alpine**：当你需要 shell、包管理器或需要在运行时安装额外工具
- **使用 distroless**：当你有独立的二进制文件且不需要调试工具（最安全、最小）

### Q: 多阶段构建会增加构建时间吗？

**A:** 可能会略微增加，但好处远大于成本：
- 最终镜像更小，传输更快
- 更好的层缓存
- 更安全（更小的攻击面）
- 构建时间的增加通常可以通过更好的层缓存来抵消

### Q: 如何调试 distroless 镜像？

**A:** Distroless 镜像没有 shell，但你可以：
1. 在开发时使用 alpine 基础镜像
2. 使用 distroless 的调试版本（例如 `gcr.io/distroless/static-debian12:debug`）
3. 使用 `docker cp` 从容器中复制文件
4. 使用 Kubernetes 的 ephemeral containers

### Q: node-prune 安全吗？

**A:** 是的，node-prune 只删除明确不需要的文件（markdown、示例、测试等），不会删除运行时代码。但应该在构建后测试以确保功能正常。

### Q: 为什么要合并 RUN 命令？

**A:** Docker 的每个命令都会创建一个新层。即使后续命令删除文件，之前层的大小也不会减少。合并命令可以确保临时文件不会留在最终镜像中。

```dockerfile
# 错误 - 临时文件留在第一层
RUN wget https://example.com/big-file.tar.gz
RUN tar -xzf big-file.tar.gz
RUN rm big-file.tar.gz  # 不会减少镜像大小！

# 正确 - 临时文件不会保留
RUN wget https://example.com/big-file.tar.gz && \
    tar -xzf big-file.tar.gz && \
    rm big-file.tar.gz
```

### Q: 如何确定应该包含哪些 Java 模块？

**A:** 
1. 从所有必需模块开始（java.base 始终需要）
2. 运行应用并查看错误
3. 根据错误添加缺失的模块
4. 或使用 `jdeps` 工具分析依赖：`jdeps --print-module-deps myapp.jar`

## 总结

镜像大小优化是一个平衡的艺术：

- **安全性**：更小的镜像 = 更小的攻击面
- **性能**：更小的镜像 = 更快的下载和启动
- **可维护性**：过度优化可能导致难以调试

对于 LSP 服务器容器，我们的目标是：
1. 使用多阶段构建分离构建和运行环境
2. 选择最小的合适基础镜像（优先 distroless，其次 alpine）
3. 仅包含运行时必需的文件
4. 删除所有平台特定和文档文件
5. 使用语言特定的优化技术

通过应用这些策略，我们通常可以将镜像大小从几百 MB 减少到几十 MB，同时保持功能完整性和安全性。
