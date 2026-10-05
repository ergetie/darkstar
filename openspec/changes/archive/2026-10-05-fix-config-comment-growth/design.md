## Context

`template_aware_merge(default_cfg, user_cfg)` builds the saved config by starting from a freshly loaded template (structure + comments) and writing user values into it. Both trees are loaded with ruamel round-trip `YAML()`, so the user's `CommentedMap`/`CommentedSeq` nodes carry comment tokens. For list keys outside `ARRAY_UNIQUE_KEYS`, `target[key] = value` binds the user's list, comments included, into the template tree. The template's own comment token for that key stays on the parent, so the dump writes both copies. On the next load, the doubled block parses into the user's list, and the cycle repeats.

Verified on `main` (ruamel 0.19.1): with the real template, only `executor.excess_pv.priority` triggers it today, at +842 B per write. The issue's minimal snippet does not reproduce.

## Goals / Non-Goals

**Goals:**
- Repeated writes produce byte-stable output.
- Fix the whole class, not one key, in one place that covers both write paths.
- Existing bloated files self-heal on the next write.

**Non-Goals:**
- Preserving comments that users add to `config.yaml` by hand.
- Changing how the YAML files are loaded, or changing `ARRAY_UNIQUE_KEYS` merge semantics.

## Decisions

**Convert the user tree to plain data at the start of `template_aware_merge`.** A small recursive helper rebuilds mappings as `dict` and sequences as `list`, and returns scalars unchanged. The merge then runs on that copy.
- Scalars are kept as-is, so ruamel's quoted-string scalar types still preserve quote style.
- It doesn't mutate the caller's tree, and it doesn't touch ruamel internals.
- Alternative: strip `.ca` comment attachments in place (the issue's option 2). Rejected because it depends on ruamel's private comment structures and mutates the caller's data.
- Alternative: load the user config with `YAML(typ="safe")` (option 1). Rejected because the save and migrate paths also reuse the round-trip-loaded user tree for pre-merge writes and comparisons, so that's a wider change with more risk.
- Alternative: add `priority` to `ARRAY_UNIQUE_KEYS` (option 3). Rejected because it only fixes one key and is semantically wrong for that key.

## Risks / Trade-offs

- [Hand-written user comments are dropped on write] → This is already effectively the case, since the output is always rebuilt from the template. The spec documents it.
- [A plain `dict` or `list` inserted into a ruamel tree dumps in a different style] → ruamel dumps plain containers in block style using the configured indent. The regression test checks a stable round trip against the real template.
- [The first write after deploy rewrites bloated files] → That's intended: the file shrinks to normal size. Timestamped backups already exist.
