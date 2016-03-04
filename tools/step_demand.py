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


class RangedExpr(object):
    # Arbitrary limit to prevent infinite looping if bounds don't meet.
    iter_limit = 100

    def __init__(self, ctx, tc, cond=None):
        assert tc.isRanged
        self.tc = tc
        self.start = subs_ctx(ctx, tc.start.raw)
        self.end = subs_ctx(ctx, tc.end.raw)
        self.cond = cond

    def subs(self, var_dict):
        """Substitute var_dict into range.

        Return of values within range.
        """
        start = sympify(self.start).subs(var_dict)
        end = sympify(self.end).subs(var_dict)
        i = 0
        if self.tc.inclusive:
            end += 1
        while start < end and i < RangedExpr.iter_limit:
            yield start
            start += 1
            i += 1


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
    key = key.replace('#', 'ctx').replace('@', 'arg')
    for k, v in ctx.items():
        key = key.replace(k, str(v))
    return key


_function_cache = {}


def step_io_functions(stepFunction, ctx, io_type):
    """
    Given a StepFunction and context values,
    return sympification of its io item and step expressions, io ∈ {inputs, outputs}.

    For example, given:
    ( addToRightEdge: row, col ) -> [cells: row + 1, col + 1],
    return:
    {'addToRightEdge': [(row + 1, col + 1)]}.
    """
    if (stepFunction.collName, io_type) in _function_cache:
        return _function_cache[(stepFunction.collName, io_type)]
    assert io_type in {'inputs', 'outputs'}
    iodict = getattr(stepFunction, io_type)
    ios = {coll: [] for coll in find_collNames(iodict)}
    for io in iodict:
        if io.kind in {"STEP", "ITEM"}:
            tag_list = io.key if io.kind == "ITEM" else io.tag
            ios[io.collName].append(tuple(
                sympify(subs_ctx(ctx, t.expr.raw)) if not t.isRanged
                else RangedExpr(ctx, t) for (i, t) in enumerate(tag_list)))
        elif io.kind == "IF":
            out_ref = io.refs[0]
            tag_list = out_ref.key if out_ref.kind == "ITEM" else out_ref.tag
            ios[out_ref.collName].append(tuple(
                Piecewise((sympify(subs_ctx(ctx, t.expr.raw)),
                           sympify(subs_ctx(ctx, io.rawCond)))) if not t.isRanged
                else RangedExpr(ctx, t, sympify(subs_ctx(ctx, io.rawCond)))
                for (i, t) in enumerate(tag_list)))
    _function_cache[(stepFunction.collName, io_type)] = ios
    return ios


def closest_match(haystacks, needle):
    '''
    From iterable of strings haystacks,
    find the shortest one that contains needle as a case-insensitive substring.
    '''
    matches = sorted((h for h in haystacks if needle.lower() in h.lower()),
                     key=len)
    if matches:
        return matches[0]


def _evaluate_tag_exprs(tag_exprs, tag):
    """Evaluate some tag expressions with given tag substitutions.
    """
    eval_stack = []
    eval_stack.append([expr if isinstance(expr, RangedExpr) else
                       expr.subs(tag) for expr in tag_exprs])
    while len(eval_stack) > 0:
        e = eval_stack.pop()
        ranges = [v for v in enumerate(e) if isinstance(v[1], RangedExpr)]
        if len(ranges) > 0:
            i, ranged_expr = ranges[0]
            for v in ranged_expr.subs(tag):
                new_tag = e[:]
                new_tag[i] = v
                eval_stack.append(new_tag)
        else:
            yield tuple(e)


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

    all_steps = {graphData.initFunction.collName: graphData.initFunction,
                    graphData.finalizeFunction.collName: graphData.finalizeFunction}
    all_steps.update(graphData.stepFunctions)

    # At the outset nothing has run, and nothing has been computed.
    run = set()
    compute = set()
    # Demand set starts at the inputs of the finalize step.
    demand = {(k, v) for k, exprs in
              step_io_functions(graphData.finalizeFunction,
                                ctx_values, 'inputs').items()
              if k not in all_steps for v in exprs}

    def tuple_to_dict(coll, tag):
        # Convert a tag tuple of values to a tag dictionary to map keys -> values
        if coll in all_steps:
            return dict(zip(all_steps[coll].tag, tag))
        else:
            return dict(zip(graphData.itemDeclarations[coll].key, tag))

    def dict_to_tuple(coll, tag):
        # Undo the other function
        if coll in all_steps:
            return tuple(tag[t] for t in all_steps[coll].tag)
        elif coll in graphData.itemDeclarations:
            return tuple(tag[t] for t in graphData.itemDeclarations[coll].key)
        else:
            return ()

    def expand_demand(step_tag):
        # Add the uncomputed inputs of the step to the demand set.
        s, t = step_tag
        for coll, in_exprses in step_io_functions(all_steps[s],
                                                  ctx_values,
                                                  'inputs').items():
            for in_exprs in in_exprses:
                for evaluated in _evaluate_tag_exprs(in_exprs, t):
                    evaluated_tuple = (coll, evaluated)
                    # Check we haven't already computed it, and
                    # make sure things like Piecewise() don't show up.
                    if evaluated_tuple not in compute and all(
                            len(e.atoms()) for e in evaluated):
                        print "Adding {} as demanded by {}".format(evaluated_tuple, step_tag)
                        demand.add(evaluated_tuple)

    def satisfy(step, tag):
        # Add the step to the run set and BFS on its products until supply is exhausted.
        # Tag should be a dict {i: val, j: val}.
        que = deque([(step, tag)])
        while len(que) != 0 and len(demand) != 0:
            step, tag = que.popleft()
            tag_tuple = dict_to_tuple(step, tag)
            # Mark that we must run the step, and satisfy its outputs.
            step_tag = (step, tag_tuple)
            data = all_steps[step]
            run.add(step_tag)
            outputs = step_io_functions(data, ctx_values, 'outputs')
            for coll, tag_exprses in outputs.items():
                for tag_exprs in tag_exprses:
                    for evaluated in _evaluate_tag_exprs(tag_exprs, tag):
                        coll_tag = (coll, evaluated)
                        if coll in all_steps:
                            if coll_tag not in run:
                                que.append((coll, tuple_to_dict(coll, evaluated)))
                        else:
                            # It's an item, add to compute set and remove from demand set.
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
            step = closest_match(candidates.keys(),
                                 raw_input("Can you help name the step? "))
            step_tag = candidates[step]
        elif len(candidates) < 1:
            print "Cannot satisfy demand for {}@{}".format(coll, tag)
            return
        else:
            step, step_tag = candidates.items()[0]
        print "Satisfying {} with {}".format(item, (step, step_tag))
        satisfy(step, step_tag)
        expand_demand((step, step_tag))

    pprint(("Compute", compute))
    pprint(("Run", run))
    # TODO: make a graph from these sets
    # idea: fake event log?

if __name__ == '__main__':
    main()
