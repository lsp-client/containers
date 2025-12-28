# Container Image Size Optimization Guide

This document summarizes various image size optimization strategies and techniques used when building LSP server container images.

## Table of Contents

- [Core Principles](#core-principles)
- [Optimization Strategies](#optimization-strategies)
  - [1. Multi-Stage Builds](#1-multi-stage-builds)
  - [2. Choosing Minimal Base Images](#2-choosing-minimal-base-images)
  - [3. Dependency Optimization](#3-dependency-optimization)
  - [4. Static Linking and Standalone Binaries](#4-static-linking-and-standalone-binaries)
  - [5. Removing Unnecessary Files](#5-removing-unnecessary-files)
  - [6. Runtime Optimization](#6-runtime-optimization)
  - [7. Layer Caching Optimization](#7-layer-caching-optimization)
- [Language-Specific Optimization Techniques](#language-specific-optimization-techniques)
- [Best Practices](#best-practices)
- [Common Questions](#common-questions)

## Core Principles

The core goals of container image size optimization are:

1. **Minimize Final Image Size** - Include only files necessary for runtime
2. **Reduce Layer Count and Size** - Optimize build instructions to reduce image layers
3. **Improve Transfer Efficiency** - Smaller images mean faster downloads and deployments
4. **Enhance Security** - Fewer dependencies and tools mean a smaller attack surface

## Optimization Strategies

### 1. Multi-Stage Builds

Multi-stage builds are the most important optimization technique, allowing us to separate build and runtime environments.

#### Principle

- **Build Stage**: Contains all compilation tools, dependencies, and source code
- **Runtime Stage**: Contains only the binaries and dependencies required at runtime

#### Example: Go Language Server (gopls)

```dockerfile
# Build stage - includes complete Go compilation environment
FROM docker.io/library/golang:alpine AS builder
ARG VERSION
ENV CGO_ENABLED=0
RUN go install -ldflags="-s -w" golang.org/x/tools/gopls@${VERSION}

# Runtime stage - contains only compiled binary
FROM gcr.io/distroless/static-debian12
ARG VERSION
LABEL org.opencontainers.image.version="${VERSION}"
COPY --from=builder /go/bin/gopls /usr/local/bin/gopls
WORKDIR /workspace
USER 65532:65532
ENTRYPOINT ["/usr/local/bin/gopls"]
```

**Effect**: The build stage may be several hundred MB, but the final image is only a few dozen MB.

### 2. Choosing Minimal Base Images

Choosing the right base image has a significant impact on the final image size.

#### Base Image Selection Guide

| Base Image Type | Size | Use Case | Advantages | Disadvantages |
|----------------|------|----------|-----------|---------------|
| **distroless/static** | ~2MB | Statically linked binaries | Extremely small, secure | No shell, no debug tools |
| **distroless/cc** | ~20MB | Binaries requiring libc | Very small, secure | No shell, no debug tools |
| **alpine** | ~5MB | General purpose | Compact, has package manager | Uses musl libc (potential compatibility issues) |
| **debian:slim** | ~80MB | Requires more system tools | Good compatibility | Relatively large |
| **ubuntu** | ~150MB+ | Requires complete system | Best compatibility | Large |

#### Comparison Examples

**Rust Analyzer (using distroless/cc)**
```dockerfile
FROM gcr.io/distroless/cc-debian12
COPY --from=builder /usr/local/bin/rust-analyzer /usr/local/bin/rust-analyzer
```
- Reason: rust-analyzer requires dynamic linking with libc

**Ruff (using distroless/static)**
```dockerfile
FROM gcr.io/distroless/static-debian12
COPY --from=builder /root/.local/share/uv/tools/ruff/bin/ruff /usr/local/bin/ruff
```
- Reason: ruff is a statically linked binary

**TypeScript LSP (using node:alpine)**
```dockerfile
FROM docker.io/library/node:22-alpine
COPY --from=builder /app/node_modules ./node_modules
```
- Reason: Requires Node.js runtime environment

### 3. Dependency Optimization

#### 3.1 Node.js Project Optimization

Node.js projects' `node_modules` directories are typically very large and require special optimization.

**Technique: node-prune**

```dockerfile
FROM docker.io/library/node:22-alpine AS builder
WORKDIR /app
RUN apk add --no-cache curl && \
    curl -sf https://gobinaries.com/tj/node-prune | sh && \
    npm install pyright@${VERSION} && \
    npm prune --production && \
    /usr/local/bin/node-prune
```

**Optimization Results**:
- `npm prune --production`: Removes devDependencies, typically reduces 30-50%
- `node-prune`: Removes unnecessary files (test files, documentation, etc.), additional 20-40% reduction

#### 3.2 Python Project Optimization

Using the `uv` tool instead of `pip` can significantly reduce image size.

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.12-alpine AS builder
RUN uv tool install ruff==${VERSION}

FROM gcr.io/distroless/static-debian12
COPY --from=builder /root/.local/share/uv/tools/ruff/bin/ruff /usr/local/bin/ruff
```

**Advantages**:
- `uv` is faster than `pip`
- Can directly install tools without requiring the entire Python environment
- Supports static binaries, can use distroless

### 4. Static Linking and Standalone Binaries

#### 4.1 Go Language: Complete Static Linking

```dockerfile
ENV CGO_ENABLED=0
RUN go install -ldflags="-s -w" golang.org/x/tools/gopls@${VERSION}
```

**Compilation Flag Explanations**:
- `CGO_ENABLED=0`: Disables CGO, ensures complete static linking
- `-s`: Strips symbol table
- `-w`: Strips DWARF debugging information

**Effect**: Generates a completely standalone binary that can run in distroless/static.

#### 4.2 Rust: Static Linking

Rust generates statically linked binaries by default (unless explicitly using dynamic linking).

```dockerfile
# Download pre-compiled static binary from GitHub
RUN curl -L "https://github.com/rust-lang/rust-analyzer/releases/download/${VERSION}/${bin}" | \
    gunzip -c - > /usr/local/bin/rust-analyzer
```

### 5. Removing Unnecessary Files

#### 5.1 Platform-Specific Files

**Java/Eclipse JDTLS Example**:

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

**Removed Content**:
- macOS and Windows specific configurations and launchers
- Documentation files (.md, README, HTML)
- Source code JAR packages
- Unnecessary platform-specific components

#### 5.2 Documentation and Example Files

In production images, these files are typically not needed:
- README, LICENSE, and other documentation
- Example code and test files
- Markdown documentation
- Source code (when already compiled)

### 6. Runtime Optimization

#### 6.1 Java: Creating Custom JRE with jlink

Standard JDK/JRE contains many modules, but LSP servers typically only need a subset.

```dockerfile
RUN jlink \
    --add-modules java.base,java.compiler,java.desktop,java.instrument,java.logging,java.management,java.management.rmi,java.naming,java.net.http,java.prefs,java.rmi,java.scripting,java.security.jgss,java.security.sasl,java.sql,java.xml,jdk.unsupported,jdk.jfr \
    --strip-debug \
    --no-man-pages \
    --no-header-files \
    --compress=2 \
    --output /opt/jre
```

**jlink Option Explanations**:
- `--add-modules`: Include only needed Java modules
- `--strip-debug`: Remove debugging information
- `--no-man-pages`: Exclude manual pages
- `--no-header-files`: Exclude header files
- `--compress=2`: Use highest compression level

**Effect**: A complete JDK may be 300-400MB, a custom JRE can be reduced to 50-100MB.

#### 6.2 Using Non-Root Users

While not directly reducing image size, this is a security best practice:

```dockerfile
USER 65532:65532  # distroless nonroot user
# or
USER node         # Pre-defined user in Node.js images
```

### 7. Layer Caching Optimization

#### 7.1 Merging RUN Commands

Merge related commands into a single RUN statement:

```dockerfile
# Not recommended - creates multiple layers
RUN apk add --no-cache curl
RUN apk add --no-cache tar
RUN apk add --no-cache binutils

# Recommended - single layer with cleanup in same layer
RUN apk add --no-cache curl tar binutils && \
    # ... use tools ... && \
    rm -rf /var/cache/apk/*
```

#### 7.2 Cleanup in Same Layer

```dockerfile
RUN apt-get update && \
    apt-get install -y curl && \
    # ... download and install ... && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
```

**Important**: If cleanup is done in a different RUN command, the previous layer's size will not be reduced. This is because Docker layers are immutable - once a layer is created with files, those files remain in that layer permanently, even if deleted in a subsequent layer.

## Language-Specific Optimization Techniques

### Node.js / TypeScript

| Technique | Implementation | Size Reduction |
|-----------|----------------|----------------|
| Use alpine base image | `node:22-alpine` | ~50% |
| npm prune --production | Remove devDependencies | 30-50% |
| node-prune | Remove unnecessary files | 20-40% |
| Copy node_modules only | Don't copy source code | - |

### Python

| Technique | Implementation | Size Reduction |
|-----------|----------------|----------------|
| Use uv instead of pip | `uv tool install` | ~30% |
| Use alpine base image | `python:3.12-alpine` | ~50% |
| Compile to static binary | PyInstaller, Nuitka | Can use distroless |
| Remove .pyc and __pycache__ | `PYTHONDONTWRITEBYTECODE=1` | 5-10% |

### Go

| Technique | Implementation | Size Reduction |
|-----------|----------------|----------------|
| Static linking | `CGO_ENABLED=0` | Can use distroless |
| Strip symbols | `-ldflags="-s -w"` | 30-40% |
| Use distroless/static | Minimal runtime | ~95% (vs full image) |

### Rust

| Technique | Implementation | Size Reduction |
|-----------|----------------|----------------|
| Use pre-compiled binaries | Download from GitHub releases | Avoid build dependencies |
| Use distroless/cc | Minimal runtime | ~95% (vs full image) |
| Strip binary | `strip` command | 30-40% |

### Java

| Technique | Implementation | Size Reduction |
|-----------|----------------|----------------|
| jlink custom JRE | Include only needed modules | 60-70% |
| Remove platform-specific files | Remove Windows/Mac files | 10-20% |
| Remove source JARs | Remove *.source_*.jar | 5-10% |
| Use Alpine | `amazoncorretto:21-alpine` | ~30% |

## Best Practices

### 1. Build Order

An optimized Dockerfile typically follows this order:

```dockerfile
# 1. Define version argument
ARG VERSION=x.y.z

# 2. Build stage - use full-featured base image
FROM builder-image AS builder
ARG VERSION

# 3. Install build dependencies (if needed)
RUN install-build-deps

# 4. Build/download application
RUN build-or-download-app

# 5. Optimize dependencies (if applicable)
RUN npm prune --production && node-prune

# 6. Remove unnecessary files
RUN remove-unnecessary-files

# 7. Runtime stage - use minimal base image
FROM minimal-runtime-image
ARG VERSION

# 8. Add metadata
LABEL org.opencontainers.image.version="${VERSION}"

# 9. Copy only necessary files
COPY --from=builder /path/to/binary /path/to/binary

# 10. Set working directory and user
WORKDIR /workspace
USER nonroot

# 11. Define entry point
ENTRYPOINT ["/path/to/binary"]
```

### 2. Using .dockerignore

Create a `.dockerignore` file to exclude unnecessary files:

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

### 3. Choosing Appropriate Compression

For files that need to be downloaded, use appropriate decompression methods:

```dockerfile
# Decompress directly to stdout, avoiding intermediate files
RUN curl -L "https://example.com/file.tar.gz" | tar -xz -C /dest
```

### 4. Architecture-Aware Builds

When building for different architectures, ensure the correct binary is downloaded:

```dockerfile
RUN arch=$(uname -m); \
    case "$arch" in \
        x86_64) bin="app-x86_64.gz" ;; \
        aarch64) bin="app-aarch64.gz" ;; \
        *) echo "Unsupported arch"; exit 1 ;; \
    esac; \
    curl -L "https://example.com/${bin}" | gunzip > /usr/local/bin/app
```

### 5. Version Pinning

Always pin versions to ensure reproducible builds:

```dockerfile
ARG VERSION=1.2.3
FROM node:22-alpine  # Use major version
RUN npm install package@${VERSION}  # Use exact version
```

## Common Questions

### Q: When to use alpine vs distroless?

**A:** 
- **Use alpine**: When you need a shell, package manager, or need to install additional tools at runtime
- **Use distroless**: When you have a standalone binary and don't need debugging tools (most secure, smallest)

### Q: Do multi-stage builds increase build time?

**A:** May increase slightly, but the benefits far outweigh the costs:
- Smaller final image, faster transfer
- Better layer caching
- More secure (smaller attack surface)
- The increase in build time can usually be offset by better layer caching

### Q: How to debug distroless images?

**A:** Distroless images have no shell, but you can:
1. Use alpine base images during development
2. Use distroless debug versions (e.g., `gcr.io/distroless/static-debian12:debug`)
3. Use `docker cp` to copy files from the container
4. Use Kubernetes ephemeral containers

### Q: Is node-prune safe?

**A:** Yes, node-prune only removes clearly unnecessary files (markdown, examples, tests, etc.), and does not delete runtime code. However, you should test after building to ensure functionality is intact.

### Q: Why merge RUN commands?

**A:** Each Docker command creates a new layer. Even if subsequent commands delete files, the size of previous layers will not decrease. Merging commands ensures temporary files are not left in the final image.

```dockerfile
# Wrong - temporary files remain in first layer
RUN wget https://example.com/big-file.tar.gz
RUN tar -xzf big-file.tar.gz
RUN rm big-file.tar.gz  # Won't reduce image size!

# Correct - temporary files are not retained
RUN wget https://example.com/big-file.tar.gz && \
    tar -xzf big-file.tar.gz && \
    rm big-file.tar.gz
```

### Q: How to determine which Java modules to include?

**A:** 
1. Start with all required modules (java.base is always needed)
2. Run the application and check for errors
3. Add missing modules based on errors
4. Or use the `jdeps` tool to analyze dependencies: `jdeps --print-module-deps myapp.jar`

## Summary

Image size optimization is a balancing act:

- **Security**: Smaller images = smaller attack surface
- **Performance**: Smaller images = faster downloads and startup
- **Maintainability**: Over-optimization can make debugging difficult

For LSP server containers, our goals are:
1. Use multi-stage builds to separate build and runtime environments
2. Choose the smallest appropriate base image (prefer distroless, then alpine)
3. Include only runtime-required files
4. Remove all platform-specific and documentation files
5. Use language-specific optimization techniques

By applying these strategies, we can typically reduce image sizes from hundreds of MB to tens of MB while maintaining functionality and security.
