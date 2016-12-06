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
import sys

import graphviz
import graphviz.files

from ._discover import findMachines


def _gvquote(s):
    return '"{}"'.format(s.replace('"', r'\"'))


def _gvhtml(s):
    return '<{}>'.format(s)


def elementMaker(name, *children, **attrs):
    """
    Construct a string from the HTML element description.
    """
    formattedAttrs = ' '.join('{}={}'.format(key, _gvquote(str(value)))
                              for key, value in sorted(attrs.items()))
    formattedChildren = ''.join(children)
    return u'<{name} {attrs}>{children}</{name}>'.format(
        name=name,
        attrs=formattedAttrs,
        children=formattedChildren)


def tableMaker(inputLabel, outputLabels, port, _E=elementMaker):
    """
    Construct an HTML table to label a state transition.
    """
    colspan = {}
    if outputLabels:
        colspan['colspan'] = str(len(outputLabels))

    inputLabelCell = _E("td",
                        _E("font",
                           inputLabel,
                           face="menlo-italic"),
                        color="purple",
                        port=port,
                        **colspan)

    pointSize = {"point-size": "9"}
    outputLabelCells = [_E("td",
                           _E("font",
                              outputLabel,
                              **pointSize),
                           color="pink")
                        for outputLabel in outputLabels]

    rows = [_E("tr", inputLabelCell)]

    if outputLabels:
        rows.append(_E("tr", *outputLabelCells))

    return _E("table", *rows)


def makeDigraph(automaton, inputAsString=repr,
                outputAsString=repr,
                stateAsString=repr):
    """
    Produce a L{graphviz.Digraph} object from an automaton.
    """
    digraph = graphviz.Digraph(graph_attr={'pack': 'true',
                                           'dpi': '100'},
                               node_attr={'fontname': 'Menlo'},
                               edge_attr={'fontname': 'Menlo'})

    for state in automaton.states():
        if state is automaton.initialState:
            stateShape = "bold"
            fontName = "Menlo-Bold"
        else:
            stateShape = ""
            fontName = "Menlo"
        digraph.node(stateAsString(state),
                     fontame=fontName,
                     shape="ellipse",
                     style=stateShape,
                     color="blue")
    for n, eachTransition in enumerate(automaton.allTransitions()):
        inState, inputSymbol, outState, outputSymbols = eachTransition
        thisTransition = "t{}".format(n)
        inputLabel = inputAsString(inputSymbol)

        port = "tableport"
        table = tableMaker(inputLabel, [outputAsString(outputSymbol)
                                        for outputSymbol in outputSymbols],
                           port=port)

        digraph.node(thisTransition,
                     label=_gvhtml(table), margin="0.2", shape="none")

        digraph.edge(stateAsString(inState),
                     '{}:{}:w'.format(thisTransition, port),
                     arrowhead="none")
        digraph.edge('{}:{}:e'.format(thisTransition, port),
                     stateAsString(outState))

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
        '--dot-directory',
        '-d',
        help="Where to write out .dot files.",
        default=".h2_visualize"
    )
    argument_parser.add_argument(
        '--image-directory',
        '-i',
        help="Where to write out image files.",
        default=".h2_visualize"
    )
    argument_parser.add_argument(
        '--image-type',
        '-t',
        help="The image format.",
        choices=graphviz.files.FORMATS,
        default='png'
    )
    argument_parser.add_argument(
        '--view',
        '-v',
        help="View rendered graphs with default image viewer",
        default=False,
        action="store_true"
    )
    args = argument_parser.parse_args(argv)

    explicitly_save_dot = (
        args.dot_directory and (
            not args.image_directory or
            args.image_directory != args.dot_directory
        )
    )

    for fqpn, machine in _findMachines(args.fqpn):
        print(fqpn, '...discovered')

        digraph = machine.asDigraph()

        if explicitly_save_dot:
            digraph.save(filename="{}.dot".format(fqpn),
                         directory=args.dot_directory)
            print(fqpn, "...wrote dot into", args.dot_directory)

        if args.image_directory:
            delete_dot = not args.dot_directory or explicitly_save_dot
            digraph.format = args.image_type
            digraph.render(filename="{}.dot".format(fqpn),
                           directory=args.image_directory,
                           view=args.view,
                           cleanup=delete_dot)
            if delete_dot:
                msg = "...wrote image into"
            else:
                msg = "...wrote image and dot into"
            print(fqpn, msg, args.image_directory)
