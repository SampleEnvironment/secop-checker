import json
import re
import sys
from collections import namedtuple
from enum import Enum
from pathlib import Path

import yaml


class CheckerError(Exception):
    pass

# TODO:
# - version resolution
# - strategy?
#   - checker which each goes through
#   - checker once through tree with callbacks (checker.check_datainfo)
#   - just static coding?
# - define datatypes
# - how to propagate errors?
#   - stop at first error, continue on warning
#   - try best effort to continue? -> effort for all following checkers


class Version(str, Enum):
    LATEST = 'latest'
    V1_0 = '1.0'
    V1_1 = '1.1'


class Checker:  # TODO
    """Base"""


Spec = namedtuple('Spec', 'all, properties, prop_map')


def load_and_mangle(version):
    path = Path(__file__).parents[1] / 'defs'
    all_specs = []
    for doc in path.glob('*.yaml'):
        with doc.open('r') as f:
            all_specs.extend(yaml.safe_load_all(f))
    specs = {}
    props = {}
    props_for_thing = {}
    for spec in all_specs:
        if not set(['kind', 'name', 'version', 'description']) <= set(spec.keys()):
            print(spec)
            raise ValueError('InternalError')
        kind = spec['kind']
        if kind == 'Property':
            props[spec['name']] = spec
            for thing in spec['applies_to']:
                if thing not in props_for_thing:
                    props_for_thing[thing] = {}
                props_for_thing[thing][spec['name']] = spec
    #print(props.keys())
    #for k, v in props_for_thing.items():
    #    print(k)
    #    for x, y in v.items():
    #        print("\t", x)

    return Spec(specs, props, props_for_thing)


def check(path, version=Version.LATEST):
    if path == '-':
        checks(sys.stdin.read(), version)
    if isinstance(path, str):
        path = Path(path)
    with path.open('r', encoding='utf-8') as f:
        checks(f.read(), version)


def check_part(node, nodekind, context, spec):
    # check that node is an object!
    props = spec.prop_map[nodekind]
    reqired = set([prop for prop, asdf in props.items() if not asdf.get('optional', False)])
    for member, mvalues in node.items():
        reqired.discard(member)
        if member not in props:
            # check custom property
            if not member.startswith('_'):
                print(f'{member}: non-standard properties need \'_\' as a prefix!')
        if member == 'modules':
            for mod, moddesc in mvalues.items():
                check_part(moddesc, 'Interface', {'name': mod}, spec)
    if reqired:
        print('missing required properties:', reqired)


def checks(description, version=Version.LATEST):
    try:
        desc = json.loads(description)
    except json.JSONDecodeError as e:
        print(e.msg, e.pos, e.lineno, e.colno)
        raise ValueError("invalid json") from e
    print("checking...")
    spec = load_and_mangle(version)
    #check_part(desc, 'SECNode', {}, spec)
    step_through(desc, spec)
    #visitor_step_through_outer(desc, spec)


def step_through(desc, spec):
    check_applicable_properties(desc, 'SECNode', spec)
    for module, moddesc in desc.get('modules', {}).items():
        check_applicable_properties(moddesc, 'Interface', spec)
        for accessible, accdesc in moddesc.get('accessibles', {}).items():
            ty = accdesc.get('datainfo').get('type')
            if ty is None:
                print("err TODO")
            elif ty == 'Command':
                check_applicable_properties(accdesc, 'Command', spec)
            else:
                check_applicable_properties(accdesc, 'Parameter', spec)
    # check each module
    #   # check each prop
    #   # check each accessible
    #   #   # check each prop
    #    #   #   # (opt) check each datainfo


def check_applicable_properties(desc, nodekind, spec):
    props = spec.prop_map[nodekind]
    reqired = set([prop for prop, asdf in props.items() if not asdf.get('optional', False)])
    # print(f'checking {nodekind}: {list(props.keys())}')
    for member, mvalues in desc.items():
        reqired.discard(member)
        if member not in props:
            if not member.startswith('_'):
                print(f'{member}: non-standard properties need \'_\' as a prefix!')
            # TODO: check custom property datainfo etc if possible
        else:
            if props[member].get('datainfo') == 'Datainfo':
                check_datainfo(mvalues)
            else:
                pass
                # isinstance(mvalues, class_from_typedesc):
    if reqired:
        print('missing required properties:', reqired)


def check_datainfo(mvalues):
    pass


# ## Test something else


class Context:
    pass
    # "path"
    #


class BaseTestChecker:
    def visit(self, nodekind, description, path, spec, name=None):
        pass

    def visit_node(self, description, path, spec):
        pass

    def visit_property(self, nodekind, description, path):
        pass

    def visit_module(self, name, description):
        pass

    def visit_accessible(self, name, description, path):
        pass

    def visit_datainfo(self, description, path):
        pass

    def finish_module(self, name):
        pass

    def finish(self):
        pass


# collect all properties, check if they are defined or preceded by _
class Propchecker(BaseTestChecker):
    def __init__(self, spec):
        self.spec = spec
        self.seen = {}

    def visit_node(self, nodekind, description, path, spec, name=None):
        # todo
        pass

    def finish(self):
        props = spec.prop_map[nodekind]
        #print(f'checking {nodekind}: {list(props.keys())}')
        for member, mvalues in desc.items():
            reqired.discard(member)
            if member not in props:
                if not member.startswith('_'):
                    print(f'{member}: non-standard properties need \'_\' as a prefix!')
                # TODO: check custom property datainfo etc if possible
            else:
                if props[member].get('datainfo') == 'Datainfo':
                    check_datainfo(mvalues)
                else:
                    pass
                    # isinstance(mvalues, class_from_typedesc):
        if reqired:
            print('missing required properties:', reqired)



class Modulenamechecker(BaseTestChecker):
    def visit_module(self, name, description):
        if not re.match(r'', name):
            print('')


def visitor_step_through_outer(desc, spec):
    checkers = []
    visitor_step_through(desc, spec, checkers)


# TODO: missing visit_datainfo calls above accessibles
def visitor_step_through(desc, spec, checkers):
    for checker in checkers:
        checker.visit_node('SECNode', desc, [])
        for prop, propdesc in desc.items():
            checker.visit_node('Property', desc, ['SECNode'], spec)
            checker.visit_property('SECNode', propdesc, ['SECNode'], spec)
    for module, moddesc in desc.get('modules', {}).items():
        for checker in checkers:
            checker.visit_node('Interface', desc, ['SECNode', 'modules'])
            checker.visit_module(module, moddesc)
        for prop, propdesc in moddesc.items():
            for checker in checkers:
                checker.visit_node('Property', moddesc, [])
                checker.visit_property('Interface', propdesc, ['SECNode', 'modules', module], spec)
        for accessible, accdesc in moddesc.get('accessibles', {}).items():
            for checker in checkers:
                checker.visit_node('Interface', accdesc, ['SECNode', 'modules', module], spec)
                checker.visit_accessible('Interface', accdesc, ['SECNode', 'modules', module])
            for prop, propdesc in accdesc.items():
                for checker in checkers:
                    checker.visit_node('SECNode', desc, [])
                    checker.visit_property('Interface', propdesc, ['SECNode', 'modules', module, 'accessibles', accessible], spec)
            datainfo = accdesc.get('datainfo')
            if not datainfo:
                continue
            for checker in checkers:
                checker.visit_datainfo(datainfo,
                                       ['SECNode', 'modules', module, 'accessibles', accessible])
        checker.finish_module(module)
    checker.finish_node()
