"""
Export TouchDesigner network to JSON for LLM context.

Run from a Text DAT or paste into the textport:
    exec(op('export_network').text)

Outputs to: [project folder]/network_export.json

## Output Modes

    OUTPUT_MODE = 'compact'   Only non-default parameters (recommended, smallest)
    OUTPUT_MODE = 'summary'   Operator tree + connections only, no parameters
    OUTPUT_MODE = 'full'      All non-default parameters with metadata (style, mode)

## Output Formats

    OUTPUT_FORMAT = 'json'    Nested JSON (default)
    OUTPUT_FORMAT = 'jsonl'   Flat JSONL, one operator per line (grep-friendly)

## System Filtering

    EXCLUDE_SYSTEM = True     Skip /sys and /ui subtrees (default: True)

TD projects contain thousands of system and UI operators that are identical
across all projects. These are noise for LLM context. Set to False only if
you specifically need to inspect TD internals.

## Filtering

Set any combination of filters below to reduce the export size.
All filters are optional -- leave as None or empty to disable.

    FILTER_FAMILIES     Only include these operator families (e.g. ['TOP', 'CHOP'])
    FILTER_TYPES        Only include these operator types (e.g. ['moviefilein', 'null'])
    FILTER_PATH_PREFIX  Only include operators under this path (e.g. '/project1/fx')
    FILTER_MAX_DEPTH    Max recursion depth from root (default: 6)
    INCLUDE_PATTERNS    Include operators whose names match these patterns (fnmatch)
    EXCLUDE_PATTERNS    Exclude operators whose names match these patterns (fnmatch)

Containers (COMPs) are kept in the output when they have matching descendants,
so the hierarchy stays intact even when filtering by type or family.
"""

import json
from fnmatch import fnmatch

# ─── Output Configuration ────────────────────────────────────────────
# Controls how much detail is exported and in what format.

OUTPUT_MODE = 'compact'        # 'compact', 'summary', or 'full'
OUTPUT_FORMAT = 'json'         # 'json' or 'jsonl'

# ─── System Filtering ─────────────────────────────────────────────────
# TD projects contain thousands of system/UI operators identical across
# all projects. Exclude them by default to focus on user content.

EXCLUDE_SYSTEM = True           # Skip /sys, /ui subtrees

# Paths excluded when EXCLUDE_SYSTEM is True. These are TD internal
# subsystems that are the same in every project.
_SYSTEM_PATHS = ('/sys', '/ui')

# ─── Filter Configuration ─────────────────────────────────────────────
# Set these to control what gets exported. None or [] means "no filter".

FILTER_FAMILIES = None          # e.g. ['TOP', 'CHOP', 'SOP']
FILTER_TYPES = None             # e.g. ['moviefilein', 'null', 'geo']
FILTER_PATH_PREFIX = None       # e.g. '/project1/fx'
FILTER_MAX_DEPTH = 6            # max recursion depth from root
INCLUDE_PATTERNS = None         # e.g. ['render*', '*_out'] (fnmatch on op name)
EXCLUDE_PATTERNS = None         # e.g. ['__*', 'local*'] (fnmatch on op name)

# ─── End Configuration ─────────────────────────────────────────────────


# ─── Graph Collector ──────────────────────────────────────────────────
# Accumulates connection edges during serialization for the top-level
# relationship graph. Three edge types:
#   ["input",  src_path, dst_path, slot]  -- data flow
#   ["bind",   src_expr, dst_path:par]    -- parameter bind
#   ["export", src_path, dst_path:par]    -- CHOP/DAT export

_graph_edges = []


def _reset_graph():
    global _graph_edges
    _graph_edges = []


# ─── Filter Functions ─────────────────────────────────────────────────

def _is_system_path(path):
    """Check if a path is under a TD system subtree."""
    for sp in _SYSTEM_PATHS:
        if path == sp or path.startswith(sp + '/'):
            return True
    return False


def matches_filters(operator):
    """Check if a leaf operator passes all active filters.

    Containers (COMPs) are handled separately during recursion -- they're
    included when they have any matching descendants. This function is for
    deciding whether a non-container op should appear in the output.
    """
    if FILTER_FAMILIES and operator.family not in FILTER_FAMILIES:
        return False

    if FILTER_TYPES and operator.type not in FILTER_TYPES:
        return False

    if FILTER_PATH_PREFIX:
        prefix = FILTER_PATH_PREFIX.rstrip('/')
        if not operator.path.startswith(prefix + '/') and operator.path != prefix:
            return False

    if INCLUDE_PATTERNS:
        if not any(fnmatch(operator.name, pat) for pat in INCLUDE_PATTERNS):
            return False

    if EXCLUDE_PATTERNS:
        if any(fnmatch(operator.name, pat) for pat in EXCLUDE_PATTERNS):
            return False

    return True


def path_could_contain_prefix(op_path):
    """Check if an operator's subtree could contain the target path prefix.

    Returns True if:
    - The operator IS at or under the prefix, or
    - The prefix is deeper than this operator (so children might match)
    """
    if not FILTER_PATH_PREFIX:
        return True
    prefix = FILTER_PATH_PREFIX.rstrip('/')
    if op_path.startswith(prefix + '/') or op_path == prefix:
        return True
    if prefix.startswith(op_path + '/') or prefix == op_path:
        return True
    return False


def has_active_filters():
    """Return True if any filter other than max_depth and EXCLUDE_SYSTEM is set."""
    return any([FILTER_FAMILIES, FILTER_TYPES, FILTER_PATH_PREFIX,
                INCLUDE_PATTERNS, EXCLUDE_PATTERNS])


# ─── Parameter Serialization ─────────────────────────────────────────

# Parameter styles that are never useful to export
_SKIP_STYLES = {'Pulse', 'Header'}


def serialize_par(par, owner_path=None):
    """Serialize a single non-default parameter.

    Returns a dict with the parameter value (and expression/mode if
    not in constant mode). Returns None for parameters that should
    be skipped (pulses, headers, read-only with no expression).

    When owner_path is provided, bind/export edges are added to the
    global graph collector.
    """
    try:
        if par.isDefault:
            return None
    except (AttributeError, TypeError):
        return None

    # Skip pulse buttons, headers, and read-only params with no expression
    try:
        if par.style in _SKIP_STYLES:
            return None
        if par.readOnly and par.mode == ParMode.CONSTANT:
            return None
    except (AttributeError, TypeError):
        pass

    result = {}

    try:
        mode = par.mode
        if mode == ParMode.EXPRESSION:
            result['expr'] = par.expr
        elif mode == ParMode.EXPORT:
            try:
                source = par.exportSource.path if par.exportSource else None
                result['export'] = source if source else True
                if source and owner_path:
                    _graph_edges.append(['export', source, owner_path + ':' + par.name])
            except (AttributeError, TypeError):
                result['export'] = True
        elif mode == ParMode.BIND:
            try:
                bind_expr = par.bindExpr
                result['bind'] = bind_expr
                if bind_expr and owner_path:
                    _graph_edges.append(['bind', bind_expr, owner_path + ':' + par.name])
            except (AttributeError, TypeError):
                result['bind'] = True
        else:
            result['val'] = par.val
    except (AttributeError, TypeError):
        try:
            result['val'] = par.val
        except (AttributeError, TypeError):
            return None

    if not result:
        return None

    return result


def serialize_par_full(par, owner_path=None):
    """Serialize a non-default parameter with full metadata.

    Includes style (type), label, and range info in addition to value.
    Used by OUTPUT_MODE = 'full'.
    """
    base = serialize_par(par, owner_path)
    if base is None:
        return None

    try:
        base['style'] = par.style
    except (AttributeError, TypeError):
        pass
    try:
        if par.label and par.label != par.name:
            base['label'] = par.label
    except (AttributeError, TypeError):
        pass

    return base


def serialize_params(operator):
    """Serialize all non-default parameters for an operator.

    Returns a dict of {par_name: value_or_info} for parameters that
    differ from their defaults. Returns None if no non-default params.

    In compact mode, constant-mode parameters are stored as bare values:
        {"file": "/path/to/file.mov", "resolutionw": 1920}

    Parameters with expressions/binds/exports use nested dicts:
        {"tx": {"expr": "absTime.seconds"}}
    """
    if OUTPUT_MODE == 'summary':
        return None

    serialize_fn = serialize_par_full if OUTPUT_MODE == 'full' else serialize_par
    params = {}

    try:
        for par in operator.pars():
            data = serialize_fn(par, owner_path=operator.path)
            if data is not None:
                if OUTPUT_MODE == 'compact' and list(data.keys()) == ['val']:
                    params[par.name] = data['val']
                else:
                    params[par.name] = data
    except Exception:
        pass

    return params if params else None


# ─── Operator Serialization ──────────────────────────────────────────

def serialize_op(operator, depth=0):
    """Serialize an operator and its children recursively.

    Connections are collected into the global graph rather than stored
    per-operator. When filters are active, containers are only included
    if they have matching descendants.
    """
    if depth > FILTER_MAX_DEPTH:
        return None

    # System path exclusion (before other filters)
    if EXCLUDE_SYSTEM and depth == 1 and _is_system_path(operator.path):
        return None

    if not path_could_contain_prefix(operator.path):
        return None

    node = {
        'path': operator.path,
        'type': operator.type,
        'family': operator.family,
    }

    # Parameters (non-default only)
    params = serialize_params(operator)
    if params:
        node['params'] = params

    # Collect connections into the top-level graph
    try:
        inputs = operator.inputs
        for slot, inp in enumerate(inputs):
            if inp is not None:
                # Only add edge if source isn't in an excluded system path
                if not (EXCLUDE_SYSTEM and _is_system_path(inp.path)):
                    _graph_edges.append(['input', inp.path, operator.path, slot])
    except Exception:
        pass

    # Recurse into children (COMPs only)
    is_container = False
    try:
        kids = operator.children
        if kids:
            is_container = True
            children = []
            for child in sorted(kids, key=lambda c: c.name):
                child_data = serialize_op(child, depth + 1)
                if child_data:
                    children.append(child_data)
            if children:
                node['children'] = children
    except Exception:
        pass

    # Filtering logic
    if has_active_filters():
        if is_container:
            if 'children' not in node or not node['children']:
                if not matches_filters(operator):
                    return None
        else:
            if not matches_filters(operator):
                return None

    return node


# ─── JSONL Flattening ─────────────────────────────────────────────────

def flatten_ops(node):
    """Flatten a nested operator tree into a list of operators.

    Each operator keeps its path (encodes hierarchy) but children
    are extracted into separate entries. Used for JSONL output.
    """
    ops = []
    flat_node = {k: v for k, v in node.items() if k != 'children'}
    ops.append(flat_node)
    for child in node.get('children', []):
        ops.extend(flatten_ops(child))
    return ops


# ─── Template Detection ──────────────────────────────────────────────

def _detect_templates(root_node):
    """Detect repeated operator signatures and extract templates.

    A signature is (type, family, frozenset of non-default param names).
    Operators sharing a signature get a template; per-instance param
    values become overrides.

    Returns:
        templates: dict of {template_id: {type, family, params (common values)}}
        The root_node is modified in-place -- templateable operators get
        'template' and optional 'overrides' keys, with type/family/params removed.
    """
    # First pass: collect all leaf operators by signature
    sig_groups = {}  # signature -> list of node references

    def collect_leaves(node):
        if 'children' in node:
            for child in node['children']:
                collect_leaves(child)
        else:
            param_keys = frozenset(node.get('params', {}).keys()) if 'params' in node else frozenset()
            sig = (node['type'], node['family'], param_keys)
            sig_groups.setdefault(sig, []).append(node)

    collect_leaves(root_node)

    # Only create templates for signatures with 2+ instances
    templates = {}
    template_counter = 0

    for sig, nodes in sig_groups.items():
        if len(nodes) < 2:
            continue

        op_type, op_family, param_keys = sig
        template_id = 't' + str(template_counter)
        template_counter += 1

        templates[template_id] = {
            'type': op_type,
            'family': op_family,
        }

        # Rewrite each node to reference the template
        for node in nodes:
            overrides = node.pop('params', None)
            node.pop('type', None)
            node.pop('family', None)
            node['template'] = template_id
            if overrides:
                node['overrides'] = overrides

    return templates


# ─── Metadata Generation ─────────────────────────────────────────────

def _generate_meta(root_node, graph_edges):
    """Generate the _meta section with network statistics."""
    total_ops = 0
    type_census = {}
    subsystems = {}

    def count_ops(node, depth=0, subsystem=None):
        nonlocal total_ops
        total_ops += 1
        key = node.get('type', node.get('template', '?')) + '/' + node.get('family', '?')
        type_census[key] = type_census.get(key, 0) + 1

        if depth == 1:
            subsystem = node['path']

        if subsystem and depth == 1:
            sub_count = _count_subtree(node)
            sub_types = {}
            _count_types(node, sub_types)
            subsystems[node['path']] = {
                'ops': sub_count,
                'types': sub_types,
            }

        for child in node.get('children', []):
            count_ops(child, depth + 1, subsystem)

    count_ops(root_node)

    # Cross-subsystem connections
    cross_edges = []
    for edge in graph_edges:
        if edge[0] == 'input':
            src_sub = _get_subsystem(edge[1])
            dst_sub = _get_subsystem(edge[2])
            if src_sub and dst_sub and src_sub != dst_sub:
                cross_edges.append(edge)

    meta = {
        'total_ops': total_ops,
        'connections': len(graph_edges),
        'subsystems': subsystems,
    }

    if cross_edges:
        meta['cross_subsystem_connections'] = cross_edges

    if EXCLUDE_SYSTEM:
        meta['system_excluded'] = list(_SYSTEM_PATHS)

    return meta


def _count_subtree(node):
    count = 1
    for child in node.get('children', []):
        count += _count_subtree(child)
    return count


def _count_types(node, types_dict):
    family = node.get('family', '?')
    types_dict[family] = types_dict.get(family, 0) + 1
    for child in node.get('children', []):
        _count_types(child, types_dict)


def _get_subsystem(path):
    """Extract the top-level subsystem from a path (e.g., '/project1' from '/project1/op1')."""
    parts = path.strip('/').split('/')
    if parts:
        return '/' + parts[0]
    return None


# ─── Main ──────────────────────────────────────────────────────────────

def export_network(root_path='/', output_filename=None,
                   families=None, types=None, path_prefix=None,
                   max_depth=None, include_patterns=None,
                   exclude_patterns=None, output_mode=None,
                   output_format=None, exclude_system=None):
    """Export the operator network with optional filtering and format control.

    Can be called as a function for programmatic use, or the script
    can be run directly with the module-level configuration variables.

    Args:
        root_path: Starting operator path (default: '/')
        output_filename: Output filename in project folder (auto-set if None)
        families: List of operator families, e.g. ['TOP', 'CHOP']
        types: List of operator types, e.g. ['moviefilein', 'null']
        path_prefix: Only export ops under this path
        max_depth: Max recursion depth (default: 6)
        include_patterns: fnmatch patterns for operator names to include
        exclude_patterns: fnmatch patterns for operator names to exclude
        output_mode: 'compact', 'summary', or 'full'
        output_format: 'json' or 'jsonl'
        exclude_system: Skip /sys and /ui subtrees (default: True)

    Returns:
        The structured export data.
    """
    global FILTER_FAMILIES, FILTER_TYPES, FILTER_PATH_PREFIX
    global FILTER_MAX_DEPTH, INCLUDE_PATTERNS, EXCLUDE_PATTERNS
    global OUTPUT_MODE, OUTPUT_FORMAT, EXCLUDE_SYSTEM

    if families is not None:
        FILTER_FAMILIES = families
    if types is not None:
        FILTER_TYPES = types
    if path_prefix is not None:
        FILTER_PATH_PREFIX = path_prefix
    if max_depth is not None:
        FILTER_MAX_DEPTH = max_depth
    if include_patterns is not None:
        INCLUDE_PATTERNS = include_patterns
    if exclude_patterns is not None:
        EXCLUDE_PATTERNS = exclude_patterns
    if output_mode is not None:
        OUTPUT_MODE = output_mode
    if output_format is not None:
        OUTPUT_FORMAT = output_format
    if exclude_system is not None:
        EXCLUDE_SYSTEM = exclude_system

    # Default filename based on format
    if output_filename is None:
        ext = 'jsonl' if OUTPUT_FORMAT == 'jsonl' else 'json'
        output_filename = f'network_export.{ext}'

    # Reset and serialize
    _reset_graph()
    root = op(root_path)
    operator_tree = serialize_op(root)

    # Detect templates (modifies tree in-place)
    templates = _detect_templates(operator_tree) if operator_tree else {}

    # Generate metadata
    meta = _generate_meta(operator_tree, _graph_edges) if operator_tree else {}

    # Build structured output
    export_data = {
        '_meta': meta,
        'graph': _graph_edges,
    }
    if templates:
        export_data['templates'] = templates
    export_data['operators'] = operator_tree

    output_path = project.folder + '/' + output_filename

    if OUTPUT_FORMAT == 'jsonl':
        # JSONL: first line is meta+graph+templates, then one line per operator
        ops = flatten_ops(operator_tree) if operator_tree else []
        with open(output_path, 'w') as f:
            header = {'_meta': meta, 'graph': _graph_edges}
            if templates:
                header['templates'] = templates
            f.write(json.dumps(header, default=str) + '\n')
            for entry in ops:
                f.write(json.dumps(entry, default=str) + '\n')
        size_kb = sum(len(json.dumps(e, default=str)) for e in ops) / 1024
        print(f"Exported {len(ops)} operators to: {output_path}")
    else:
        indent = None if OUTPUT_MODE == 'compact' else 2
        json_str = json.dumps(export_data, indent=indent, default=str)
        with open(output_path, 'w') as f:
            f.write(json_str)
        size_kb = len(json_str) / 1024
        print(f"Exported network to: {output_path}")

    print(f"Output size: {size_kb:.0f} KB")
    print(f"Mode: {OUTPUT_MODE}, Format: {OUTPUT_FORMAT}")

    if templates:
        template_ops = sum(1 for _ in _iter_ops(operator_tree) if 'template' in _)
        print(f"Templates: {len(templates)} (covering {template_ops} operators)")

    print(f"Graph edges: {len(_graph_edges)}")

    if EXCLUDE_SYSTEM:
        print(f"System paths excluded: {', '.join(_SYSTEM_PATHS)}")

    active = []
    if FILTER_FAMILIES:
        active.append('families=' + str(FILTER_FAMILIES))
    if FILTER_TYPES:
        active.append('types=' + str(FILTER_TYPES))
    if FILTER_PATH_PREFIX:
        active.append('path_prefix=' + FILTER_PATH_PREFIX)
    if INCLUDE_PATTERNS:
        active.append('include=' + str(INCLUDE_PATTERNS))
    if EXCLUDE_PATTERNS:
        active.append('exclude=' + str(EXCLUDE_PATTERNS))
    active.append('max_depth=' + str(FILTER_MAX_DEPTH))
    if active:
        print(f"Active filters: {', '.join(active)}")

    return export_data


def _iter_ops(node):
    """Iterate all operators in a tree (depth-first)."""
    yield node
    for child in node.get('children', []):
        yield from _iter_ops(child)


# When run directly (exec from Text DAT), use module-level config
export_network()
