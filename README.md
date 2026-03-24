# TD4LLMs

Export your TouchDesigner network to JSON so LLMs can understand your project.

TD4LLMs serializes your TD network -- operators, parameters, connections, and hierarchy -- into a compact format designed for LLM context windows. Feed it to Claude, ChatGPT, or any LLM to get help debugging, documenting, or extending your TouchDesigner projects.

## Why?

TouchDesigner's `.toe` files are binary -- LLMs can't read them. TD4LLMs bridges that gap by exporting a human-readable representation of your network. Only non-default parameters are included, and system/UI boilerplate is excluded by default, so the output is small enough to paste directly into an LLM conversation.

## Quick Start

1. Copy `export_network.py` into your TouchDesigner project (e.g., as a Text DAT)
2. Run it from a Text DAT or the Textport:

```python
exec(op('export_network').text)
```

3. Find `network_export.json` (or `.jsonl`) in your project folder
4. Paste the output into your LLM conversation for context

## What Gets Exported

- **Operator tree** -- full hierarchy with paths, types, and families
- **Parameters** -- only non-default values (parameters you actually changed)
- **Relationship graph** -- all connections as a top-level adjacency list with typed edges (input/bind/export)
- **Templates** -- repeated operator configurations are defined once and referenced, reducing duplication
- **Metadata** -- operator counts, subsystem breakdown, cross-subsystem connections

### What Gets Excluded (by default)

TD projects contain thousands of system and UI operators (`/sys`, `/ui`) that are identical across all projects. These are excluded by default since they're noise for LLM context. On a real project this typically removes 95-98% of operators. Set `EXCLUDE_SYSTEM = False` to include them.

## Output Structure

```json
{
  "_meta": {
    "total_ops": 437,
    "connections": 215,
    "system_excluded": ["/sys", "/ui"],
    "subsystems": {
      "/project1": {"ops": 381, "types": {"TOP": 45, "CHOP": 12, ...}}
    }
  },
  "graph": [
    ["input", "/project1/noise1", "/project1/comp1", 0],
    ["bind", "op('ctrl')['opacity']", "/project1/render1:opacity"],
    ["export", "/project1/chop1", "/project1/geo1:ty"]
  ],
  "templates": {
    "t0": {"type": "null", "family": "TOP"},
    "t1": {"type": "moviefilein", "family": "TOP"}
  },
  "operators": {
    "path": "/",
    "type": "root",
    "family": "COMP",
    "children": [...]
  }
}
```

### Sections

| Section | What it contains |
|---------|-----------------|
| `_meta` | Network statistics, subsystem breakdown, cross-subsystem connections |
| `graph` | All connections as typed edges: `input` (data flow), `bind` (param references), `export` (CHOP/DAT exports) |
| `templates` | Deduplicated operator configurations -- each unique (type, family, param-set) defined once |
| `operators` | The operator tree, with templateable operators referencing their template ID |

### Relationship Graph

Connections are extracted into a top-level `graph` array instead of being buried in per-operator fields. This lets an LLM see the full network topology at a glance.

Three edge types:
- `["input", src_path, dst_path, slot]` -- data flow (operator wiring)
- `["bind", bind_expr, dst_path:param]` -- parameter binds
- `["export", src_path, dst_path:param]` -- CHOP/DAT export connections

### Template Deduplication

Operators with identical signatures (same type, family, and set of non-default param names) share a template. The template is defined once; each instance references it with per-instance param values as overrides.

```json
{
  "templates": {
    "t0": {"type": "moviefilein", "family": "TOP"}
  },
  "operators": {
    "path": "/project1",
    "children": [
      {"path": "/project1/mov1", "template": "t0", "overrides": {"file": "/video1.mov"}},
      {"path": "/project1/mov2", "template": "t0", "overrides": {"file": "/video2.mov"}}
    ]
  }
}
```

## Output Modes

Control how much detail is exported with `OUTPUT_MODE` at the top of the script:

| Mode | What's included | Best for |
|------|----------------|----------|
| `compact` (default) | Non-default params as bare values | Day-to-day LLM use |
| `summary` | Operator tree + connections only, no params | Architecture overview |
| `full` | Non-default params with metadata (style, mode) | Debugging parameter issues |

### Compact mode example

```json
{
  "path": "/project1/render1",
  "type": "glslmulti",
  "family": "TOP",
  "params": {"resolutionw": 1920, "resolutionh": 1080, "outputresolution": 9}
}
```

Parameters you never touched are omitted. Expressions, binds, and exports are preserved:

```json
{
  "params": {
    "tx": {"expr": "absTime.seconds * 0.1"},
    "opacity": {"bind": "op('ctrl')['opacity']"},
    "file": "/path/to/video.mov"
  }
}
```

### Summary mode example

```json
{"path": "/project1/render1", "type": "glslmulti", "family": "TOP"}
```

No parameters at all -- just the network graph.

## Output Formats

Set `OUTPUT_FORMAT` at the top of the script:

| Format | Description | Output file |
|--------|------------|-------------|
| `json` (default) | Structured JSON with meta, graph, templates, and operator tree | `network_export.json` |
| `jsonl` | First line: meta + graph + templates. Remaining lines: one operator each | `network_export.jsonl` |

**JSONL** is useful for very large networks -- you can grep it, load specific operators, or stream it line by line.

## Filtering

Use filters to export only what you need. Set them at the top of `export_network.py`:

```python
# Skip TD system/UI internals (default: True)
EXCLUDE_SYSTEM = True

# Only export TOP and CHOP operators
FILTER_FAMILIES = ['TOP', 'CHOP']

# Only export specific operator types
FILTER_TYPES = ['moviefilein', 'null', 'geo']

# Only export operators under a specific path
FILTER_PATH_PREFIX = '/project1/fx'

# Limit recursion depth
FILTER_MAX_DEPTH = 3

# Include/exclude by operator name (fnmatch patterns)
INCLUDE_PATTERNS = ['render*', '*_out']
EXCLUDE_PATTERNS = ['__*', 'local*']
```

All filters are optional and combine with AND logic. Leave as `None` to disable.

Container operators (COMPs) are automatically kept in the output when they have matching descendants, so the hierarchy stays readable even with aggressive filtering.

### Programmatic Usage

You can also call `export_network()` as a function from another script or the Textport:

```python
# In the Textport or another DAT:
exec(op('export_network').text)

# Export only TOPs under /project1, summary mode, as JSONL
export_network(
    path_prefix='/project1',
    families=['TOP'],
    max_depth=3,
    output_mode='summary',
    output_format='jsonl',
    output_filename='tops_summary.jsonl'
)

# Include system operators for debugging TD internals
export_network(exclude_system=False)
```

## Size Comparison

On a real-world Gaussian splatting project (19,377 total operators):

| Configuration | Size | Tokens (est) |
|--------------|------|-------------|
| Original (pretty JSON, all pages) | 23.5 MB | ~6M |
| v1 compact (all operators) | ~2.9 MB | ~760K |
| v2 compact (system excluded, templates) | ~57 KB | ~15K |
| v2 summary (tree + connections only) | ~40 KB | ~10K |

98% of operators in the example project are TD system/UI boilerplate. Excluding them is the single biggest optimization.

## Configuration

Settings at the top of `export_network.py`:

- **`OUTPUT_MODE`** -- `'compact'`, `'summary'`, or `'full'` (default: `'compact'`)
- **`OUTPUT_FORMAT`** -- `'json'` or `'jsonl'` (default: `'json'`)
- **`EXCLUDE_SYSTEM`** -- skip `/sys` and `/ui` subtrees (default: `True`)
- **`FILTER_MAX_DEPTH`** -- how deep to recurse into nested COMPs (default: 6)
- **Root operator** -- change `root_path` in `export_network()` to export a subtree

## Requirements

- TouchDesigner (tested on 2023.x+)
- No external dependencies (uses TD's built-in `Par` API directly)

## License

MIT
