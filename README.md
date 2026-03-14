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

## Requirements

- TouchDesigner (tested on 2023.x+)
- Uses the built-in `TDJSON` module (no external dependencies)

## License

MIT
