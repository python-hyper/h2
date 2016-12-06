# -*- coding: utf-8 -*-
"""
State Machine Visualizer
~~~~~~~~~~~~~~~~~~~~~~~~

This code provides a module that can use graphviz to visualise the state
machines included in hyper-h2. These visualisations can be used as part of the
documentation of hyper-h2, and as a reference material to understand how the
state machines function.

The code in this module is heavily inspired by code in Automat, which can be
found here: https://github.com/glyph/automat. For details on the licensing of
Automat, please see the NOTICES.visualizer file in this folder.

This module is very deliberately not shipped with the rest of hyper-h2. This is
because it is of minimal value to users who are installing hyper-h2: its use
is only really for the developers of hyper-h2.
"""
from __future__ import print_function
import argparse
import collections
import sys

import graphviz
import graphviz.files

import h2.connection
import h2.stream


StateMachine = collections.namedtuple(
    'StateMachine', ['fqdn', 'machine', 'states', 'inputs', 'transitions']
)


# This is all the state machines we currently know about and will render.
# If any new state machines are added, they should be inserted here.
STATE_MACHINES = [
    StateMachine(
        fqdn='h2.connection.H2ConnectionStateMachine',
        machine=h2.connection.H2ConnectionStateMachine,
        states=h2.connection.ConnectionState,
        inputs=h2.connection.ConnectionInputs,
        transitions=h2.connection.H2ConnectionStateMachine._transitions,
    ),
    StateMachine(
        fqdn='h2.stream.H2StreamStateMachine',
        machine=h2.stream.H2StreamStateMachine,
        states=h2.stream.StreamState,
        inputs=h2.stream.StreamInputs,
        transitions=h2.stream._transitions,
    ),
]


def enum_member_name(state):
    """
    All enum member names have the form <EnumClassName>.<EnumMemberName>. For
    our rendering we only want the member name, so we take their representation
    and split it.
    """
    return str(state).split('.', 1)[1]


def function_name(func):
    """
    Given a side-effect function, return its string name.
    """
    return func.__name__


def build_digraph(state_machine):
    """
    Produce a L{graphviz.Digraph} object from a state machine.
    """
    digraph = graphviz.Digraph(node_attr={'fontname': 'Menlo'},
                               edge_attr={'fontname': 'Menlo'})

    # First, add the states as nodes.
    seen_first_state = False
    for state in state_machine.states:
        if not seen_first_state:
            state_shape = "bold"
            font_name = "Menlo-Bold"
        else:
            state_shape = ""
            font_name = "Menlo"
        digraph.node(enum_member_name(state),
                     fontame=font_name,
                     shape="ellipse",
                     style=state_shape,
                     color="blue")
        seen_first_state = True

    for n, transition in enumerate(state_machine.transitions.items()):
        initial_state, event = transition[0]
        side_effect, final_state = transition[1]
        input_label = enum_member_name(event)

        if side_effect is not None:
            input_label = "{} ({})".format(
                input_label, function_name(side_effect)
            )

        digraph.edge(
            enum_member_name(initial_state),
            enum_member_name(final_state),
            label=input_label,
        )

    return digraph


def main():
    """
    Renders all the state machines in hyper-h2 into images.
    """
    program_name = sys.argv[0]
    argv = sys.argv[1:]

    description = """
    Visualize hyper-h2 state machines as graphs.
    """
    epilog = """
    You must have the graphviz tool suite installed.  Please visit
    http://www.graphviz.org for more information.
    """

    argument_parser = argparse.ArgumentParser(
        prog=program_name,
        description=description,
        epilog=epilog
    )
    argument_parser.add_argument(
        '--image-directory',
        '-i',
        help="Where to write out image files.",
        default=".h2_visualize"
    )
    argument_parser.add_argument(
        '--view',
        '-v',
        help="View rendered graphs with default image viewer",
        default=False,
        action="store_true"
    )
    args = argument_parser.parse_args(argv)

    for state_machine in STATE_MACHINES:
        print(state_machine.fqdn, '...discovered')

        digraph = build_digraph(state_machine)

        if args.image_directory:
            digraph.format = "png"
            digraph.render(filename="{}.dot".format(state_machine.fqdn),
                           directory=args.image_directory,
                           view=args.view,
                           cleanup=True)
            print(state_machine.fqdn, "...wrote image into", args.image_directory)


if __name__ == '__main__':
    main()
