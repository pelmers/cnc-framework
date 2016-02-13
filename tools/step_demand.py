#!/usr/bin/env python

import os
import re
from itertools import chain
from argparse import ArgumentParser
from pprint import pprint

from cncframework import graph, parser
from cncframework.events.eventgraph import EventGraph
from cncframework.inverse import find_step_inverses, find_blame_candidates, blame_deadlocks


def parse_ctx_params(ctxParams):
    '''
    Parse the context parameter expression (a string) into a sequence of
    (variable name, type) tuples.
    '''
    def read_statement(statement):
        # normalize whitespace
        statement = re.sub(r"\s+", " ", statement.strip())
        # first word is the type, (TODO: unless it's struct then it's two words)
        t, names = statement.split(' ', 1)
        return ((name, t) for name in names.split(', '))
    return chain.from_iterable(read_statement(s) for s in ctxParams.split(';') if s)


def input_ctx(ctx_vars):
    '''
    Ask on standard input for the values of context variables represented as
    (name, type) pairs. Return map of context var name -> value
    '''
    return {"ctx" + name: int(raw_input("Value for {}, type -1 if NaN: ".format(name)))
            for name, _ in ctx_vars}


def subs_ctx(ctx, key):
    '''
    Substitute given context values into the key expression of an item or step.
    '''
    for tag in key:
        print tag.expr.raw


def main():
    bin_name = os.environ['BIN_NAME'] or "CnCDemand"
    arg_parser = ArgumentParser(prog=bin_name,
                                description="Compute the demand-driven execution graph for specified output using provided input.")
    arg_parser.add_argument('specfile', help="CnC graph spec file")
    # arg_parser.add_argument('outitem', help="Output collection@tag")
    args = arg_parser.parse_args()
    # Parse graph spec
    graphAst = parser.cncGraphSpec.parseFile(args.specfile, parseAll=True)
    graphData = graph.CnCGraph("_", graphAst)

    pprint(graphData.ctxParams)
    ctx_vars = parse_ctx_params('\n'.join(graphData.ctxParams))
    ctx_values = input_ctx(ctx_vars)
    pprint(ctx_values)

    # TODO: substitute context parameters into all the functions
    inputs = []
    for input_item in graphData.finalizeFunction.inputItems:
        if input_item.kind == "ITEM":
            # TODO
            pprint(subs_ctx(ctx_values, input_item.key))
    pprint(inputs)
    for output_item in graphData.initFunction.outputItems:
        if input_item.kind == "ITEM":
            # TODO
            pass

    # TODO: find the inputs of the finalize step

    # TODO: solve backward with inverse functions

if __name__ == '__main__':
    main()
