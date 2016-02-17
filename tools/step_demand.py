#!/usr/bin/env python

import os
import re
from collections import deque
from itertools import chain
from argparse import ArgumentParser
from pprint import pprint
from sympy import sympify

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
def step_input_functions(stepFunction):
    """
    Given a StepFunction,
    return sympification of its input item and step expressions.
    """
    # TODO: ranged function should be okay
    inpts = {}
    for inpt in stepFunction.inputs:
        if inpt.kind in {"STEP", "ITEM"}:
            tag_list = inpt.key if inpt.kind == "ITEM" else inpt.tag
            inpts[inpt.collName] = tuple(
                sympify(t.expr)
                for (i, t) in enumerate(t for t in tag_list if not t.isRanged))
        elif inpt.kind == "IF":
            out_ref = inpt.refs[0]
            tag_list = out_ref.key if out_ref.kind == "ITEM" else out_ref.tag
            inpts[out_ref.collName] = tuple(
                Piecewise((sympify(t.expr),
                           sympify(inpt.rawCond.replace('@', 'arg').replace('#', 'ctx'))))
                for (i, t) in enumerate(t for t in tag_list if not t.isRanged))
    return inpts

# TODO: cache this
def step_output_functions(stepFunction):
    """
    Given a StepFunction,
    return sympification of its output item and step expressions.
    """
    # TODO: ranged function should be okay
    outputs = {}
    for output in stepFunction.outputs:
        if output.kind in {"STEP", "ITEM"}:
            tag_list = output.key if output.kind == "ITEM" else output.tag
            outputs[output.collName] = tuple(
                sympify(t.expr)
                for (i, t) in enumerate(t for t in tag_list if not t.isRanged))
        elif output.kind == "IF":
            out_ref = output.refs[0]
            tag_list = out_ref.key if out_ref.kind == "ITEM" else out_ref.tag
            outputs[out_ref.collName] = tuple(
                Piecewise((sympify(t.expr),
                           sympify(output.rawCond.replace('@', 'arg').replace('#', 'ctx'))))
                for (i, t) in enumerate(t for t in tag_list if not t.isRanged))
    return outputs


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

    print "Demand set:"
    pprint([(c, tuple_to_dict(c, t)) for c, t in demand])

    def satisfy(stepOrItem, tag):
        # If it's a step, then add it to the run set and BFS satisfy on its products until demand is empty.
        # If it's an item, then add it to the compute set.
        all_steps = {graphData.initFunction.collName,
                     graphData.finalizeFunction.collName}.union(graphData.stepFunctions)
        que = deque([(stepOrItem, tag)])
        while len(que) != 0 and len(demand) != 0:
            stepOrItem, tag = que.popleft()
            tag_tuple = dict_to_tuple(stepOrItem, tag)
            if stepOrItem in all_steps:
                run.add((stepOrItem, tag_tuple))
                data = (graphData.stepFunctions[stepOrItem] if stepOrItem in graphData.stepFunctions
                        else graphData.initFunction if stepOrItem == graphData.initFunction.collName
                        else graphData.finalizeFunction)
                outputs = step_output_functions(data)
                for coll, tag_exprs in outputs.items():
                    evaluated = tuple(expr.subs(tag) for expr in tag_exprs)
                    que.append((coll, tuple_to_dict(coll, evaluated)))
            else:
                # It's an item, add to compute set and remove from demand set.
                coll_tag = (stepOrItem, tag_tuple)
                compute.add(coll_tag)
                demand.discard(coll_tag)

    satisfy(graphData.initFunction.collName, {})
    while len(demand) > 0:
        for item in demand:
            coll, tag = item
            candidates = find_blame_candidates(coll, tag, graphData)
            if len(candidates) > 1:
                print "Ambiguous resolution for {}@{}:".format(coll, tag)
                pprint(candidates)
                return
            elif len(candidates) < 1:
                print "Cannot satisfy demand for {}@{}".format(coll, tag)
                return
            else:
                step, step_tag = candidates.items()[0]
                satisfy(step, tuple_to_dict(step_tag))
        break
    pprint(("Compute", compute))
    pprint(("Run", run))
    # TODO: make a graph from these sets
    # idea: fake event log?

if __name__ == '__main__':
    main()
