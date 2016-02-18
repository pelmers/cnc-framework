#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
from collections import deque
from itertools import chain
from argparse import ArgumentParser
from pprint import pprint
from sympy import sympify, Piecewise

from cncframework import graph, parser
import cncframework.events.actions as actions
from cncframework.events.eventgraph import EventGraph
from cncframework.inverse import find_step_inverses, find_blame_candidates, find_collNames


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
    Substitute given context values into the key expression of an item or step and simplify.
    '''
    return tuple(sympify(tag.expr.raw.replace("#", "ctx")).subs(ctx) for tag in key)


# TODO: cache this
def step_io_functions(stepFunction, io):
    """
    Given a StepFunction,
    return sympification of its io item and step expressions, io ∈ {inputs, outputs}.
    """
    # TODO: ranged function should be okay
    assert io in {'inputs', 'outputs'}
    iodict = getattr(stepFunction, io)
    ios = {coll: [] for coll in find_collNames(iodict)}
    for io in iodict:
        if io.kind in {"STEP", "ITEM"}:
            tag_list = io.key if io.kind == "ITEM" else io.tag
            ios[io.collName].append(tuple(
                sympify(t.expr)
                for (i, t) in enumerate(t for t in tag_list if not t.isRanged)))
        elif io.kind == "IF":
            out_ref = io.refs[0]
            tag_list = out_ref.key if out_ref.kind == "ITEM" else out_ref.tag
            ios[out_ref.collName].append(tuple(
                Piecewise((sympify(t.expr),
                           sympify(io.rawCond.replace('@', 'arg').replace('#', 'ctx'))))
                for (i, t) in enumerate(t for t in tag_list if not t.isRanged)))
    return ios


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

    ctx_vars = parse_ctx_params('\n'.join(graphData.ctxParams))
    ctx_values = input_ctx(ctx_vars)

    run = set()
    demand = {(input_item.collName, subs_ctx(ctx_values, input_item.key))
              for input_item in graphData.finalizeFunction.inputItems
              if input_item.kind == "ITEM"}
    compute = {(output_item.collName, subs_ctx(ctx_values, output_item.key))
               for output_item in graphData.initFunction.outputItems
               if output_item.kind == "ITEM"}

    def satisfy(stepOrItem, tag):
        # If it's a step, then add it to the run set and BFS satisfy on its products until demand is empty.
        # If it's an item, then add it to the compute set.
        def tuple_to_dict(coll, tag):
            # Convert a tag tuple of values to a tag dictionary to map keys -> values
            if coll in graphData.stepFunctions:
                return dict(zip(graphData.stepFunctions[coll].tag, tag))
            else:
                return dict(zip(graphData.itemDeclarations[coll].key, tag))

        def dict_to_tuple(coll, tag):
            # Undo the other function
            if coll in graphData.stepFunctions:
                return tuple(tag[t] for t in graphData.stepFunctions[coll].tag)
            elif coll in graphData.itemDeclarations:
                return tuple(tag[t] for t in graphData.itemDeclarations[coll].key)
            else:
                return ()

        all_steps = {graphData.initFunction.collName: graphData.initFunction,
                     graphData.finalizeFunction.collName: graphData.finalizeFunction}
        all_steps.update(graphData.stepFunctions)
        que = deque([(stepOrItem, tag)])
        while len(que) != 0 and len(demand) != 0:
            stepOrItem, tag = que.popleft()
            tag_tuple = dict_to_tuple(stepOrItem, tag)
            if stepOrItem in all_steps:
                run.add((stepOrItem, tag_tuple))
                data = all_steps[stepOrItem]
                outputs = step_io_functions(data, 'outputs')
                for coll, tag_exprses in outputs.items():
                    for tag_exprs in tag_exprses:
                        evaluated = tuple(expr.subs(tag) for expr in tag_exprs)
                        que.append((coll, tuple_to_dict(coll, evaluated)))
            else:
                # It's an item, add to compute set and remove from demand set.
                coll_tag = (stepOrItem, tag_tuple)
                compute.add(coll_tag)
                demand.discard(coll_tag)

    satisfy(graphData.initFunction.collName, {})
    while len(demand) > 0:
        # Arbitrarily pick an element from the demand set.
        for item in demand:
            break
        coll, tag = item
        candidates = find_blame_candidates(coll, tag, graphData)
        if len(candidates) > 1:
            print "Ambiguous resolution for {}@{}:".format(coll, tag)
            pprint(candidates)
            # TODO: auto-resolve?
            step = raw_input("Can you help? ")
            step_tag = candidates[step]
        elif len(candidates) < 1:
            print "Cannot satisfy demand for {}@{}".format(coll, tag)
            return
        else:
            step, step_tag = candidates.items()[0]
        satisfy(step, step_tag)
        # Add the uncomputed inputs of the prescribed set to the demand set.
        for coll, in_exprses in step_io_functions(graphData.stepFunctions[step], 'inputs').items():
            for in_exprs in in_exprses:
                evaluated = tuple(expr.subs(step_tag) for expr in in_exprs)
                evaluated_tuple = (coll, evaluated)
                if evaluated_tuple not in compute:
                    demand.add(evaluated_tuple)

    pprint(("Compute", compute))
    pprint(("Run", run))
    # TODO: make a graph from these sets
    # idea: fake event log?

if __name__ == '__main__':
    main()
