## What does this change?

<!-- One sentence describing what this PR does -->

## Type of change

- [ ] Bug fix (corrects existing behavior)
- [ ] New skill (adds a new skill to the collection)
- [ ] Skill improvement (enhances an existing skill)
- [ ] New plugin (adds a new plugin to `plugins/`)
- [ ] Plugin improvement (enhances an existing plugin)
- [ ] Documentation (updates docs, README, CONTRIBUTING)
- [ ] Infrastructure (CI, scripts, templates)

## Checklist

### Skills
- [ ] `SKILL.md` has valid frontmatter (`name`, `description`, `metadata.version`)
- [ ] Ran `scripts/validate-skill.sh` locally and it passes

### Plugins (if applicable)
- [ ] `.claude-plugin/plugin.json` has required fields (`name`, `version`, `description`)
- [ ] Ran `scripts/validate-plugin.sh` locally and it passes
- [ ] All bundled skills pass `validate-skill.sh`
- [ ] All bundled commands have YAML frontmatter with `description`

### General
- [ ] Changes are focused (one logical change per PR)
- [ ] No secrets or credentials included
