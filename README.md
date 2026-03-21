# TD4LLMs

Export your TouchDesigner network to JSON so LLMs can understand your project.

TD4LLMs serializes your entire TD network — operators, parameters, connections, and hierarchy — into a structured JSON file. Feed it to Claude, ChatGPT, or any LLM to get help debugging, documenting, or extending your TouchDesigner projects.

## Why?

TouchDesigner's `.toe` files are binary — LLMs can't read them. TD4LLMs bridges that gap by exporting a complete, human-readable representation of your network that gives an LLM full context about your project's structure.

## Quick Start

1. Copy `export_network.py` into your TouchDesigner project (e.g., as a Text DAT)
2. Run it from a Text DAT or the Textport:

```python
exec(op('export_network').text)
```

3. Find `network_export.json` in your project folder
4. Paste the JSON into your LLM conversation for context

## What Gets Exported

- **Operator tree** — full hierarchy with paths, names, types, and families
- **Parameters** — all parameter pages serialized via TDJSON (TouchDesigner's built-in serializer)
- **Connections** — input/output wiring between operators
- **Recursion** — descends into COMPs up to a configurable depth (default: 6 levels)

## Example

See [`example_export.json`](example_export.json) for a real-world export from a Gaussian splatting project.

## Configuration

In `export_network.py`, you can adjust:

- **`max_depth`** — how deep to recurse into nested COMPs (default: 6)
- **Root operator** — change `op('/')` to export a subtree instead of the whole project

## Generate CLAUDE.md

Turn your export into a markdown project overview that Claude Code (or any LLM) can use as context:

```bash
python generate_claude_md.py network_export.json -o CLAUDE.md
```

Drop the generated `CLAUDE.md` into your project folder and Claude Code automatically understands your TD network -- operator tree, signal flows, key parameters.

### Options

```bash
# Print to stdout
python generate_claude_md.py network_export.json

# Control tree depth (default: 3 levels)
python generate_claude_md.py network_export.json --tree-depth 4

# Limit parameter entries (default: 20)
python generate_claude_md.py network_export.json --max-params 10

# Use a custom template
python generate_claude_md.py network_export.json --template my_template.md
```

### Custom Templates

Create a markdown file with these placeholders:

- `{overview}` -- operator counts, families, common types
- `{tree}` -- indented operator tree
- `{containers}` -- top-level container summary
- `{signal_flows}` -- signal flow hub analysis
- `{parameters}` -- key non-default parameters
- `{family_reference}` -- operator family descriptions

### Programmatic Usage

```python
from generate_claude_md import generate

md = generate('network_export.json', tree_depth=4, max_params=10)
with open('CLAUDE.md', 'w') as f:
    f.write(md)
```

## Requirements

- TouchDesigner (tested on 2023.x+) for `export_network.py`
- Python 3.6+ for `generate_claude_md.py` (no external dependencies)

## License

MIT
