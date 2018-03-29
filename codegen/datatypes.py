import os.path as opath
import textwrap
from io import StringIO

from codegen.utils import (PlotlyNode,
                           format_and_write_source_py)


def get_typing_type(plotly_type, array_ok=False):
    """
    Get Python type corresponding to a valType string from the plotly schema

    Parameters
    ----------
    plotly_type : str
        a plotly datatype string
    array_ok : bool
        Whether lists/arrays are permitted
    Returns
    -------
    str
        Python type string
    """
    if plotly_type in ('data_array', 'info_array', 'colorlist'):
        pytype = 'List'
    elif plotly_type in ('string', 'color', 'colorscale', 'subplotid'):
        pytype = 'str'
    elif plotly_type in ('enumerated', 'flaglist', 'any'):
        pytype = 'Any'
    elif plotly_type in ('number', 'angle'):
        pytype = 'Number'
    elif plotly_type == 'integer':
        pytype = 'int'
    elif plotly_type == 'boolean':
        pytype = 'bool'
    else:
        raise ValueError('Unknown plotly type: %s' % plotly_type)

    if array_ok:
        return f'Union[{pytype}, List[{pytype}]]'
    else:
        return pytype


def build_datatype_py(node):
    """
    Build datatype (graph_objs) class source code string for a datatype
    PlotlyNode

    Parameters
    ----------
    node : PlotlyNode
        The datatype node (node.is_datatype must evaluate to true) for which
        to build the datatype class
    Returns
    -------
    str
        String containing source code for the datatype class definition
    """

    # Validate inputs
    # ---------------
    assert node.is_compound

    # Extract node properties
    # -----------------------
    undercase = node.name_undercase
    datatype_class = node.name_datatype_class
    literal_nodes = [n for n in node.child_literals if
                     n.plotly_name in ['type']]

    # Initialze source code buffer
    # ----------------------------
    buffer = StringIO()

    # Imports
    # -------
    buffer.write('from typing import *\n')
    buffer.write('from numbers import Number\n')
    buffer.write(
        f'from plotly.basedatatypes import {node.name_base_datatype}\n')

    # ### Import type's validator package with rename ###
    buffer.write(
        f'from plotly.validators{node.parent_dotpath_str} import '
        f'{undercase} as v_{undercase}\n')

    # ### Import type's graph_objs package with rename ###
    # If type has any compound children, then import that package that
    # holds them
    if node.child_compound_datatypes:
        buffer.write(
            f'from plotly.graph_objs{node.parent_dotpath_str} import '
            f'{undercase} as d_{undercase}\n')

    # Write class definition
    # ----------------------
    buffer.write(f"""

class {datatype_class}({node.name_base_datatype}):\n""")

    # ### Property definitions ###
    child_datatype_nodes = node.child_datatypes

    subtype_nodes = child_datatype_nodes
    for subtype_node in subtype_nodes:
        sub_datatype_class = subtype_node.name_datatype_class
        if subtype_node.is_array_element:
            prop_type = f'Tuple[d_{undercase}.{sub_datatype_class}]'
        elif subtype_node.is_compound:
            prop_type = f'd_{undercase}.{sub_datatype_class}'
        else:
            prop_type = get_typing_type(subtype_node.datatype)

        # #### Get property description ####
        raw_description = subtype_node.description
        property_description = '\n'.join(
            textwrap.wrap(raw_description,
                          initial_indent=' ' * 8,
                          subsequent_indent=' ' * 8,
                          width=79 - 8))

        # # #### Get validator description ####
        validator = subtype_node.get_validator_instance()
        if validator:
            validator_description = reindent_validator_description(
                validator, 4)

            # #### Combine to form property docstring ####
            if property_description.strip():
                property_docstring = f"""{property_description}
    
        {validator_description}"""
            else:
                property_docstring = f"        {validator_description}"
        else:
            property_docstring = property_description

        # #### Write get property ####
        buffer.write(f"""\

    # {subtype_node.name_property}
    # {'-' * len(subtype_node.name_property)}
    @property
    def {subtype_node.name_property}(self) -> {prop_type}:
        \"\"\"
{property_docstring}
        \"\"\"
        return self['{subtype_node.name_property}']""")

        # #### Write set property ####
        buffer.write(f"""

    @{subtype_node.name_property}.setter
    def {subtype_node.name_property}(self, val):
        self['{subtype_node.name_property}'] = val\n""")

        # ### Literals ###
    for literal_node in literal_nodes:
        buffer.write(f"""\

    # {literal_node.name_property}
    # {'-' * len(literal_node.name_property)}
    @property
    def {literal_node.name_property}(self) -> {prop_type}:
        return self._props['{literal_node.name_property}']\n""")

    # ### Private properties descriptions ###
    buffer.write(f"""

    # property parent name
    # --------------------
    @property
    def _parent_path_str(self) -> str:
        return '{node.parent_path_str}'

    # Self properties description
    # ---------------------------
    @property
    def _prop_descriptions(self) -> str:
        return \"\"\"\\""")

    buffer.write(node.get_constructor_params_docstring(indent=8))

    buffer.write(f"""
        \"\"\"""")

    # ### Constructor ###
    buffer.write(f"""
    def __init__(self""")

    add_constructor_params(buffer, subtype_nodes)
    header = f"Construct a new {datatype_class} object"
    add_docstring(buffer, node, header=header)

    buffer.write(f"""
        super().__init__('{node.name_property}', **kwargs)

        # Initialize validators
        # ---------------------""")
    for subtype_node in subtype_nodes:
        sub_name = subtype_node.name_property
        sub_validator = subtype_node.name_validator_class
        buffer.write(f"""
        self._validators['{sub_name}'] = v_{undercase}.{sub_validator}()""")

    buffer.write(f"""

        # Populate data dict with properties
        # ----------------------------------""")
    for subtype_node in subtype_nodes:
        buffer.write(f"""
        self.{subtype_node.name_property} = {subtype_node.name_property}""")

    # ### Literals ###
    literal_nodes = [n for n in node.child_literals if
                     n.plotly_name in ['type']]
    if literal_nodes:
        buffer.write(f"""

        # Read-only literals
        # ------------------""")
        for literal_node in literal_nodes:
            lit_name = literal_node.name_property
            lit_val = literal_node.node_data
            buffer.write(f"""
        self._props['{lit_name}'] = '{lit_val}'""")

    # Return source string
    # --------------------
    return buffer.getvalue()


def reindent_validator_description(validator, extra_indent):
    """
    Return validator description with modified indenting. The string that is
    returned has no leading indent, and the subsequent lines are indented by 4
    spaces (the default for validator descriptions) plus `extra_indent` spaces

    Parameters
    ----------
    validator : BaseValidator
        Validator from which to extract the description
    extra_indent : int
        Number of spaces of indent to add to subsequent lines (those after
        the first line). Validators description start with in indent of 4
        spaces

    Returns
    -------
    str
        Validator description string
    """
    # Remove leading indent and add extra spaces to subsequent indent
    return ('\n' + ' ' * extra_indent).join(
        validator.description().strip().split('\n'))


def add_constructor_params(buffer, subtype_nodes):
    """
    Write datatype constructor params to a buffer

    Parameters
    ----------
    buffer : StringIO
        Buffer to write to
    subtype_nodes : list of PlotlyNode
        List of datatype nodes to be written as constructor params
    Returns
    -------
    None
    """
    for i, subtype_node in enumerate(subtype_nodes):
        buffer.write(f""",
            {subtype_node.name_property}=None""")

    buffer.write(""",
            **kwargs""")
    buffer.write(f"""
        ):""")


def add_docstring(buffer, node, header):
    """
    Write docstring for a compound datatype node

    Parameters
    ----------
    buffer : StringIO
        Buffer to write to
    node : PlotlyNode
        Compound datatype plotly node for which to write docstring
    header :
        Top-level header for docstring that will preceded the input node's
        own description. Header should be < 71 characters long
    Returns
    -------

    """
    # Validate inputs
    # ---------------
    assert node.is_compound

    # Build wrapped description
    # -------------------------
    node_description = node.description
    if node_description:
        description_lines = textwrap.wrap(
            node_description,
            width=79-8,
            initial_indent=' ' * 8,
            subsequent_indent=' ' * 8)

        node_description = '\n'.join(description_lines) + '\n\n'

    # Write header and description
    # ----------------------------
    buffer.write(f"""
        \"\"\"
        {header}
        
{node_description}        Parameters
        ----------""")

    # Write parameter descriptions
    # ----------------------------
    buffer.write(node.get_constructor_params_docstring(
        indent=8))

    # Write return block and close docstring
    # --------------------------------------
    buffer.write(f"""

        Returns
        -------
        {node.name_datatype_class}
        \"\"\"""")


def write_datatype_py(outdir, node):
    """
    Build datatype (graph_objs) class source code and write to a file

    Parameters
    ----------
    outdir :
        Root outdir in which the graph_objs package should reside
    node :
        The datatype node (node.is_datatype must evaluate to true) for which
        to build the datatype class

    Returns
    -------
    None
    """
    # Generate source code
    # --------------------
    datatype_source = build_datatype_py(node)

    # Write file
    # ----------
    filepath = opath.join(outdir, 'graph_objs',
                          *node.parent_path_parts,
                          '_' + node.name_undercase + '.py')
    format_and_write_source_py(datatype_source, filepath)
