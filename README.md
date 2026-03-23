# TD4LLMs

Export your TouchDesigner network to JSON so LLMs can understand your project.

TD4LLMs serializes your TD network -- operators, parameters, connections, and hierarchy -- into a compact format designed for LLM context windows. Feed it to Claude, ChatGPT, or any LLM to get help debugging, documenting, or extending your TouchDesigner projects.

## Why?

TouchDesigner's `.toe` files are binary -- LLMs can't read them. TD4LLMs bridges that gap by exporting a human-readable representation of your network. Only non-default parameters are included, so the output is small enough to paste directly into an LLM conversation.

## Quick Start

1. Copy `export_network.py` into your TouchDesigner project (e.g., as a Text DAT)
2. Run it from a Text DAT or the Textport:

```python
exec(op('export_network').text)
```

3. Find `network_export.json` (or `.jsonl`) in your project folder
4. Paste the output into your LLM conversation for context

## What Gets Exported

- **Operator tree** -- full hierarchy with paths, names, types, and families
- **Parameters** -- only non-default values (parameters you actually changed)
- **Connections** -- input/output wiring between operators as path arrays
- **Recursion** -- descends into COMPs up to a configurable depth (default: 6 levels)

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
  "name": "render1",
  "type": "glslmulti",
  "family": "TOP",
  "params": {"resolutionw": 1920, "resolutionh": 1080, "outputresolution": 9},
  "inputs": ["/project1/noise1", "/project1/feedback1"]
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
{"path": "/project1/render1", "type": "glslmulti", "family": "TOP", "inputs": ["/project1/noise1"]}
```

No parameters at all -- just the network graph.

## Output Formats

Set `OUTPUT_FORMAT` at the top of the script:

| Format | Description | Output file |
|--------|------------|-------------|
| `json` (default) | Nested JSON tree | `network_export.json` |
| `jsonl` | Flat JSONL, one operator per line | `network_export.jsonl` |

**JSONL** is useful for very large networks -- you can grep it, load specific operators, or stream it line by line. Each line is a self-contained JSON object with the operator's `path` encoding its position in the hierarchy.

## Filtering

Use filters to export only what you need. Set them at the top of `export_network.py`:

```python
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
```

## Size Comparison

On a real-world Gaussian splatting project (19,377 operators):

| Configuration | Size | Reduction |
|--------------|------|-----------|
| Original (pretty JSON, all pages) | 23.5 MB | -- |
| Compact JSON (non-default params, minified) | ~2.9 MB | 88% |
| Summary JSONL (tree + connections only) | ~2.4 MB | 90% |

With filtering applied (e.g., only TOPs in one subtree), output typically drops to KB range.

## Configuration

Settings at the top of `export_network.py`:

- **`OUTPUT_MODE`** -- `'compact'`, `'summary'`, or `'full'` (default: `'compact'`)
- **`OUTPUT_FORMAT`** -- `'json'` or `'jsonl'` (default: `'json'`)
- **`FILTER_MAX_DEPTH`** -- how deep to recurse into nested COMPs (default: 6)
- **Root operator** -- change `op('/')` to export a subtree instead of the whole project

## Requirements

- TouchDesigner (tested on 2023.x+)
- No external dependencies (uses TD's built-in `Par` API directly)

## License

MIT
