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

# ─── Filter Configuration ─────────────────────────────────────────────
# Set these to control what gets exported. None or [] means "no filter".

FILTER_FAMILIES = None          # e.g. ['TOP', 'CHOP', 'SOP']
FILTER_TYPES = None             # e.g. ['moviefilein', 'null', 'geo']
FILTER_PATH_PREFIX = None       # e.g. '/project1/fx'
FILTER_MAX_DEPTH = 6            # max recursion depth from root
INCLUDE_PATTERNS = None         # e.g. ['render*', '*_out'] (fnmatch on op name)
EXCLUDE_PATTERNS = None         # e.g. ['__*', 'local*'] (fnmatch on op name)

# ─── End Configuration ─────────────────────────────────────────────────


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
    # Operator is at or under the prefix
    if op_path.startswith(prefix + '/') or op_path == prefix:
        return True
    # Prefix is deeper than this operator (children might match)
    if prefix.startswith(op_path + '/') or prefix == op_path:
        return True
    return False


def has_active_filters():
    """Return True if any filter other than max_depth is set."""
    return any([FILTER_FAMILIES, FILTER_TYPES, FILTER_PATH_PREFIX,
                INCLUDE_PATTERNS, EXCLUDE_PATTERNS])


# ─── Parameter Serialization ─────────────────────────────────────────

# Parameter styles that are never useful to export
_SKIP_STYLES = {'Pulse', 'Header'}


def serialize_par(par):
    """Serialize a single non-default parameter.

    Returns a dict with the parameter value (and expression/mode if
    not in constant mode). Returns None for parameters that should
    be skipped (pulses, headers, read-only with no expression).
    """
    try:
        if par.isDefault:
            return None
    except:
        return None

    # Skip pulse buttons, headers, and read-only params with no expression
    try:
        if par.style in _SKIP_STYLES:
            return None
        if par.readOnly and par.mode == ParMode.CONSTANT:
            return None
    except:
        pass

    result = {}

    try:
        mode = par.mode
        if mode == ParMode.EXPRESSION:
            result['expr'] = par.expr
        elif mode == ParMode.EXPORT:
            # Export mode: parameter is driven by an export CHOP/DAT
            try:
                result['export'] = par.exportSource.path if par.exportSource else True
            except:
                result['export'] = True
        elif mode == ParMode.BIND:
            # Bind mode: parameter references another parameter
            try:
                result['bind'] = par.bindExpr
            except:
                result['bind'] = True
        else:
            # Constant mode -- just store the value
            result['val'] = par.val
    except:
        # Fallback: try to get any value
        try:
            result['val'] = par.val
        except:
            return None

    if not result:
        return None

    return result


def serialize_par_full(par):
    """Serialize a non-default parameter with full metadata.

    Includes style (type), label, and range info in addition to value.
    Used by OUTPUT_MODE = 'full'.
    """
    base = serialize_par(par)
    if base is None:
        return None

    try:
        base['style'] = par.style
    except:
        pass
    try:
        if par.label and par.label != par.name:
            base['label'] = par.label
    except:
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
            data = serialize_fn(par)
            if data is not None:
                # In compact mode, flatten constant-mode params to bare values
                if OUTPUT_MODE == 'compact' and list(data.keys()) == ['val']:
                    params[par.name] = data['val']
                else:
                    params[par.name] = data
    except:
        pass

    return params if params else None


# ─── Operator Serialization ──────────────────────────────────────────

def serialize_op(operator, depth=0):
    """Serialize an operator and its children recursively.

    When filters are active, containers are only included if they have
    matching descendants. This keeps the hierarchy readable while still
    trimming the output aggressively.
    """
    if depth > FILTER_MAX_DEPTH:
        return None

    if not path_could_contain_prefix(operator.path):
        return None

    node = {
        'path': operator.path,
        'name': operator.name,
        'type': operator.type,
        'family': operator.family,
    }

    # Parameters (non-default only)
    params = serialize_params(operator)
    if params:
        node['params'] = params

    # Connections: inputs (compact format -- just paths)
    try:
        inputs = []
        for i, inp in enumerate(operator.inputs):
            if inp is not None:
                inputs.append(inp.path)
        if inputs:
            node['inputs'] = inputs
    except:
        pass

    # Connections: outputs (compact format -- just paths)
    try:
        outputs = []
        for i, out in enumerate(operator.outputs):
            if out is not None:
                outputs.append(out.path)
        if outputs:
            node['outputs'] = outputs
    except:
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
    except:
        pass

    # Filtering logic:
    # - If no filters are active, include everything (original behavior)
    # - Containers are included only if they have matching children
    # - Leaf ops are included only if they pass all filters
    if has_active_filters():
        if is_container:
            if 'children' not in node or not node['children']:
                # Container with no matching descendants -- check if it matches on its own
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


# ─── Main ──────────────────────────────────────────────────────────────

def export_network(root_path='/', output_filename=None,
                   families=None, types=None, path_prefix=None,
                   max_depth=None, include_patterns=None,
                   exclude_patterns=None, output_mode=None,
                   output_format=None):
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

    Returns:
        The serialized data (dict for json, list for jsonl).
    """
    global FILTER_FAMILIES, FILTER_TYPES, FILTER_PATH_PREFIX
    global FILTER_MAX_DEPTH, INCLUDE_PATTERNS, EXCLUDE_PATTERNS
    global OUTPUT_MODE, OUTPUT_FORMAT

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

    # Default filename based on format
    if output_filename is None:
        ext = 'jsonl' if OUTPUT_FORMAT == 'jsonl' else 'json'
        output_filename = f'network_export.{ext}'

    root = op(root_path)
    data = serialize_op(root)

    output_path = project.folder + '/' + output_filename

    if OUTPUT_FORMAT == 'jsonl':
        ops = flatten_ops(data) if data else []
        with open(output_path, 'w') as f:
            for entry in ops:
                f.write(json.dumps(entry, default=str) + '\n')
        size_kb = sum(len(json.dumps(e, default=str)) for e in ops) / 1024
        print(f"Exported {len(ops)} operators to: {output_path}")
    else:
        indent = None if OUTPUT_MODE == 'compact' else 2
        json_str = json.dumps(data, indent=indent, default=str)
        with open(output_path, 'w') as f:
            f.write(json_str)
        size_kb = len(json_str) / 1024
        print(f"Exported network to: {output_path}")

    print(f"Output size: {size_kb:.0f} KB")
    print(f"Mode: {OUTPUT_MODE}, Format: {OUTPUT_FORMAT}")

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

    return ops if OUTPUT_FORMAT == 'jsonl' else data


# When run directly (exec from Text DAT), use module-level config
root = op('/')
data = serialize_op(root)

if OUTPUT_FORMAT == 'jsonl':
    _ops = flatten_ops(data) if data else []
    _output_path = project.folder + '/network_export.jsonl'
    with open(_output_path, 'w') as f:
        for _entry in _ops:
            f.write(json.dumps(_entry, default=str) + '\n')
    _size_kb = sum(len(json.dumps(e, default=str)) for e in _ops) / 1024
    print(f"Exported {len(_ops)} operators to: {_output_path}")
else:
    _indent = None if OUTPUT_MODE == 'compact' else 2
    _json_str = json.dumps(data, indent=_indent, default=str)
    _output_path = project.folder + '/network_export.json'
    with open(_output_path, 'w') as f:
        f.write(_json_str)
    _size_kb = len(_json_str) / 1024
    print(f"Exported network to: {_output_path}")

print(f"Output size: {_size_kb:.0f} KB")
print(f"Mode: {OUTPUT_MODE}, Format: {OUTPUT_FORMAT}")

if has_active_filters():
    _filters = []
    if FILTER_FAMILIES:
        _filters.append(f"families={FILTER_FAMILIES}")
    if FILTER_TYPES:
        _filters.append(f"types={FILTER_TYPES}")
    if FILTER_PATH_PREFIX:
        _filters.append(f"path_prefix={FILTER_PATH_PREFIX}")
    if INCLUDE_PATTERNS:
        _filters.append(f"include={INCLUDE_PATTERNS}")
    if EXCLUDE_PATTERNS:
        _filters.append(f"exclude={EXCLUDE_PATTERNS}")
    print(f"Active filters: {', '.join(_filters)}")
