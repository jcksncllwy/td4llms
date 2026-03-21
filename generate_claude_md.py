"""
Generate a TD network overview from a TD4LLMs export.

Reads a JSON or JSONL export and produces a markdown file that gives
an LLM a high-level understanding of the TouchDesigner project --
operator tree, signal flows, key parameters, and architecture.

Default output is TD_NETWORK.md. Use --update-claude-md to also add
a reference line to CLAUDE.md so Claude Code picks it up automatically.

Usage:
    python generate_claude_md.py network_export.json
    python generate_claude_md.py network_export.json -o TD_NETWORK.md
    python generate_claude_md.py network_export.json --update-claude-md
    python generate_claude_md.py network_export.json --template my_template.md
    python generate_claude_md.py network_export.json --tree-depth 4 --max-params 10
"""

import json
import argparse
import sys
import os
from collections import Counter
from pathlib import Path


# ── Analysis ─────────────────────────────────────────────────────────


def load_export(path):
    """Load a JSON or JSONL export file.

    Returns a normalized operator tree (dict). JSONL files are
    reconstructed into a tree from their flat path-based entries.
    """
    path = str(path)

    if path.endswith('.jsonl'):
        return _load_jsonl(path)

    with open(path) as f:
        return _normalize_node(json.load(f))


def _load_jsonl(path):
    """Reconstruct a tree from flat JSONL entries."""
    ops = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                ops.append(json.loads(line))

    if not ops:
        return {}

    # Build lookup by path
    by_path = {op['path']: op for op in ops}

    # Reconstruct parent-child relationships from paths
    for op in ops:
        op_path = op['path']
        parent_path = op_path.rsplit('/', 1)[0] or '/'
        if parent_path != op_path and parent_path in by_path:
            parent = by_path[parent_path]
            parent.setdefault('children', []).append(op)

    # Root is the entry with path '/' or the shallowest path
    root = by_path.get('/')
    if not root:
        root = min(ops, key=lambda o: o['path'].count('/'))

    return _normalize_node(root)


def _normalize_node(node):
    """Normalize a node to handle both old and new export formats.

    Old format: inputs/outputs are [{index, path, name}, ...]
    New format: inputs/outputs are [path, ...]
    """
    # Normalize inputs
    if 'inputs' in node:
        inputs = node['inputs']
        if inputs and isinstance(inputs[0], dict):
            node['inputs'] = [inp['path'] for inp in inputs]

    # Normalize outputs
    if 'outputs' in node:
        outputs = node['outputs']
        if outputs and isinstance(outputs[0], dict):
            node['outputs'] = [out['path'] for out in outputs]

    # Remove pages (old format noise, not useful for CLAUDE.md)
    node.pop('pages', None)

    # Recurse into children
    for child in node.get('children', []):
        _normalize_node(child)

    return node


def analyze(root):
    """Analyze a network export and return a structured summary.

    Returns a dict with all the data needed to render a template:
        name, total_ops, max_depth, family_counts, type_counts,
        top_containers, signal_chains, params_summary, tree
    """
    stats = {
        'name': root.get('name', 'unknown'),
        'root_path': root.get('path', '/'),
        'total_ops': 0,
        'max_depth': 0,
        'family_counts': Counter(),
        'type_counts': Counter(),
        'containers': [],       # (path, name, type, child_count, families_inside)
        'signal_chains': [],    # notable connection chains
        'param_ops': [],        # operators with interesting parameters
    }

    # Walk the tree
    _walk(root, stats, depth=0)

    # Sort containers by child count (most complex first)
    stats['containers'].sort(key=lambda c: c['child_count'], reverse=True)

    # Find signal chains (operators with many connections)
    all_ops = []
    _flatten(root, all_ops)
    stats['signal_chains'] = _find_signal_chains(all_ops)

    # Collect operators with notable parameters
    stats['param_ops'] = _find_notable_params(all_ops)

    return stats


def _walk(node, stats, depth):
    """Recursive walk to collect statistics."""
    stats['total_ops'] += 1
    stats['max_depth'] = max(stats['max_depth'], depth)
    stats['family_counts'][node.get('family', '?')] += 1
    stats['type_counts'][node.get('type', '?')] += 1

    children = node.get('children', [])
    if children:
        # This is a container -- analyze its contents
        child_families = Counter()
        child_count = _count_descendants(node)
        for child in children:
            child_families[child.get('family', '?')] += 1

        stats['containers'].append({
            'path': node['path'],
            'name': node['name'],
            'type': node.get('type', '?'),
            'child_count': child_count,
            'families': dict(child_families),
            'depth': depth,
        })

        for child in children:
            _walk(child, stats, depth + 1)


def _count_descendants(node):
    """Count all descendants of a node."""
    count = 0
    for child in node.get('children', []):
        count += 1 + _count_descendants(child)
    return count


def _flatten(node, result):
    """Flatten the tree into a list of all operators."""
    result.append(node)
    for child in node.get('children', []):
        _flatten(child, result)


def _find_signal_chains(all_ops):
    """Find notable signal flow patterns.

    Looks for operators that are hubs (many inputs or outputs),
    and traces short chains through the network.
    """
    chains = []

    # Build adjacency: output_path -> list of ops that receive from it
    # Also find hub operators (>= 3 connections)
    hubs = []
    for op in all_ops:
        inputs = op.get('inputs', [])
        outputs = op.get('outputs', [])
        total_connections = len(inputs) + len(outputs)
        if total_connections >= 3:
            hubs.append({
                'path': op['path'],
                'name': op['name'],
                'type': op.get('type', '?'),
                'family': op.get('family', '?'),
                'num_inputs': len(inputs),
                'num_outputs': len(outputs),
                'input_paths': inputs,
                'output_paths': outputs,
            })

    # Sort by total connections
    hubs.sort(key=lambda h: h['num_inputs'] + h['num_outputs'], reverse=True)

    return hubs[:20]  # Top 20 hub operators


def _find_notable_params(all_ops):
    """Find operators with interesting non-default parameters."""
    notable = []
    for op in all_ops:
        params = op.get('params')
        if not params:
            continue

        # Look for params that suggest important configuration:
        # file paths, expressions, binds, exports
        interesting = {}
        for name, val in params.items():
            if isinstance(val, dict):
                # Expression, bind, or export -- always interesting
                interesting[name] = val
            elif isinstance(val, str) and ('/' in val or '\\' in val):
                # Looks like a file path
                interesting[name] = val
            elif name in ('file', 'dat', 'top', 'chop', 'sop', 'mat',
                          'text', 'glsl', 'pixelformat', 'resolutionw',
                          'resolutionh', 'rate', 'length'):
                # Known important parameter names
                interesting[name] = val

        if interesting:
            notable.append({
                'path': op['path'],
                'name': op['name'],
                'type': op.get('type', '?'),
                'family': op.get('family', '?'),
                'params': interesting,
            })

    # Limit to most interesting (by number of notable params)
    notable.sort(key=lambda n: len(n['params']), reverse=True)
    return notable[:30]


# ── Tree Rendering ───────────────────────────────────────────────────


def render_tree(root, max_depth=3, indent=0):
    """Render an indented operator tree as a string.

    Shows full detail for the first max_depth levels, then
    summarizes deeper containers with operator counts.
    """
    lines = []
    _render_node(root, lines, max_depth, depth=0, indent=indent)
    return '\n'.join(lines)


def _render_node(node, lines, max_depth, depth, indent):
    """Render a single node and recurse into children."""
    prefix = '  ' * indent
    name = node.get('name', '?')
    op_type = node.get('type', '?')
    family = node.get('family', '?')
    children = node.get('children', [])
    inputs = node.get('inputs', [])

    # Build the line
    label = f"{name}"
    if children:
        label += '/'
    label += f"  ({op_type}, {family})"

    # Show inputs if any
    if inputs:
        input_names = [p.rsplit('/', 1)[-1] for p in inputs]
        label += f"  <- {', '.join(input_names)}"

    lines.append(f"{prefix}{label}")

    # Handle children
    if not children:
        return

    if depth >= max_depth:
        # Summarize instead of expanding
        child_count = _count_descendants(node)
        families = Counter()
        for child in children:
            families[child.get('family', '?')] += 1
            # Also count grandchildren's families
            _count_families(child, families)
        family_str = ', '.join(f"{c} {f}" for f, c in families.most_common())
        lines.append(f"{prefix}  ... {child_count} operators ({family_str})")
    else:
        for child in children:
            _render_node(child, lines, max_depth, depth + 1, indent + 1)


def _count_families(node, counter):
    """Recursively count families in a subtree."""
    for child in node.get('children', []):
        counter[child.get('family', '?')] += 1
        _count_families(child, counter)


# ── Markdown Generation ──────────────────────────────────────────────


DEFAULT_TEMPLATE = """\
# TouchDesigner Project

> Auto-generated by [TD4LLMs](https://github.com/jcksncllwy/td4llms).
> Re-generate after significant network changes to keep this file current.

## Overview

{overview}

## Network Architecture

### Operator Tree

```
{tree}
```

### Top-Level Containers

{containers}

{signal_flows}

{parameters}

## Operator Family Reference

{family_reference}
"""


def generate(export_path, template_path=None, tree_depth=3, max_params=20):
    """Generate TD network overview markdown from an export file.

    Args:
        export_path: Path to JSON or JSONL export file.
        template_path: Optional path to a custom template file.
        tree_depth: How many levels deep to expand the operator tree.
        max_params: Maximum number of parameter entries to include.

    Returns:
        The generated markdown as a string.
    """
    root = load_export(export_path)
    stats = analyze(root)

    # Render sections
    overview = _render_overview(stats)
    tree = render_tree(root, max_depth=tree_depth)
    containers = _render_containers(stats)
    signal_flows = _render_signal_flows(stats)
    parameters = _render_parameters(stats, max_params)
    family_reference = _render_family_reference(stats)

    if template_path:
        with open(template_path) as f:
            template = f.read()
    else:
        template = DEFAULT_TEMPLATE

    return template.format(
        overview=overview,
        tree=tree,
        containers=containers,
        signal_flows=signal_flows,
        parameters=parameters,
        family_reference=family_reference,
    )


def _render_overview(stats):
    """Render the overview section."""
    lines = []
    lines.append(f"- **{stats['total_ops']:,}** operators across "
                 f"**{len(stats['family_counts'])}** families")
    lines.append(f"- **{stats['max_depth']}** levels deep")

    # Top-level summary
    top_families = stats['family_counts'].most_common()
    family_str = ', '.join(f"{f}: {c:,}" for f, c in top_families)
    lines.append(f"- Families: {family_str}")

    # Most common types
    top_types = stats['type_counts'].most_common(8)
    type_str = ', '.join(f"`{t}` ({c:,})" for t, c in top_types)
    lines.append(f"- Most common types: {type_str}")

    return '\n'.join(lines)


def _render_containers(stats):
    """Render the top-level containers section."""
    # Show containers at depth 1 (direct children of root)
    top = [c for c in stats['containers'] if c['depth'] == 1]

    if not top:
        # Fall back to all containers
        top = stats['containers'][:10]

    if not top:
        return "_No containers found._"

    lines = []
    for c in top[:15]:
        families = ', '.join(f"{v} {k}" for k, v in
                             sorted(c['families'].items(),
                                    key=lambda x: -x[1]))
        lines.append(f"- **`{c['path']}`** ({c['type']}, {c['child_count']:,} "
                     f"descendants) -- {families}")

    return '\n'.join(lines)


def _render_signal_flows(stats):
    """Render signal flow hubs section."""
    hubs = stats['signal_chains']
    if not hubs:
        return ""

    lines = ["### Signal Flow Hubs", "",
             "Operators with the most connections (likely routing or mixing points):", ""]

    for hub in hubs[:12]:
        total = hub['num_inputs'] + hub['num_outputs']
        direction = []
        if hub['num_inputs']:
            direction.append(f"{hub['num_inputs']} in")
        if hub['num_outputs']:
            direction.append(f"{hub['num_outputs']} out")

        lines.append(f"- **`{hub['path']}`** ({hub['type']}, {hub['family']}) "
                     f"-- {', '.join(direction)}")

    return '\n'.join(lines)


def _render_parameters(stats, max_params):
    """Render the key parameters section."""
    param_ops = stats['param_ops'][:max_params]
    if not param_ops:
        return ""

    lines = ["## Key Parameters", "",
             "Operators with notable non-default parameters "
             "(file paths, expressions, binds):", ""]

    for op in param_ops:
        lines.append(f"### `{op['path']}` ({op['type']}, {op['family']})")
        lines.append("")
        for name, val in op['params'].items():
            if isinstance(val, dict):
                # Expression/bind/export
                if 'expr' in val:
                    lines.append(f"- `{name}`: expression `{val['expr']}`")
                elif 'bind' in val:
                    lines.append(f"- `{name}`: bind `{val['bind']}`")
                elif 'export' in val:
                    lines.append(f"- `{name}`: exported from `{val['export']}`")
                else:
                    lines.append(f"- `{name}`: `{val}`")
            else:
                lines.append(f"- `{name}`: `{val}`")
        lines.append("")

    return '\n'.join(lines)


def _render_family_reference(stats):
    """Render a quick-reference of TD operator families."""
    family_descriptions = {
        'COMP': 'Components -- containers, geometry, cameras, lights, panels',
        'TOP': 'Texture Operators -- 2D image processing, rendering, compositing',
        'CHOP': 'Channel Operators -- animation, audio, control signals, math',
        'SOP': 'Surface Operators -- 3D geometry, meshes, points',
        'DAT': 'Data Operators -- tables, text, scripts, web data',
        'MAT': 'Material Operators -- shaders, materials, PBR',
        'POP': 'Particle Operators -- particle systems (legacy)',
    }

    lines = []
    for family, count in stats['family_counts'].most_common():
        desc = family_descriptions.get(family, 'Unknown family')
        lines.append(f"- **{family}** ({count:,}) -- {desc}")

    return '\n'.join(lines)


# ── Config ───────────────────────────────────────────────────────────

CONFIG_FILE = '.td4llms.json'


def load_config(config_path=CONFIG_FILE):
    """Load saved preferences from .td4llms.json."""
    if os.path.exists(config_path):
        try:
            with open(config_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_config(config, config_path=CONFIG_FILE):
    """Save preferences to .td4llms.json."""
    existing = load_config(config_path)
    existing.update(config)
    with open(config_path, 'w') as f:
        json.dump(existing, f, indent=2)
        f.write('\n')


# ── CLAUDE.md Update ─────────────────────────────────────────────────


_CLAUDE_MD_REFERENCE = (
    '\n# TouchDesigner Network\n\n'
    'See TD_NETWORK.md for the TouchDesigner network architecture '
    '(operator tree, signal flows, parameters).\n'
)


def update_claude_md(output_name='TD_NETWORK.md', claude_md_path='CLAUDE.md'):
    """Add a reference to the network overview in CLAUDE.md.

    Appends a one-liner pointing to the network file. If CLAUDE.md
    already references the file, does nothing. Creates CLAUDE.md
    if it doesn't exist.

    Returns True if CLAUDE.md was modified, False if already up to date.
    """
    reference = _CLAUDE_MD_REFERENCE.replace('TD_NETWORK.md', output_name)
    marker = output_name

    if os.path.exists(claude_md_path):
        with open(claude_md_path) as f:
            existing = f.read()
        if marker in existing:
            return False
        with open(claude_md_path, 'a') as f:
            f.write(reference)
    else:
        with open(claude_md_path, 'w') as f:
            f.write(reference.lstrip('\n'))

    return True


# ── CLI ──────────────────────────────────────────────────────────────


def _resolve_update_claude_md(args):
    """Determine whether to update CLAUDE.md.

    Priority:
    1. Explicit CLI flags (--update-claude-md / --no-update-claude-md)
    2. Saved preference in .td4llms.json
    3. Interactive prompt (if TTY available)
    4. Default to False (non-interactive / piped)
    """
    # Explicit flags win
    if args.update_claude_md:
        return True
    if args.no_update_claude_md:
        return False

    # Check saved config
    config = load_config()
    if 'update_claude_md' in config:
        return config['update_claude_md']

    # No saved preference -- ask if interactive
    if not sys.stdin.isatty():
        return False

    print("", file=sys.stderr)
    print("Add a reference to CLAUDE.md so Claude Code can find "
          "your network overview?", file=sys.stderr)
    print("  This appends a one-liner pointing to the generated file.",
          file=sys.stderr)
    print("  (Your choice is saved in .td4llms.json for future runs.)",
          file=sys.stderr)
    print("", file=sys.stderr)

    while True:
        try:
            answer = input("Update CLAUDE.md? [y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("", file=sys.stderr)
            return False
        if answer in ('y', 'yes'):
            save_config({'update_claude_md': True})
            return True
        elif answer in ('n', 'no'):
            save_config({'update_claude_md': False})
            return False
        print("  Please enter y or n.", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description='Generate a TD network overview from a TD4LLMs export.',
        epilog='Example: python generate_claude_md.py export.json'
    )
    parser.add_argument('export_file',
                        help='Path to the JSON or JSONL network export')
    parser.add_argument('-o', '--output', default='TD_NETWORK.md',
                        help='Output file path (default: TD_NETWORK.md)')
    parser.add_argument('--update-claude-md', action='store_true',
                        default=False,
                        help='Add a reference to the output file in CLAUDE.md')
    parser.add_argument('--no-update-claude-md', action='store_true',
                        default=False,
                        help='Do not update CLAUDE.md (overrides saved preference)')
    parser.add_argument('--claude-md', default='CLAUDE.md',
                        help='Path to CLAUDE.md (default: CLAUDE.md)')
    parser.add_argument('--template', default=None,
                        help='Path to a custom markdown template')
    parser.add_argument('--tree-depth', type=int, default=3,
                        help='Max depth for the operator tree (default: 3)')
    parser.add_argument('--max-params', type=int, default=20,
                        help='Max parameter entries to show (default: 20)')
    parser.add_argument('--stdout', action='store_true',
                        help='Print to stdout instead of writing a file')

    args = parser.parse_args()

    if not os.path.exists(args.export_file):
        print(f"Error: file not found: {args.export_file}", file=sys.stderr)
        sys.exit(1)

    md = generate(
        export_path=args.export_file,
        template_path=args.template,
        tree_depth=args.tree_depth,
        max_params=args.max_params,
    )

    if args.stdout:
        print(md)
    else:
        with open(args.output, 'w') as f:
            f.write(md)
        print(f"Generated {args.output} "
              f"({len(md) / 1024:.1f} KB)", file=sys.stderr)

        should_update = _resolve_update_claude_md(args)
        if should_update:
            output_name = os.path.basename(args.output)
            modified = update_claude_md(output_name, args.claude_md)
            if modified:
                print(f"Added reference to {output_name} in "
                      f"{args.claude_md}", file=sys.stderr)
            else:
                print(f"{args.claude_md} already references "
                      f"{output_name}", file=sys.stderr)


if __name__ == '__main__':
    main()
