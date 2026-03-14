"""
Export TouchDesigner network to JSON using TDJSON for parameter serialization.

Run from a Text DAT or paste into the textport:
    exec(op('export_network').text)

Outputs to: [project folder]/network_export.json
"""

import json
import TDJSON

def serialize_op(operator, depth=0, max_depth=5):
	"""Serialize an operator and its children recursively."""
	if depth > max_depth:
		return None

	node = {
		'path': operator.path,
		'name': operator.name,
		'type': operator.type,
		'family': operator.family,
	}

	# Use TDJSON to serialize each parameter page
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
	try:
		kids = operator.children
		if kids:
			node['children'] = []
			for child in sorted(kids, key=lambda c: c.name):
				child_data = serialize_op(child, depth + 1, max_depth)
				if child_data:
					node['children'].append(child_data)
	except:
		pass

	return node

# Serialize from project root
root = op('/')
data = serialize_op(root, max_depth=6)

# Write to file
output_path = project.folder + '/network_export.json'
with open(output_path, 'w') as f:
	json.dump(data, f, indent=2, default=str)

print(f"Exported network to: {output_path}")
print(f"Total JSON size: {len(json.dumps(data, default=str)) / 1024:.0f} KB")
