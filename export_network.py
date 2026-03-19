"""
Export TouchDesigner network to JSON using TDJSON for parameter serialization.

Run from a Text DAT or paste into the textport:
    exec(op('export_network').text)

Outputs to: [project folder]/network_export.json

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

# ─── Filter Configuration ─────────────────────────────────────────────
# Set these to control what gets exported. None or [] means "no filter".

FILTER_FAMILIES = None          # e.g. ['TOP', 'CHOP', 'SOP']
FILTER_TYPES = None             # e.g. ['moviefilein', 'null', 'geo']
FILTER_PATH_PREFIX = None       # e.g. '/project1/fx'
FILTER_MAX_DEPTH = 6            # max recursion depth from root
INCLUDE_PATTERNS = None         # e.g. ['render*', '*_out'] (fnmatch on op name)
EXCLUDE_PATTERNS = None         # e.g. ['__*', 'local*'] (fnmatch on op name)

# ─── End Configuration ─────────────────────────────────────────────────

try:
    import TDJSON
    HAS_TDJSON = True
except ImportError:
    HAS_TDJSON = False


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

    # Use TDJSON to serialize each parameter page
    if HAS_TDJSON:
        try:
            pages = {}
            for page in operator.pages:
                page_data = TDJSON.serializeTDData(page, verbose=True)
                if page_data:
                    pages[page.name] = page_data
            if pages:
                node['pages'] = pages
        except:
            pass

    # Connections: inputs
    try:
        inputs = []
        for i, inp in enumerate(operator.inputs):
            if inp is not None:
                inputs.append({
                    'index': i,
                    'path': inp.path,
                    'name': inp.name,
                })
        if inputs:
            node['inputs'] = inputs
    except:
        pass

    # Connections: outputs
    try:
        outputs = []
        for i, out in enumerate(operator.outputs):
            if out is not None:
                outputs.append({
                    'index': i,
                    'path': out.path,
                    'name': out.name,
                })
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


# ─── Main ──────────────────────────────────────────────────────────────

def export_network(root_path='/', output_filename='network_export.json',
                   families=None, types=None, path_prefix=None,
                   max_depth=None, include_patterns=None,
                   exclude_patterns=None):
    """Export the operator network to JSON with optional filtering.

    Can be called as a function for programmatic use, or the script
    can be run directly with the module-level configuration variables.

    Args:
        root_path: Starting operator path (default: '/')
        output_filename: Output filename in project folder
        families: List of operator families, e.g. ['TOP', 'CHOP']
        types: List of operator types, e.g. ['moviefilein', 'null']
        path_prefix: Only export ops under this path
        max_depth: Max recursion depth (default: 6)
        include_patterns: fnmatch patterns for operator names to include
        exclude_patterns: fnmatch patterns for operator names to exclude

    Returns:
        The serialized data dict.
    """
    global FILTER_FAMILIES, FILTER_TYPES, FILTER_PATH_PREFIX
    global FILTER_MAX_DEPTH, INCLUDE_PATTERNS, EXCLUDE_PATTERNS

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

    root = op(root_path)
    data = serialize_op(root)

    output_path = project.folder + '/' + output_filename
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)

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

    size_kb = len(json.dumps(data, default=str)) / 1024
    print(f"Exported network to: {output_path}")
    print(f"Total JSON size: {size_kb:.0f} KB")
    if active:
        print(f"Active filters: {', '.join(active)}")

    return data


# When run directly (exec from Text DAT), use module-level config
root = op('/')
data = serialize_op(root)

output_path = project.folder + '/network_export.json'
with open(output_path, 'w') as f:
    json.dump(data, f, indent=2, default=str)

print(f"Exported network to: {output_path}")
print(f"Total JSON size: {len(json.dumps(data, default=str)) / 1024:.0f} KB")
if has_active_filters():
    filters = []
    if FILTER_FAMILIES:
        filters.append(f"families={FILTER_FAMILIES}")
    if FILTER_TYPES:
        filters.append(f"types={FILTER_TYPES}")
    if FILTER_PATH_PREFIX:
        filters.append(f"path_prefix={FILTER_PATH_PREFIX}")
    if INCLUDE_PATTERNS:
        filters.append(f"include={INCLUDE_PATTERNS}")
    if EXCLUDE_PATTERNS:
        filters.append(f"exclude={EXCLUDE_PATTERNS}")
    print(f"Active filters: {', '.join(filters)}")
