#
# This source file is part of the EdgeDB open source project.
#
# Copyright 2008-present MagicStack Inc. and the EdgeDB authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#


"""EdgeQL non-statement expression compilation functions."""


import ast
import typing

from edb import errors

from edb.edgeql import qltypes as ft

from edb.ir import ast as irast
from edb.ir import staeval as ireval
from edb.ir import typeutils as irtyputils

from edb.schema import abc as s_abc
from edb.schema import objtypes as s_objtypes
from edb.schema import pointers as s_pointers

from edb.edgeql import ast as qlast

from . import cast
from . import context
from . import dispatch
from . import inference
from . import pathctx
from . import setgen
from . import schemactx
from . import stmtctx
from . import typegen

from . import func  # NOQA


@dispatch.compile.register(qlast._Optional)
def compile__Optional(
        expr: qlast.Base, *, ctx: context.ContextLevel) -> irast.Set:

    result = setgen.ensure_set(
        dispatch.compile(expr.expr, ctx=ctx),
        ctx=ctx)

    pathctx.register_set_in_scope(result, ctx=ctx)
    pathctx.mark_path_as_optional(result.path_id, ctx=ctx)

    return result


@dispatch.compile.register(qlast.Path)
def compile_Path(
        expr: qlast.Base, *, ctx: context.ContextLevel) -> irast.Set:
    return setgen.compile_path(expr, ctx=ctx)


@dispatch.compile.register(qlast.BinOp)
def compile_BinOp(
        expr: qlast.Base, *, ctx: context.ContextLevel) -> irast.Set:

    op_node = func.compile_operator(
        expr, op_name=expr.op, qlargs=[expr.left, expr.right], ctx=ctx)

    if ctx.env.constant_folding:
        folded = try_fold_binop(op_node.expr, ctx=ctx)
        if folded is not None:
            return folded

    return setgen.ensure_set(op_node, ctx=ctx)


@dispatch.compile.register(qlast.IsOp)
def compile_IsOp(
        expr: qlast.Base, *, ctx: context.ContextLevel) -> irast.Set:
    op_node = compile_type_check_op(expr, ctx=ctx)
    return setgen.ensure_set(op_node, ctx=ctx)


@dispatch.compile.register(qlast.Parameter)
def compile_Parameter(
        expr: qlast.Base, *, ctx: context.ContextLevel) -> irast.Set:

    if ctx.func is not None:
        raise errors.QueryError(
            f'"$parameters" cannot be used in functions',
            context=expr.context)

    pt = ctx.env.query_parameters.get(expr.name)
    typeref = irtyputils.type_to_typeref(ctx.env.schema, pt)
    return setgen.ensure_set(
        irast.Parameter(typeref=typeref, name=expr.name), ctx=ctx)


@dispatch.compile.register(qlast.DetachedExpr)
def compile_DetachedExpr(
        expr: qlast.DetachedExpr, *, ctx: context.ContextLevel):
    with ctx.detached() as subctx:
        return dispatch.compile(expr.expr, ctx=subctx)


@dispatch.compile.register(qlast.Set)
def compile_Set(
        expr: qlast.Base, *, ctx: context.ContextLevel) -> irast.Base:
    if expr.elements:
        if len(expr.elements) == 1:
            # From the scope perspective, single-element set
            # literals are equivalent to a binary UNION with
            # an empty set, not to the element.
            with ctx.newscope(fenced=True) as scopectx:
                ir_set = dispatch.compile(expr.elements[0], ctx=scopectx)
                return setgen.scoped_set(ir_set, ctx=scopectx)
        else:
            elements = flatten_set(expr)
            # a set literal is just sugar for a UNION
            op = 'UNION'

            bigunion = qlast.BinOp(
                left=elements[0],
                right=elements[1],
                op=op
            )
            for el in elements[2:]:
                bigunion = qlast.BinOp(
                    left=bigunion,
                    right=el,
                    op=op
                )
            return dispatch.compile(bigunion, ctx=ctx)
    else:
        return setgen.new_empty_set(alias=ctx.aliases.get('e'), ctx=ctx)


@dispatch.compile.register(qlast.BaseConstant)
def compile_BaseConstant(
        expr: qlast.BaseConstant, *, ctx: context.ContextLevel) -> irast.Base:
    value = expr.value

    if isinstance(expr, qlast.StringConstant):
        std_type = 'std::str'
        node_cls = irast.StringConstant
    elif isinstance(expr, qlast.RawStringConstant):
        std_type = 'std::str'
        node_cls = irast.RawStringConstant
    elif isinstance(expr, qlast.IntegerConstant):
        int_value = int(expr.value)
        if expr.is_negative:
            int_value = -int_value
            value = f'-{value}'
        # If integer value is out of int64 bounds, use decimal
        if -2 ** 63 <= int_value < 2 ** 63:
            std_type = 'std::int64'
        else:
            std_type = 'std::decimal'
        node_cls = irast.IntegerConstant
    elif isinstance(expr, qlast.FloatConstant):
        if expr.is_negative:
            value = f'-{value}'
        std_type = 'std::float64'
        node_cls = irast.FloatConstant
    elif isinstance(expr, qlast.BooleanConstant):
        std_type = 'std::bool'
        node_cls = irast.BooleanConstant
    elif isinstance(expr, qlast.BytesConstant):
        std_type = 'std::bytes'
        node_cls = irast.BytesConstant
        value = ast.literal_eval(f'b{expr.quote}{expr.value}{expr.quote}')
    else:
        raise RuntimeError(f'unexpected constant type: {type(expr)}')

    ct = irtyputils.type_to_typeref(
        ctx.env.schema, ctx.env.schema.get(std_type))
    return setgen.ensure_set(node_cls(value=value, typeref=ct), ctx=ctx)


def try_fold_binop(
        opcall: irast.OperatorCall, *,
        ctx: context.ContextLevel) -> typing.Optional[irast.Set]:
    try:
        const = ireval.evaluate(opcall, schema=ctx.env.schema)
    except ireval.UnsupportedExpressionError:
        anyreal = ctx.env.schema.get('std::anyreal')

        if (opcall.func_shortname in ('std::+', 'std::*') and
                opcall.operator_kind is ft.OperatorKind.INFIX and
                all(setgen.get_set_type(a.expr, ctx=ctx).issubclass(
                    ctx.env.schema, anyreal)
                    for a in opcall.args)):
            return try_fold_associative_binop(opcall, ctx=ctx)
    else:
        return setgen.ensure_set(const, ctx=ctx)


def try_fold_associative_binop(
        opcall: irast.OperatorCall, *,
        ctx: context.ContextLevel) -> typing.Optional[irast.Set]:

    # Let's check if we have (CONST + (OTHER_CONST + X))
    # tree, which can be optimized to ((CONST + OTHER_CONST) + X)

    op = opcall.func_shortname
    my_const = opcall.args[0].expr
    other_binop = opcall.args[1].expr
    folded = None

    if isinstance(other_binop.expr, irast.BaseConstant):
        my_const, other_binop = other_binop, my_const

    if (isinstance(my_const.expr, irast.BaseConstant) and
            isinstance(other_binop.expr, irast.OperatorCall) and
            other_binop.expr.func_shortname == op and
            other_binop.expr.operator_kind is ft.OperatorKind.INFIX):

        other_const = other_binop.expr.args[0].expr
        other_binop_node = other_binop.expr.args[1].expr

        if isinstance(other_binop_node.expr, irast.BaseConstant):
            other_binop_node, other_const = \
                other_const, other_binop_node

        if isinstance(other_const.expr, irast.BaseConstant):
            try:
                new_const = ireval.evaluate(
                    irast.OperatorCall(
                        args=[
                            irast.CallArg(
                                expr=other_const,
                            ),
                            irast.CallArg(
                                expr=my_const,
                            ),
                        ],
                        func_module_id=opcall.func_module_id,
                        func_shortname=op,
                        func_polymorphic=opcall.func_polymorphic,
                        func_sql_function=opcall.func_sql_function,
                        sql_operator=opcall.sql_operator,
                        force_return_cast=opcall.force_return_cast,
                        operator_kind=opcall.operator_kind,
                        params_typemods=opcall.params_typemods,
                        context=opcall.context,
                        typeref=opcall.typeref,
                        typemod=opcall.typemod,
                    ),
                    schema=ctx.env.schema,
                )
            except ireval.UnsupportedExpressionError:
                pass
            else:
                folded_binop = irast.OperatorCall(
                    args=[
                        irast.CallArg(
                            expr=setgen.ensure_set(new_const, ctx=ctx),
                        ),
                        irast.CallArg(
                            expr=other_binop_node,
                        ),
                    ],
                    func_module_id=opcall.func_module_id,
                    func_shortname=op,
                    func_polymorphic=opcall.func_polymorphic,
                    func_sql_function=opcall.func_sql_function,
                    sql_operator=opcall.sql_operator,
                    force_return_cast=opcall.force_return_cast,
                    operator_kind=opcall.operator_kind,
                    params_typemods=opcall.params_typemods,
                    context=opcall.context,
                    typeref=opcall.typeref,
                    typemod=opcall.typemod,
                )

                folded = setgen.ensure_set(folded_binop, ctx=ctx)

    return folded


@dispatch.compile.register(qlast.NamedTuple)
def compile_NamedTuple(
        expr: qlast.Base, *, ctx: context.ContextLevel) -> irast.Set:

    elements = []
    for el in expr.elements:
        element = irast.TupleElement(
            name=el.name.name,
            val=setgen.ensure_set(dispatch.compile(el.val, ctx=ctx), ctx=ctx)
        )
        elements.append(element)

    return setgen.new_tuple_set(elements, named=True, ctx=ctx)


@dispatch.compile.register(qlast.Tuple)
def compile_Tuple(
        expr: qlast.Base, *, ctx: context.ContextLevel) -> irast.Set:

    elements = []
    for i, el in enumerate(expr.elements):
        element = irast.TupleElement(
            name=str(i),
            val=setgen.ensure_set(dispatch.compile(el, ctx=ctx), ctx=ctx)
        )
        elements.append(element)

    return setgen.new_tuple_set(elements, named=False, ctx=ctx)


@dispatch.compile.register(qlast.Array)
def compile_Array(
        expr: qlast.Base, *, ctx: context.ContextLevel) -> irast.Base:
    elements = [dispatch.compile(e, ctx=ctx) for e in expr.elements]
    # check that none of the elements are themselves arrays
    for el, expr_el in zip(elements, expr.elements):
        if isinstance(inference.infer_type(el, ctx.env), s_abc.Array):
            raise errors.QueryError(
                f'nested arrays are not supported',
                context=expr_el.context)

    return setgen.new_array_set(elements, ctx=ctx)


@dispatch.compile.register(qlast.IfElse)
def compile_IfElse(
        expr: qlast.IfElse, *, ctx: context.ContextLevel) -> irast.Base:

    condition = setgen.ensure_set(
        dispatch.compile(expr.condition, ctx=ctx), ctx=ctx)

    ql_if_expr = expr.if_expr
    ql_else_expr = expr.else_expr

    with ctx.newscope(fenced=True) as scopectx:
        if_expr = setgen.scoped_set(
            dispatch.compile(ql_if_expr, ctx=scopectx),
            ctx=scopectx)

    with ctx.newscope(fenced=True) as scopectx:
        else_expr = setgen.scoped_set(
            dispatch.compile(ql_else_expr, ctx=scopectx),
            ctx=scopectx)

    if_expr_type = inference.infer_type(if_expr, ctx.env)
    else_expr_type = inference.infer_type(else_expr, ctx.env)
    cond_expr_type = inference.infer_type(condition, ctx.env)

    # make sure that the condition is actually boolean
    bool_t = ctx.env.schema.get('std::bool')
    if not cond_expr_type.issubclass(ctx.env.schema, bool_t):
        raise errors.QueryError(
            'if/else condition must be of type {}, got: {}'.format(
                bool_t.get_displayname(ctx.env.schema),
                cond_expr_type.get_displayname(ctx.env.schema)),
            context=expr.context)

    result = if_expr_type.find_common_implicitly_castable_type(
        else_expr_type, schema=ctx.env.schema)

    if result is None:
        raise errors.QueryError(
            f'IF/ELSE operator cannot be applied to operands of type '
            f'{if_expr_type.get_displayname(ctx.env.schema)!r} and '
            f'{else_expr_type.get_displayname(ctx.env.schema)!r}',
            context=expr.context)

    ifelse = irast.IfElseExpr(
        if_expr=if_expr,
        else_expr=else_expr,
        condition=condition)

    stmtctx.get_expr_cardinality_later(
        target=ifelse, field='if_expr_card', irexpr=if_expr, ctx=ctx)
    stmtctx.get_expr_cardinality_later(
        target=ifelse, field='else_expr_card', irexpr=else_expr, ctx=ctx)

    return setgen.ensure_set(
        ifelse,
        ctx=ctx
    )


@dispatch.compile.register(qlast.UnaryOp)
def compile_UnaryOp(
        expr: qlast.Base, *, ctx: context.ContextLevel) -> irast.Set:

    result = func.compile_operator(
        expr, op_name=expr.op, qlargs=[expr.operand], ctx=ctx)

    try:
        result = ireval.evaluate(result, schema=ctx.env.schema)
    except ireval.UnsupportedExpressionError:
        pass

    return setgen.ensure_set(result, ctx=ctx)


@dispatch.compile.register(qlast.TypeCast)
def compile_TypeCast(
        expr: qlast.Base, *, ctx: context.ContextLevel) -> irast.Base:
    target_typeref = typegen.ql_typeref_to_ir_typeref(expr.type, ctx=ctx)

    if (isinstance(expr.expr, qlast.Array) and not expr.expr.elements and
            irtyputils.is_array(target_typeref)):
        ir_expr = irast.Array()

    elif isinstance(expr.expr, qlast.Parameter):
        pt = typegen.ql_typeref_to_type(expr.type, ctx=ctx)
        param_name = expr.expr.name
        if param_name not in ctx.env.query_parameters:
            if ctx.env.query_parameters:
                first_key: str = next(iter(ctx.env.query_parameters))
                if first_key.isdecimal():
                    if not param_name.isdecimal():
                        raise errors.QueryError(
                            f'cannot combine positional and named parameters '
                            f'in the same query',
                            context=expr.expr.context)
                else:
                    if param_name.isdecimal():
                        raise errors.QueryError(
                            f'expected a named argument',
                            context=expr.expr.context)
            ctx.env.query_parameters[param_name] = pt
        else:
            param_first_type = ctx.env.query_parameters[param_name]
            if not param_first_type.explicitly_castable_to(pt, ctx.env.schema):
                raise errors.QueryError(
                    f'cannot cast '
                    f'{param_first_type.get_displayname(ctx.env.schema)} to '
                    f'{pt.get_displayname(ctx.env.schema)}',
                    context=expr.expr.context)

        param = irast.Parameter(
            typeref=irtyputils.type_to_typeref(ctx.env.schema, pt),
            name=param_name, context=expr.expr.context)
        return setgen.ensure_set(param, ctx=ctx)

    else:
        with ctx.new() as subctx:
            # We use "exposed" mode in case this is a type of a cast
            # that wants view shapes, e.g. a std::json cast.  We do
            # this wholesale to support tuple and array casts without
            # having to analyze the target type (which is cumbersome
            # in QL AST).
            subctx.expr_exposed = True
            ir_expr = dispatch.compile(expr.expr, ctx=subctx)

    new_stype = typegen.ql_typeref_to_type(expr.type, ctx=ctx)
    return cast.compile_cast(
        ir_expr, new_stype, ctx=ctx, srcctx=expr.expr.context)


@dispatch.compile.register(qlast.TypeFilter)
def compile_TypeFilter(
        expr: qlast.Base, *, ctx: context.ContextLevel) -> irast.Base:
    # Expr[IS Type] expressions.
    with ctx.new() as scopectx:
        arg = setgen.ensure_set(
            dispatch.compile(expr.expr, ctx=scopectx),
            ctx=scopectx)

    arg_type = inference.infer_type(arg, ctx.env)
    if not isinstance(arg_type, s_objtypes.ObjectType):
        raise errors.QueryError(
            f'invalid type filter operand: '
            f'{arg_type.get_displayname(ctx.env.schema)} '
            f'is not an object type',
            context=expr.expr.context)

    typ = schemactx.get_schema_type(expr.type.maintype, ctx=ctx)
    if not isinstance(typ, s_objtypes.ObjectType):
        raise errors.QueryError(
            f'invalid type filter operand: '
            f'{typ.get_displayname(ctx.env.schema)} is not an object type',
            context=expr.type.context)

    return setgen.class_indirection_set(arg, typ, optional=False, ctx=ctx)


@dispatch.compile.register(qlast.Introspect)
def compile_Introspect(
        expr: qlast.Introspect, *, ctx: context.ContextLevel) -> irast.Base:

    typeref = typegen.ql_typeref_to_ir_typeref(expr.type, ctx=ctx)
    if typeref.material_type and not irtyputils.is_object(typeref):
        typeref = typeref.material_type

    if irtyputils.is_view(typeref):
        raise errors.QueryError(
            f'cannot introspect views',
            context=expr.type.context)
    if irtyputils.is_collection(typeref):
        raise errors.QueryError(
            f'cannot introspect collection types',
            context=expr.type.context)
    if irtyputils.is_generic(typeref):
        raise errors.QueryError(
            f'cannot introspect generic types',
            context=expr.type.context)

    return irast.TypeIntrospection(typeref=typeref)


@dispatch.compile.register(qlast.Indirection)
def compile_Indirection(
        expr: qlast.Base, *, ctx: context.ContextLevel) -> irast.Base:
    node = dispatch.compile(expr.arg, ctx=ctx)
    for indirection_el in expr.indirection:
        if isinstance(indirection_el, qlast.Index):
            idx = dispatch.compile(indirection_el.index, ctx=ctx)
            idx.context = indirection_el.index.context
            node = irast.IndexIndirection(expr=node, index=idx,
                                          context=expr.context)

        elif isinstance(indirection_el, qlast.Slice):
            if indirection_el.start:
                start = dispatch.compile(indirection_el.start, ctx=ctx)
            else:
                start = None

            if indirection_el.stop:
                stop = dispatch.compile(indirection_el.stop, ctx=ctx)
            else:
                stop = None

            node = irast.SliceIndirection(
                expr=node, start=start, stop=stop)
        else:
            raise ValueError('unexpected indirection node: '
                             '{!r}'.format(indirection_el))

    return setgen.ensure_set(node, ctx=ctx)


def compile_type_check_op(
        expr: qlast.IsOp, *, ctx: context.ContextLevel) -> irast.TypeCheckOp:
    # <Expr> IS <TypeExpr>
    left = setgen.ensure_set(dispatch.compile(expr.left, ctx=ctx), ctx=ctx)
    ltype = setgen.get_set_type(left, ctx=ctx)
    typeref = typegen.ql_typeref_to_ir_typeref(expr.right, ctx=ctx)

    if ltype.is_object_type():
        left = setgen.ptr_step_set(
            left, source=ltype, ptr_name='__type__',
            direction=s_pointers.PointerDirection.Outbound,
            source_context=expr.context, ctx=ctx)
        pathctx.register_set_in_scope(left, ctx=ctx)
        result = None
    else:
        if ltype.is_collection() and ltype.contains_object():
            raise errors.QueryError(
                f'type checks on non-primitive collections are not supported'
            )

        test_type = irtyputils.ir_typeref_to_type(ctx.env.schema, typeref)
        result = ltype.issubclass(ctx.env.schema, test_type)

    return irast.TypeCheckOp(
        left=left, right=typeref, op=expr.op, result=result)


def flatten_set(expr: qlast.Set) -> typing.List[qlast.Expr]:
    elements = []
    for el in expr.elements:
        if isinstance(el, qlast.Set):
            elements.extend(flatten_set(el))
        else:
            elements.append(el)

    return elements
