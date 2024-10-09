import json
import re
import sys
from collections import namedtuple
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml


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
    # print(props.keys())
    # for k, v in props_for_thing.items():
    #     print(k)
    #     for x, y in v.items():
    #         print("\t", x)

    return Spec(specs, props, props_for_thing)


def check(path, version=Version.LATEST, output_json=False):
    if path == '-':
        checks(sys.stdin.read(), version, output_json=output_json)
    if isinstance(path, str):
        path = Path(path)
    with path.open('r', encoding='utf-8') as f:
        checks(f.read(), version, output_json=output_json)


def check_part(node, nodekind, context, spec):
    # check that node is an object!
    props = spec.prop_map[nodekind]
    required = set([prop for prop, asdf in props.items() if not asdf.get('optional', False)])
    for member, mvalues in node.items():
        required.discard(member)
        if member not in props:
            # check custom property
            if not member.startswith('_'):
                print(f'{member}: non-standard properties need \'_\' as a prefix!')
        if member == 'modules':
            for mod, moddesc in mvalues.items():
                check_part(moddesc, 'Interface', {'name': mod}, spec)
    if required:
        print('missing required properties:', required)


def checks(description, version=Version.LATEST, output_json=False):
    """check string"""
    try:
        desc = json.loads(description)
    except json.JSONDecodeError as e:
        print(e.msg, e.pos, e.lineno, e.colno)
        raise ValueError("invalid json") from e
    spec = load_and_mangle(version)
    # check_part(desc, 'SECNode', {}, spec)
    # step_through(desc, spec)
    visitor_step_through_outer(desc, spec, output_json)


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
    required = set([prop for prop, asdf in props.items() if not asdf.get('optional', False)])
    # print(f'checking {nodekind}: {list(props.keys())}')
    for member, mvalues in desc.items():
        required.discard(member)
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
    if required:
        print('missing required properties:', required)


def check_datainfo(mvalues):
    pass


# int-enum?
class Severity(Enum):
    HINT = 0
    WARNING = 1
    ERROR = 2
    CATASTROPHIC = 3  # something, were we just stop?


# TODO: make this useful
@dataclass
class Context:
    path: list[str]
    # system?


@dataclass
class CheckerError:
    severity: Severity
    checker: str  # name of the checker that produced the error
    ctx: Context
    msg: str


class BaseTestChecker:
    name = 'check-base'

    def __init__(self, spec):
        self.spec = spec

    def visit(self, nodekind, description, context, name=None):
        """called at every element of the description"""

    def visit_node(self, description, context):
        """called when visiting the root SECNode element"""

    def visit_property(self, nodekind, description, context):
        """called when visiting elements that should be a property, based on their position"""

    def visit_module(self, name, description, context):
        """called when visiting elements that should be a module, based on their position"""

    def visit_accessible(self, name, description, context):
        """called when visiting elements that should be an accessible, based on their position"""

    def visit_datainfo(self, description, context):
        """called when visiting elements that are called datainfo"""

    def finish_accessible(self, description, context):
        """called after all subelements of an accessible"""

    def finish_module(self, name, context):
        """called after all subelements of a module"""

    def finish(self, context):
        """called after all elements are processed"""

    def get_errors(self):
        """get all errors the checker found"""


# TODO: better way
class PropChecker(BaseTestChecker):
    name = 'properties-basic'

    def __init__(self, spec):
        super().__init__(spec)
        self.errors = []

    def check_props_present(self, description, context, nodekind):
        props = self.spec.prop_map[nodekind]
        required = set(
            [prop for prop, propspec in props.items()
             if not propspec.get('optional', False)]
        )
        for member, mvalues in description.items():
            required.discard(member)
            if member not in props:
                if not member.startswith('_'):
                    self.errors.append(
                        CheckerError(Severity.WARNING, self.name, context,
                                     f'{member}: non-standard properties need \'_\' as a prefix!'
                                     )
                    )
                # TODO: check custom property datainfo etc if possible
            else:
                if props[member].get('datainfo') == 'Datainfo':
                    check_datainfo(mvalues)
                else:
                    pass
                    # isinstance(mvalues, class_from_typedesc):
        if required:
            self.errors.append(
                CheckerError(Severity.WARNING, self.name, context,
                             f'missing required properties: {required}'
                             )
            )

    def visit_node(self, description, context):
        self.check_props_present(description, context, 'SECNode')

    def visit_module(self, name, description, context):
        self.check_props_present(description, context, 'Interface')

    def visit_accessible(self, name, description, context):
        ty = description.get('datainfo', {}).get('type', None)
        if ty is None:
            self.errors.append(
                    CheckerError(Severity.ERROR, self.name, context,
                                 f'Accessible datainfo of {name} does not have a type!')
            )
        elif ty == 'Command':
            self.check_props_present(description, context, 'Command')
        else:
            self.check_props_present(description, context, 'Parameter')

    def get_errors(self):
        return self.errors


class ModulenameChecker(BaseTestChecker):
    name = 'module-name'

    def __init__(self, spec):
        super().__init__(spec)
        self.errors = []

    def visit_module(self, name, description, context):
        if not re.match(r'^[a-zA-Z]\w{0,62}$', name):
            self.errors.append(
                    CheckerError(Severity.WARNING, self.name, context,
                                 f'{name} does not match required module name format!')
            )

    def get_errors(self):
        return self.errors


def errors_to_json(errors):
    output = []
    for checkername, errors_from_checker in errors.items():
        output.append({
            "checker": checkername,
            "errors": [
                {"severity": err.severity.name, "ctx": err.ctx.path, "msg": err.msg}
                for err in errors_from_checker
            ],
        })
    return json.dumps(output)


def fmt_errors(errors):
    if all(not errs for errs in errors.values()):
        return 'No errors found'

    out = ''
    for checker, errs in errors.items():
        if not errs:
            continue
        out += f'{checker}:\n'
        for err in errs:
            out += f'  {err.severity.name.capitalize()}: {err.msg} ({err.ctx})\n'
    return out


def visitor_step_through_outer(desc, spec, output_json):
    checkers = [PropChecker, ModulenameChecker]
    errors = {}
    for checkercls in checkers:
        checker = checkercls(spec)
        if checker.name in errors:
            raise ValueError('didnt override checker name or you want to run checker twice!')
        visitor_step_through(desc, checker)
        errors[checker.name] = checker.get_errors()
    if output_json:
        print(errors_to_json(errors))
    else:
        print(fmt_errors(errors))


# TODO: missing visit_datainfo calls above accessibles
# TODO: maybe too strict/make more flexible? -> e.g. go through all dicts and check datainfo by name etc.
def visitor_step_through(desc, checker):
    checker.visit('SECNode', desc, Context([]))
    checker.visit_node(desc, Context([]))
    for prop, propdesc in desc.items():
        checker.visit('Property', desc, Context(['SECNode']))
        checker.visit_property('SECNode', propdesc, Context(['SECNode']))
    for module, moddesc in desc.get('modules', {}).items():
        checker.visit('Interface', desc, Context(['SECNode', 'modules']))
        checker.visit_module(module, moddesc, Context(['SECNode', 'modules']))
        for prop, propdesc in moddesc.items():
            checker.visit('Property', moddesc, Context([]))
            checker.visit_property('Interface', propdesc, Context(['SECNode', 'modules', module]))
        for accessible, accdesc in moddesc.get('accessibles', {}).items():
            checker.visit('Interface', accdesc, Context(['SECNode', 'modules', module]))
            checker.visit_accessible('Interface', accdesc, Context(['SECNode', 'modules', module]))
            for prop, propdesc in accdesc.items():
                checker.visit('SECNode', desc, Context([]))
                checker.visit_property('Interface', propdesc,
                                       Context(['SECNode', 'modules', module, 'accessibles', accessible]))
            datainfo = accdesc.get('datainfo')
            if not datainfo:
                continue
            checker.visit_datainfo(datainfo,
                                   Context(['SECNode', 'modules', module, 'accessibles', accessible]))
            checker.finish_accessible(datainfo,
                                   Context(['SECNode', 'modules', module, 'accessibles', accessible]))
        checker.finish_module(module, Context(['SECNode']))
    checker.finish(Context([]))
