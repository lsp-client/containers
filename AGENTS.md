# AGENTS.md

## Container Runtime

- Use `docker` for building and running containers.

## SOP: Add LSP Image

1. Create `/<name>/ContainerFile`: Use `ARG VERSION`, multi-stage builds to minimize size, and `ENTRYPOINT ["...", "--stdio"]`.
2. Update `registry.toml`: Add `[name]` with `type` and `package`/`repo`.
3. Build: `docker build -f <name>/ContainerFile -t lsp-test .`
4. Test: `docker run --rm lsp-test --version`
5. Check Size: `docker images lsp-test --format "{{.Size}}"` (Ensure it is minimized and report the value).
