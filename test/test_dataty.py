"""Unit tests for Dataty subclasses — validate() and describe()."""

# ruff: noqa: ANN201

from secop_check.dataty import (
    AnyType,
    Array,
    Bool,
    Datainfo,
    Double,
    Int,
    Number,
    OneOf,
    OneOfEnum,
    Parent,
    String,
    Struct,
    Tuple,
)


def test_number():
    assert Number().validate(42)
    assert Number().validate(3.14)
    assert not Number().validate('bad')
    assert not Number().validate(None)
    assert Number().describe() == 'number'


def test_double():
    assert Double().validate(42)
    assert Double().validate(3.14)
    assert not Double().validate('bad')
    assert Double().describe() == 'double'


def test_string():
    assert String().validate('hello')
    assert String().validate('')
    assert not String().validate(42)
    assert not String().validate(None)
    assert String().describe() == 'string'


def test_bool():
    assert Bool().validate(True)  # noqa: FBT003
    assert Bool().validate(False)  # noqa: FBT003
    assert not Bool().validate(1)
    assert not Bool().validate(0)
    assert not Bool().validate('true')
    assert Bool().describe() == 'bool'


def test_int():
    assert Int({}).validate(42)
    assert Int({}).validate(3.0)
    assert not Int({}).validate(3.14)
    assert not Int({}).validate('bad')
    assert not Int({'min': 0}).validate(-1)
    assert not Int({'max': 100}).validate(101)
    assert Int({'min': 0, 'max': 100}).validate(50)
    assert Int({'min': 0, 'max': 100}).validate(0)
    assert Int({'min': 0, 'max': 100}).validate(100)
    assert Int({}).describe() == 'integer'
    assert Int({'min': 0}).describe() == 'integer (>= 0)'
    assert Int({'max': 100}).describe() == 'integer (<= 100)'
    assert Int({'min': 0, 'max': 100}).describe() == 'integer (>= 0) (<= 100)'


def test_array():
    assert Array({}).validate([1, 2, 3])
    assert not Array({}).validate('bad')
    assert Array({'members': 'int'}).validate([1, 2, 3])
    assert not Array({'members': 'int'}).validate([1, 'bad'])
    assert Array({'members': 'int'}).validate([])
    assert not Array({'members': 'int'}).validate('bad')
    assert Array({}).describe() == 'array'
    assert Array({'members': 'string'}).describe() == 'array of string'


def test_tuple():
    assert Tuple({}).validate([1, 2, 3])
    assert not Tuple({}).validate('bad')
    assert Tuple({'members': ['int', 'string']}).validate([1, 'hello'])
    assert not Tuple({'members': ['int', 'string']}).validate([1])
    assert not Tuple({'members': ['int', 'string']}).validate([1, 'x', 3])
    assert not Tuple({'members': ['int', 'string']}).validate([1, 2])
    assert not Tuple({'members': ['int', 'string']}).validate('bad')
    assert Tuple({}).describe() == 'tuple'
    desc = Tuple({'members': ['int', 'string']}).describe()
    assert desc == 'tuple of (integer, string)'


def test_struct():
    # homogeneous
    assert Struct({'members': 'double'}).validate({'a': 1.0, 'b': 2.0})
    assert not Struct({'members': 'double'}).validate({'a': 'bad'})
    assert not Struct({'members': 'double'}).validate('bad')
    assert Struct({'members': 'double'}).validate({})
    assert Struct({'members': 'double'}).validate({'a': 1})
    desc = Struct({'members': 'double'}).describe()
    assert desc == 'struct with str names and values of type: double'
    # heterogeneous
    s = Struct({'members': {'a': 'int', 'b': 'string'}})
    assert s.validate({'a': 1, 'b': 'x'})
    assert not s.validate({'a': 1})
    assert not s.validate({'a': 'bad', 'b': 'x'})
    assert not s.validate('bad')
    assert s.validate({'a': 1, 'b': 'x', 'extra': 2})
    s2 = Struct({'members': {'a': 'int', 'b': 'string'}, 'optional': ['b']})
    assert s2.validate({'a': 1})
    desc = s2.describe()
    assert desc == 'struct with fields: a (integer, required), b (string, optional)'
    # no members
    assert Struct({}).validate({'a': 1})
    assert not Struct({}).validate('bad')
    assert Struct({}).describe() == 'struct'


def test_oneof():
    assert OneOf({'values': ['a', 'b', 'c']}).validate('a')
    assert not OneOf({'values': ['a', 'b', 'c']}).validate('d')
    assert not OneOf({'values': ['a', 'b', 'c']}).validate(42)
    assert OneOf({'values': ['a', 'b', 'c']}).describe() == 'one of: a, b, c'


def test_oneof_enum():
    assert OneOfEnum({'members': {'a': 1, 'b': 2}}).validate(1)
    assert not OneOfEnum({'members': {'a': 1, 'b': 2}}).validate(3)
    assert not OneOfEnum({'members': {'a': 1, 'b': 2}}).validate('bad')
    desc = OneOfEnum({'members': {'a': 1, 'b': 2}}).describe()
    assert desc == 'one of [1, 2]'


def test_datainfo():
    assert Datainfo().validate({'type': 'double'})
    assert not Datainfo().validate('bad')
    assert Datainfo().describe() == 'datainfo'


def test_anytype():
    assert AnyType().validate('anything')
    assert AnyType().validate(42)
    assert AnyType().validate(None)
    assert AnyType().describe() == 'any type'


def test_parent():
    assert Parent().validate('anything')
    assert Parent().validate(42)
    assert Parent().describe() == 'type of parent element'
