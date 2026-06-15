# Shell completion

`_net-auto-switch` is a zsh completion for the `net-auto-switch` command
(subcommands `init` / `update` / `whois` / `service` and their flags).

## Automatic (recommended)

`install.sh` registers it for you, idempotently — it adds a single marker-guarded
block to `~/.zshrc` that points at `$INSTALL_DIR/completions`. Re-running the
installer never duplicates the block, and `net-auto-switch update` refreshes the
completion in place (no re-registration needed). Just open a new shell or run
`exec zsh` after installing.

## Manual

If you cloned the repo or want to wire it up yourself, add to `~/.zshrc`:

```zsh
fpath=("/path/to/net-auto-switch/completions" $fpath)
autoload -Uz compinit && compinit
```

Then `exec zsh`. Type `net-auto-switch <Tab>` to see subcommands.

> bash/fish are not provided — the installer targets macOS, whose default shell
> is zsh.
