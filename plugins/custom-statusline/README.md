# custom-statusline

An adaptive Claude Code statusline that shows project, git, and context info with icons — and dynamically adjusts between 1, 2, or 3 lines based on your terminal width and branch name length.

## Preview

### Wide terminal (Mac/iPad — single line)

```
Opus 4.6 | 📁 my-project | 🌿 develop(⇡⇣) | 🧠 ●●●●●●●●●○○○○○○○○○○○○○○○○ 36%
```

### Narrow terminal (phone SSH — two lines)

```
Opus 4.6 | 📁 my-project
🌿 feature/auth(~2|⇡1) | 🧠 ●●●●●●○○○○○○○○○ 42%
```

### Long branch name (auto 3-line layout)

```
Opus 4.6 | 📁 tiny-vacation-agent
🌿 feature/story-11.13-prompt-dedup-restructure(~5|?)
🧠 ●●●●●●●●○○○○○○○○○○○○ 42.5%
```

### Ultra-narrow (<40 cols)

```
Opus 4.6
🌿 develop(⇡⇣)
🧠 ●●●●○○○○ 38%
```

The layout switches **automatically** based on whether the content fits. Long branch names that would lose >1/3 of their text get their own line. No configuration needed.

## What It Shows

### 📁 Project Directory

The basename of your current working directory.

### 🌿 Git Branch + Sync Status

Branch name with compact remote sync indicator in parentheses:

| Symbol | Color | Meaning |
|--------|-------|---------|
| `⇡⇣` | cyan | In sync with remote |
| `⇡3` | green | 3 commits ahead (unpushed) |
| `⇣2` | yellow | 2 commits behind (need to pull) |
| `⇡2⇣1` | red | Diverged from remote |
| `?` | dim | No remote tracking branch |

Dirty working tree is shown with `~N` before the pipe: `develop(~3\|⇡⇣)`

### 🧠 Context Window Usage

Color-coded progress bar with percentage:

| Range | Color | Bar |
|-------|-------|-----|
| 0-49% | green | `●●●●●○○○○○○○○○○○○○○○` |
| 50-79% | yellow | `●●●●●●●●●●●●○○○○○○○○` |
| 80-100% | red | `●●●●●●●●●●●●●●●●●●○○` |

## How Width Detection Works

Claude Code runs statusline scripts in a pipe context where standard terminal detection (`/dev/tty`, `$COLUMNS`) fails. This plugin uses a 3-tier detection strategy:

1. **tmux** (highest priority) — `tmux display-message -p '#{window_width}'` returns the actual pane width, which updates when you switch between devices (phone, iPad, Mac)
2. **Parent TTY** — finds the Claude Code process's TTY via `ps -o tty= -p $PPID` and queries it with `stty size`
3. **Fallback** — defaults to 40 columns (safe for mobile)

This means the statusline adapts in real-time when you attach to a tmux session from different devices.

## Installation

### Via Claude Code (Recommended)

```shell
# Add the marketplace (one-time setup)
/plugin marketplace add abhattacherjee/claude-code-skills

# Install this plugin
/plugin install custom-statusline@claude-code-skills
```

### Via Script

```bash
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh /tmp/ccs/plugins/custom-statusline
rm -rf /tmp/ccs
```

### Manual

```bash
cp -r plugins/custom-statusline/skills/* ~/.claude/skills/
```

Then run `/install-statusline` in Claude Code, or manually:

```bash
bash ~/.claude/skills/install-statusline/scripts/install.sh
```

The install script copies the statusline script to `~/.claude/statusline-command.sh` and adds the `statusLine` entry to `~/.claude/settings.json`.

## Customization

After installing, use `/statusline` in Claude Code to make changes. The `statusline-setup` agent understands the script structure and can modify icons, colors, bar style, layout breakpoints, and more.

## Uninstall

```bash
# Via Claude Code
/plugin uninstall custom-statusline@claude-code-skills

# Via script
git clone https://github.com/abhattacherjee/claude-code-skills.git /tmp/ccs
/tmp/ccs/scripts/install-plugin.sh --uninstall /tmp/ccs/plugins/custom-statusline
rm -rf /tmp/ccs
```

## Contents

- **1** skill (`install-statusline`), **0** commands

## License

[MIT](LICENSE)
