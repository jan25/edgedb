##
# Copyright (c) 2008-2015 MagicStack Inc.
# All rights reserved.
#
# See LICENSE for details.
##


from edgedb.lang.common import ast
from edgedb.lang.common import parsing, context

from edgedb.lang.edgeql import ast as qlast

from ...errors import EdgeQLSyntaxError

from . import keywords

from .precedence import *  # NOQA
from .tokens import *  # NOQA


class Nonterm(context.Nonterm):
    pass


class SelectExpr(Nonterm):
    @parsing.precedence(P_UMINUS)
    def reduce_SelectNoParens(self, *kids):
        self.val = kids[0].val

    @parsing.precedence(P_UMINUS)
    def reduce_SelectWithParens(self, *kids):
        self.val = kids[0].val


class SelectWithParens(Nonterm):
    def reduce_LPAREN_SelectNoParens_RPAREN(self, *kids):
        self.val = kids[1].val

    def reduce_LPAREN_SelectWithParens_RPAREN(self, *kids):
        self.val = kids[1].val


class SelectNoParens(Nonterm):
    def reduce_AliasBlock_SelectClause_OptSortClause_OptSelectLimit(
            self, *kids):
        qry = kids[1].val
        qry.orderby = kids[2].val
        qry.offset = kids[3].val[0]
        qry.limit = kids[3].val[1]
        (qry.namespaces, qry.aliases) = kids[0].val

        self.val = qry

    def reduce_AliasBlock_WithClause_SelectClause_OptSortClause_OptSelectLimit(
            self, *kids):
        qry = kids[2].val
        qry.orderby = kids[3].val
        qry.offset = kids[4].val[0]
        qry.limit = kids[4].val[1]
        (qry.namespaces, qry.aliases) = kids[0].val
        qry.cges = kids[1].val

        self.val = qry

    def reduce_WithClause_SelectClause_OptSortClause_OptSelectLimit(
            self, *kids):
        qry = kids[1].val
        qry.orderby = kids[2].val
        qry.offset = kids[3].val[0]
        qry.limit = kids[3].val[1]
        qry.cges = kids[0].val

        self.val = qry

    def reduce_SimpleSelect_OptSelectLimit(self, *kids):
        qry = kids[0].val
        qry.offset = kids[1].val[0]
        qry.limit = kids[1].val[1]
        self.val = qry

    def reduce_SelectClause_SortClause_OptSelectLimit(self, *kids):
        qry = kids[0].val
        qry.orderby = kids[1].val
        qry.offset = kids[2].val[0]
        qry.limit = kids[2].val[1]

        self.val = qry


class WithClause(Nonterm):
    def reduce_WITH_CgeList(self, *kids):
        self.val = kids[1].val


class Cge(Nonterm):
    def reduce_ShortName_AS_LPAREN_SelectExpr_RPAREN(self, *kids):
        self.val = qlast.CGENode(expr=kids[3].val, alias=kids[0].val)


class CgeList(parsing.ListNonterm, element=Cge, separator=T_COMMA):
    pass


class SelectClause(Nonterm):
    def reduce_SimpleSelect(self, *kids):
        self.val = kids[0].val

    def reduce_SelectWithParens(self, *kids):
        self.val = kids[0].val


class SimpleSelect(Nonterm):
    def reduce_Select(self, *kids):
        r"%reduce SELECT OptDistinct SelectTargetList \
                  OptWhereClause OptGroupClause"
        self.val = qlast.SelectQueryNode(
            distinct=kids[1].val,
            targets=kids[2].val,
            where=kids[3].val,
            groupby=kids[4].val
        )

    def reduce_SelectClause_UNION_OptAll_SelectClause(self, *kids):
        self.val = qlast.SelectQueryNode(
            op=qlast.UNION,
            op_larg=kids[0].val,
            op_rarg=kids[3].val
        )

    def reduce_SelectClause_INTERSECT_OptAll_SelectClause(self, *kids):
        self.val = qlast.SelectQueryNode(
            op=qlast.INTERSECT,
            op_larg=kids[0].val,
            op_rarg=kids[3].val
        )

    def reduce_SelectClause_EXCEPT_OptAll_SelectClause(self, *kids):
        self.val = qlast.SelectQueryNode(
            op=qlast.EXCEPT,
            op_larg=kids[0].val,
            op_rarg=kids[3].val
        )


class OptAliasBlock(Nonterm):
    def reduce_AliasBlock(self, *kids):
        self.val = kids[0].val

    def reduce_empty(self, *kids):
        self.val = ([], [])


class AliasBlock(Nonterm):
    def reduce_USING_AliasDeclList(self, *kids):
        nsaliases = []
        expraliases = []

        for alias in kids[1].val:
            if isinstance(alias, qlast.NamespaceAliasDeclNode):
                nsaliases.append(alias)
            else:
                expraliases.append(alias)

        self.val = (nsaliases, expraliases)


class ModuleName(Nonterm):
    def reduce_IDENT(self, *kids):
        self.val = [kids[0].val]


class AliasDecl(Nonterm):
    def reduce_NAMESPACE_ModuleName(self, *kids):
        self.val = qlast.NamespaceAliasDeclNode(
            namespace='.'.join(kids[1].val))

    def reduce_ShortName_TURNSTILE_NAMESPACE_ModuleName(self, *kids):
        self.val = qlast.NamespaceAliasDeclNode(
            alias=kids[0].val,
            namespace='.'.join(kids[3].val))

    def reduce_ShortName_TURNSTILE_Expr(self, *kids):
        self.val = qlast.ExpressionAliasDeclNode(
            alias=kids[0].val,
            expr=kids[2].val)


class AliasDeclList(parsing.ListNonterm, element=AliasDecl, separator=T_COMMA):
    pass


class OptDistinct(Nonterm):
    def reduce_DISTINCT(self, *kids):
        self.val = True

    def reduce_empty(self, *kids):
        self.val = False


class SelectTargetEl(Nonterm):
    def reduce_Expr_AS_ShortName(self, *kids):
        self.val = qlast.SelectExprNode(expr=kids[0].val, alias=kids[2].val)

    def reduce_Expr(self, *kids):
        self.val = qlast.SelectExprNode(expr=kids[0].val)

    def reduce_Expr_Shape(self, *kids):
        tshape = kids[0].val
        if (not isinstance(tshape, qlast.PathNode) or
                tshape.pathspec):
            raise EdgeQLSyntaxError('unexpected shape',
                                    context=kids[1].val.context)

        tshape.pathspec = kids[1].val
        self.val = qlast.SelectExprNode(expr=tshape)


class SelectTargetList(parsing.ListNonterm, element=SelectTargetEl,
                       separator=T_COMMA):
    pass


class Shape(Nonterm):
    def reduce_LBRACE_SelectPointerSpecList_RBRACE(self, *kids):
        self.val = kids[1].val


class TypedShape(Nonterm):
    def reduce_NodeName_Shape(self, *kids):
        self.val = qlast.PathNode(
            steps=[qlast.PathStepNode(expr=kids[0].val.name,
                                      namespace=kids[0].val.module)],
            pathspec=kids[1].val)


class OptAnySubShape(Nonterm):
    def reduce_COLON_Shape(self, *kids):
        self.val = kids[1].val

    def reduce_COLON_TypedShape(self, *kids):
        self.val = kids[1].val

    def reduce_empty(self, *kids):
        self.val = None


class SelectPointerSpec(Nonterm):
    def reduce_PointerGlob(self, *kids):
        self.val = kids[0].val

    def reduce_AT_NodeName(self, *kids):
        from edgedb.lang.schema import pointers as s_pointers

        self.val = qlast.SelectPathSpecNode(
            expr=qlast.LinkExprNode(
                expr=qlast.LinkNode(
                    name=kids[1].val.name, namespace=kids[1].val.module,
                    direction=s_pointers.PointerDirection.Outbound,
                    type='property'
                )
            )
        )

    def reduce_PointerSpecWithSubShape(self, *kids):
        r"""%reduce PointerSpecSetExpr OptPointerRecursionSpec \
             OptAnySubShape OptWhereClause OptSortClause OptSelectLimit \
        """
        self.val = kids[0].val
        if isinstance(self.val, qlast.SelectTypeRefNode):
            self.val.attrs = [s.expr for s in kids[2].val]
        else:
            self.val.recurse = kids[1].val
            self.val.pathspec = kids[2].val
            self.val.where = kids[3].val
            self.val.orderby = kids[4].val
            self.val.offset = kids[5].val[0]
            self.val.limit = kids[5].val[1]

    def reduce_PointerSpecSetExpr_OptPointerRecursionSpec_TURNSTILE_Expr(
            self, *kids):
        self.val = kids[0].val
        self.val.recurse = kids[1].val
        self.val.compexpr = kids[3].val


class SelectPointerSpecList(parsing.ListNonterm, element=SelectPointerSpec,
                            separator=T_COMMA):
    pass


class FQPathExpr(Nonterm):
    def reduce_LinkDirection_FQPathPtr(self, *kids):
        self.val = kids[1].val
        self.val.direction = kids[0].val

    def reduce_FQPathPtr(self, *kids):
        from edgedb.lang.schema import pointers as s_pointers
        self.val = kids[0].val
        self.val.direction = s_pointers.PointerDirection.Outbound


class FQPathPtr(Nonterm):
    def reduce_FQPathStepName(self, *kids):
        self.val = qlast.LinkNode(name=kids[0].val.name,
                                  namespace=kids[0].val.module)

    def reduce_FQPathPtrParen(self, *kids):
        self.val = kids[0].val


class FQPathPtrParen(Nonterm):
    def reduce_LPAREN_FQPathPtrParen_RPAREN(self, *kids):
        self.val = kids[1].val

    def reduce_LPAREN_FQPathStepName_RPAREN(self, *kids):
        self.val = qlast.LinkNode(name=kids[1].val.name,
                                  namespace=kids[1].val.module)


class PointerSpecSetExpr(Nonterm):
    def reduce_FQPathExpr(self, *kids):
        self.val = qlast.SelectPathSpecNode(
            expr=qlast.LinkExprNode(expr=kids[0].val)
        )

    def reduce_TYPEINDIRECTION(self, *kids):
        # fill out attrs later from the shape
        self.val = qlast.SelectTypeRefNode()


class OptPointerRecursionSpec(Nonterm):
    def reduce_STAR(self, *kids):
        self.val = qlast.ConstantNode(value=0)

    def reduce_STAR_NumberConstant(self, *kids):
        self.val = kids[1].val

    def reduce_empty(self, *kids):
        self.val = None


class PointerGlob(Nonterm):
    def reduce_STAR(self, *kids):
        flt = qlast.PointerGlobFilter(property='loading', value='eager')
        self.val = qlast.PointerGlobNode(filters=[flt], type='link')

    def reduce_STAR_LPAREN_PointerGlobFilterList_RPAREN(self, *kids):
        self.val = qlast.PointerGlobNode(filters=kids[2].val, type='link')

    def reduce_AT_STAR(self, *kids):
        flt = qlast.PointerGlobFilter(property='loading', value='eager')
        self.val = qlast.PointerGlobNode(filters=[flt], type='property')

    def reduce_AT_STAR_LPAREN_PointerGlobFilterList_RPAREN(self, *kids):
        self.val = qlast.PointerGlobNode(filters=kids[2].val, type='property')


class PointerGlobFilter(Nonterm):
    def reduce_ShortName_EQUALS_ShortName(self, *kids):
        self.val = qlast.PointerGlobFilter(property=kids[0].val,
                                           value=kids[2].val)

    def reduce_ANY_ShortName(self, *kids):
        self.val = qlast.PointerGlobFilter(property=kids[1].val, any=True)


class PointerGlobFilterList(parsing.ListNonterm, element=PointerGlobFilter,
                            separator=T_COMMA):
    pass


class WhereClause(Nonterm):
    def reduce_WHERE_Expr(self, *kids):
        self.val = kids[1].val


class OptWhereClause(Nonterm):
    def reduce_WhereClause(self, *kids):
        self.val = kids[0].val

    def reduce_empty(self, *kids):
        self.val = None


class OptGroupClause(Nonterm):
    def reduce_GROUP_BY_ExprList(self, *kids):
        self.val = kids[2].val

    def reduce_empty(self, *kids):
        self.val = None


class SortClause(Nonterm):
    def reduce_ORDER_BY_OrderbyList(self, *kids):
        self.val = kids[2].val


class OptSortClause(Nonterm):
    def reduce_SortClause(self, *kids):
        self.val = kids[0].val

    def reduce_empty(self, *kids):
        self.val = None


class OrderbyExpr(Nonterm):
    def reduce_Expr_OptDirection_OptNonesOrder(self, *kids):
        self.val = qlast.SortExprNode(path=kids[0].val,
                                      direction=kids[1].val,
                                      nones_order=kids[2].val)


class OrderbyList(parsing.ListNonterm, element=OrderbyExpr, separator=T_THEN):
    pass


class OptSelectLimit(Nonterm):
    def reduce_SelectLimit(self, *kids):
        self.val = kids[0].val

    def reduce_empty(self, *kids):
        self.val = (None, None)


class SelectLimit(Nonterm):
    def reduce_OffsetClause_LimitClause(self, *kids):
        self.val = (kids[0].val, kids[1].val)

    def reduce_OffsetClause(self, *kids):
        self.val = (kids[0].val, None)

    def reduce_LimitClause(self, *kids):
        self.val = (None, kids[0].val)


class OffsetClause(Nonterm):
    def reduce_OFFSET_NumberConstant(self, *kids):
        self.val = kids[1].val


class LimitClause(Nonterm):
    def reduce_LIMIT_NumberConstant(self, *kids):
        self.val = kids[1].val


class OptDirection(Nonterm):
    def reduce_ASC(self, *kids):
        self.val = qlast.SortAsc

    def reduce_DESC(self, *kids):
        self.val = qlast.SortDesc

    def reduce_empty(self, *kids):
        self.val = qlast.SortDefault


class OptNonesOrder(Nonterm):
    def reduce_NONES_FIRST(self, *kids):
        self.val = qlast.NonesFirst

    def reduce_NONES_LAST(self, *kids):
        self.val = qlast.NonesLast

    def reduce_empty(self, *kids):
        self.val = None


class OptAll(Nonterm):
    def reduce_ALL(self, *kids):
        self.val = True

    def reduce_empty(self, *kids):
        self.val = None


class IndirectionEl(Nonterm):
    def reduce_LBRACKET_Expr_RBRACKET(self, *kids):
        self.val = qlast.IndexNode(index=kids[1].val)

    def reduce_LBRACKET_Expr_COLON_Expr_RBRACKET(self, *kids):
        self.val = qlast.SliceNode(start=kids[1].val, stop=kids[3].val)

    def reduce_LBRACKET_Expr_COLON_RBRACKET(self, *kids):
        self.val = qlast.SliceNode(start=kids[1].val, stop=None)

    def reduce_LBRACKET_COLON_Expr_RBRACKET(self, *kids):
        self.val = qlast.SliceNode(start=None, stop=kids[2].val)


class ParenExpr(Nonterm):
    def reduce_LPAREN_Expr_RPAREN(self, *kids):
        self.val = kids[1].val

    def reduce_LPAREN_OpPath_RPAREN(self, *kids):
        self.val = kids[1].val


class Expr(Nonterm):
    # Path | Constant | '(' Expr ')' | FuncExpr | Sequence | Mapping
    # | '+' Expr | '-' Expr | Expr '+' Expr | Expr '-' Expr
    # | Expr '*' Expr | Expr '/' Expr | Expr '%' Expr
    # | Expr '^' Expr | Expr '<' Expr | Expr '>' Expr
    # | Expr '=' Expr
    # | Expr AND Expr | Expr OR Expr | NOT Expr
    # | Expr LIKE Expr | Expr NOT LIKE Expr
    # | Expr ILIKE Expr | Expr NOT ILIKE Expr
    # | Expr IS Expr | Expr IS NOT Expr
    # | Expr IS OF '(' NodeNameList ')'
    # | Expr IS NOT OF '(' NodeNameList ')'
    # | Expr IN Expr | Expr NOT IN Expr
    # | '<' ExtTypeExpr '>' '(' Expr ')'

    def reduce_Path(self, *kids):
        self.val = kids[0].val

    def reduce_Constant(self, *kids):
        self.val = kids[0].val

    def reduce_ParenExpr(self, *kids):
        self.val = kids[0].val

    def reduce_Expr_IndirectionEl(self, *kids):
        expr = kids[0].val
        if isinstance(expr, qlast.IndirectionNode):
            self.val = expr
            expr.indirection.append(kids[1].val)
        else:
            self.val = qlast.IndirectionNode(arg=expr,
                                             indirection=[kids[1].val])

    def reduce_FuncExpr(self, *kids):
        self.val = kids[0].val

    @parsing.precedence(P_UMINUS)
    def reduce_SelectWithParens(self, *kids):
        self.val = kids[0].val

    def reduce_EXISTS_SelectWithParens(self, *kids):
        self.val = qlast.ExistsPredicateNode(expr=kids[1].val)

    def reduce_EXISTS_LPAREN_Expr_RPAREN(self, *kids):
        self.val = qlast.ExistsPredicateNode(expr=kids[2].val)

    def reduce_Sequence(self, *kids):
        self.val = kids[0].val

    def reduce_Mapping(self, *kids):
        self.val = kids[0].val

    @parsing.precedence(P_UMINUS)
    def reduce_PLUS_Expr(self, *kids):
        self.val = qlast.UnaryOpNode(op=ast.ops.UPLUS, operand=kids[1].val)

    @parsing.precedence(P_UMINUS)
    def reduce_MINUS_Expr(self, *kids):
        self.val = qlast.UnaryOpNode(op=ast.ops.UMINUS, operand=kids[1].val)

    def reduce_Expr_PLUS_Expr(self, *kids):
        self.val = qlast.BinOpNode(left=kids[0].val, op=ast.ops.ADD,
                                   right=kids[2].val)

    def reduce_Expr_MINUS_Expr(self, *kids):
        self.val = qlast.BinOpNode(left=kids[0].val, op=ast.ops.SUB,
                                   right=kids[2].val)

    def reduce_Expr_STAR_Expr(self, *kids):
        self.val = qlast.BinOpNode(left=kids[0].val, op=ast.ops.MUL,
                                   right=kids[2].val)

    def reduce_Expr_SLASH_Expr(self, *kids):
        self.val = qlast.BinOpNode(left=kids[0].val, op=ast.ops.DIV,
                                   right=kids[2].val)

    def reduce_Expr_PERCENT_Expr(self, *kids):
        self.val = qlast.BinOpNode(left=kids[0].val, op=ast.ops.MOD,
                                   right=kids[2].val)

    def reduce_Expr_STARSTAR_Expr(self, *kids):
        self.val = qlast.BinOpNode(left=kids[0].val, op=ast.ops.POW,
                                   right=kids[2].val)

    def reduce_Expr_LANGBRACKET_Expr(self, *kids):
        self.val = qlast.BinOpNode(left=kids[0].val, op=ast.ops.LT,
                                   right=kids[2].val)

    def reduce_Expr_RANGBRACKET_Expr(self, *kids):
        self.val = qlast.BinOpNode(left=kids[0].val, op=ast.ops.GT,
                                   right=kids[2].val)

    def reduce_Expr_EQUALS_Expr(self, *kids):
        self.val = qlast.BinOpNode(left=kids[0].val, op=ast.ops.EQ,
                                   right=kids[2].val)

    @parsing.precedence(P_OP)
    def reduce_Expr_OP_Expr(self, *kids):
        op = kids[1].val
        if op == '!=':
            op = ast.ops.NE
        elif op == '==':
            op = ast.ops.EQ
        elif op == '>=':
            op = ast.ops.GE
        elif op == '<=':
            op = ast.ops.LE
        elif op == '@@':
            op = qlast.SEARCH
        elif op == '@@!':
            op = qlast.SEARCHEX
        elif op == '~':
            op = qlast.REMATCH
        elif op == '~*':
            op = qlast.REIMATCH

        self.val = qlast.BinOpNode(left=kids[0].val, op=op, right=kids[2].val)

    @parsing.precedence(P_OP)
    def reduce_OP_Expr(self, *kids):
        self.val = qlast.UnaryOpNode(op=kids[0].val, operand=kids[1].val)

    # @parsing.precedence(P_POSTFIXOP)
    # def reduce_Expr_OP(self, *kids):
    #     self.val = qlast.PostfixOpNode(op=kids[1].val, operand=kids[0].val)

    def reduce_Expr_AND_Expr(self, *kids):
        self.val = qlast.BinOpNode(left=kids[0].val, op=ast.ops.AND,
                                   right=kids[2].val)

    def reduce_Expr_OR_Expr(self, *kids):
        self.val = qlast.BinOpNode(left=kids[0].val, op=ast.ops.OR,
                                   right=kids[2].val)

    def reduce_NOT_Expr(self, *kids):
        self.val = qlast.UnaryOpNode(op=ast.ops.NOT, operand=kids[1].val)

    def reduce_Expr_LIKE_Expr(self, *kids):
        self.val = qlast.BinOpNode(left=kids[0].val, op=qlast.LIKE,
                                   right=kids[2].val)

    def reduce_Expr_NOT_LIKE_Expr(self, *kids):
        val = qlast.BinOpNode(left=kids[0].val, op=qlast.LIKE,
                              right=kids[2].val)
        self.val = qlast.UnaryOpNode(op=ast.ops.NOT, operand=val)

    def reduce_Expr_ILIKE_Expr(self, *kids):
        self.val = qlast.BinOpNode(left=kids[0].val, op=qlast.ILIKE,
                                   right=kids[2].val)

    def reduce_Expr_NOT_ILIKE_Expr(self, *kids):
        val = qlast.BinOpNode(left=kids[0].val, op=qlast.ILIKE,
                              right=kids[2].val)
        self.val = qlast.UnaryOpNode(op=ast.ops.NOT, operand=val)

    @parsing.precedence(P_IS)
    def reduce_Expr_IS_NONE(self, *kids):
        self.val = qlast.NoneTestNode(expr=kids[0].val)

    @parsing.precedence(P_IS)
    def reduce_Expr_IS_NOT_NONE(self, *kids):
        nt = qlast.NoneTestNode(expr=kids[0].val)
        self.val = qlast.UnaryOpNode(op=ast.ops.NOT, operand=nt)

    def reduce_Expr_INSTANCEOF_Expr(self, *kids):
        self.val = qlast.BinOpNode(left=kids[0].val, op=ast.ops.INSTANCEOF,
                                   right=isexpr)

    def reduce_Expr_IN_Expr(self, *kids):
        inexpr = kids[2].val
        self.val = qlast.BinOpNode(left=kids[0].val, op=ast.ops.IN,
                                   right=inexpr)

    @parsing.precedence(P_IN)
    def reduce_Expr_NOT_IN_Expr(self, *kids):
        inexpr = kids[3].val
        self.val = qlast.BinOpNode(left=kids[0].val, op=ast.ops.NOT_IN,
                                   right=inexpr)

    @parsing.precedence(P_TYPECAST)
    def reduce_LANGBRACKET_ExtTypeExpr_RANGBRACKET_Expr(
            self, *kids):
        self.val = qlast.TypeCastNode(expr=kids[3].val, type=kids[1].val)


class Sequence(Nonterm):
    def reduce_LPAREN_Expr_COMMA_OptExprList_RPAREN(self, *kids):
        self.val = qlast.SequenceNode(elements=[kids[1].val] + kids[3].val)


class Mapping(Nonterm):
    def reduce_LBRACE_MappingElementsList_RBRACE(self, *kids):
        self.val = qlast.MappingNode(items=kids[1].val)


class MappingElement(Nonterm):
    def reduce_SCONST_COLON_Expr(self, *kids):
        self.val = (qlast.ConstantNode(value=kids[0].val), kids[2].val)


class MappingElementsList(parsing.ListNonterm, element=MappingElement,
                          separator=T_COMMA):
    pass


class OptExprList(Nonterm):
    def reduce_ExprList(self, *kids):
        self.val = kids[0].val

    def reduce_empty(self, *kids):
        self.val = []


class ExprList(parsing.ListNonterm, element=Expr, separator=T_COMMA):
    pass


class Constant(Nonterm):
    # BaseConstant
    # | BaseNumberConstant
    # | BaseStringConstant
    # | BaseBooleanConstant

    def reduce_BaseConstant(self, *kids):
        self.val = kids[0].val

    def reduce_BaseNumberConstant(self, *kids):
        self.val = kids[0].val

    def reduce_BaseStringConstant(self, *kids):
        self.val = kids[0].val

    def reduce_BaseBooleanConstant(self, *kids):
        self.val = kids[0].val


class BaseConstant(Nonterm):
    # NoneConstant
    # | ArgConstant

    def reduce_NoneConstant(self, *kids):
        self.val = kids[0].val

    def reduce_ArgConstant(self, *kids):
        self.val = kids[0].val


class NoneConstant(Nonterm):
    def reduce_NONE(self, *kids):
        self.val = qlast.ConstantNode(value=None)


class ArgConstant(Nonterm):
    def reduce_DOLLAR_ICONST(self, *kids):
        self.val = qlast.ConstantNode(value=None, index=int(kids[1].val))

    def reduce_DOLLAR_ShortName(self, *kids):
        self.val = qlast.ConstantNode(value=None, index=str(kids[1].val))


class BaseNumberConstant(Nonterm):
    def reduce_ICONST(self, *kids):
        self.val = qlast.ConstantNode(value=int(kids[0].val))

    def reduce_FCONST(self, *kids):
        self.val = qlast.ConstantNode(value=float(kids[0].val))


class NumberConstant(Nonterm):
    def reduce_BaseConstant(self, *kids):
        self.val = kids[0].val

    def reduce_BaseNumberConstant(self, *kids):
        self.val = kids[0].val


class BaseStringConstant(Nonterm):
    def reduce_SCONST(self, *kids):
        self.val = qlast.ConstantNode(value=str(kids[0].val))


class BaseBooleanConstant(Nonterm):
    def reduce_TRUE(self, *kids):
        self.val = qlast.ConstantNode(value=True)

    def reduce_FALSE(self, *kids):
        self.val = qlast.ConstantNode(value=False)


# this is used inside parentheses or in shapes
#
class OpPath(Nonterm):
    @parsing.precedence(P_PATHSTART)
    def reduce_OpName(self, *kids):
        self.val = qlast.PathNode(
            steps=[qlast.PathStepNode(expr=kids[0].val.name,
                                      namespace=kids[0].val.module)])


class Path(Nonterm):
    @parsing.precedence(P_PATHSTART)
    def reduce_NodeName(self, *kids):
        self.val = qlast.PathNode(
            steps=[qlast.PathStepNode(expr=kids[0].val.name,
                                      namespace=kids[0].val.module)])

    @parsing.precedence(P_DOT)
    def reduce_Expr_PathStep(self, *kids):
        path = kids[0].val
        if not isinstance(path, qlast.PathNode):
            raise EdgeQLSyntaxError('illegal path node',
                                    context=kids[1].val.context)

        path.steps.append(kids[1].val)
        self.val = path


class PathStep(Nonterm):
    def reduce_DOT_PathExprOrType(self, *kids):
        self.val = qlast.LinkExprNode(expr=kids[1].val)

    def reduce_AT_PathExpr(self, *kids):
        self.val = qlast.LinkPropExprNode(expr=kids[1].val)
        kids[1].val.type = 'property'


class PathExprOrType(Nonterm):
    def reduce_PathExpr(self, *kids):
        self.val = kids[0].val

    def reduce_TYPEINDIRECTION(self, *kids):
        self.val = qlast.TypeIndirection()


class PathExpr(Nonterm):
    def reduce_LinkDirection_PathPtr(self, *kids):
        self.val = kids[1].val
        self.val.direction = kids[0].val

    def reduce_PathPtr(self, *kids):
        from edgedb.lang.schema import pointers as s_pointers
        self.val = kids[0].val
        self.val.direction = s_pointers.PointerDirection.Outbound


class PathPtr(Nonterm):
    def reduce_PathStepName(self, *kids):
        self.val = qlast.LinkNode(name=kids[0].val.name,
                                  namespace=kids[0].val.module)

    def reduce_PathPtrParen(self, *kids):
        self.val = kids[0].val


class PathPtrParen(Nonterm):
    def reduce_LPAREN_PathPtrParen_RPAREN(self, *kids):
        self.val = kids[1].val

    def reduce_LPAREN_FQPathStepName_RPAREN(self, *kids):
        self.val = qlast.LinkNode(name=kids[1].val.name,
                                  namespace=kids[1].val.module)

    def reduce_LPAREN_NodeName_TO_NodeName_RPAREN(self, *kids):
        self.val = qlast.LinkNode(
            name=kids[1].val.name,
            namespace=kids[1].val.module,
            target=kids[3].val)


class LinkDirection(Nonterm):
    def reduce_LANGBRACKET(self, *kids):
        from edgedb.lang.schema import pointers as s_pointers
        self.val = s_pointers.PointerDirection.Inbound

    def reduce_RANGBRACKET(self, *kids):
        from edgedb.lang.schema import pointers as s_pointers
        self.val = s_pointers.PointerDirection.Outbound


class OptFilterClause(Nonterm):
    def reduce_FILTER_LPAREN_WhereClause_RPAREN(self, *kids):
        self.val = kids[2].val

    def reduce_empty(self, *kids):
        self.val = None


class FuncApplication(Nonterm):
    def reduce_FuncApplication(self, *kids):
        r"""%reduce NodeName LPAREN OptFuncArgList OptSortClause \
                    RPAREN OptFilterClause \
        """
        module = kids[0].val.module
        func_name = kids[0].val.name
        args = kids[2].val

        if not module and func_name == 'type':
            if len(args) != 1:
                msg = 'type() takes exactly one argument, {} given' \
                    .format(len(args))
                raise EdgeQLSyntaxError(msg, context=args[1].context)
            self.val = qlast.TypeRefNode(expr=args[0])
        else:
            name = func_name if not module else (module, func_name)
            self.val = qlast.FunctionCallNode(func=name, args=args,
                                              agg_sort=kids[3].val,
                                              agg_filter=kids[5].val)


class FuncExpr(Nonterm):
    def reduce_FuncApplication_OptOverClause(self, *kids):
        self.val = kids[0].val
        self.val.window = kids[1].val


class OptOverClause(Nonterm):
    def reduce_OVER_WindowSpec(self, *kids):
        self.val = kids[1].val

    def reduce_empty(self, *kids):
        self.val = None


class WindowSpec(Nonterm):
    def reduce_LPAREN_OptPartitionClause_OptSortClause_RPAREN(self, *kids):
        self.val = qlast.WindowSpecNode(
            partition=kids[1].val,
            orderby=kids[2].val
        )


class OptPartitionClause(Nonterm):
    def reduce_PARTITION_BY_ExprList(self, *kids):
        self.val = kids[2].val

    def reduce_empty(self, *kids):
        self.val = None


class FuncArgExpr(Nonterm):
    def reduce_Expr(self, *kids):
        self.val = kids[0].val

    def reduce_ParamName_TURNSTILE_Expr(self, *kids):
        self.val = qlast.NamedArgNode(name=kids[0].val, arg=kids[2].val)


class FuncArgList(parsing.ListNonterm, element=FuncArgExpr, separator=T_COMMA):
    pass


class OptFuncArgList(Nonterm):
    def reduce_FuncArgList(self, *kids):
        self.val = kids[0].val

    def reduce_empty(self, *kids):
        self.val = []


class Identifier(Nonterm):
    def reduce_IDENT(self, *kids):
        self.val = kids[0].val

    def reduce_UnreservedKeyword(self, *kids):
        self.val = kids[0].val


class AnyIdentifier(Nonterm):
    def reduce_Identifier(self, *kids):
        self.val = kids[0].val

    def reduce_ReservedKeyword(self, *kids):
        self.val = kids[0].val


class ShortName(Nonterm):
    def reduce_IDENT(self, *kids):
        self.val = kids[0].val


# this can appear anywhere
#
class BaseName(Nonterm):
    def reduce_IDENT(self, *kids):
        self.val = [kids[0].val]

    def reduce_IDENT_DOUBLECOLON_AnyIdentifier(self, *kids):
        self.val = [kids[0].val, kids[2].val]


# this can appear anywhere after parentheses or operator
#
class OpName(Nonterm):
    def reduce_UnreservedKeyword(self, *kids):
        self.val = [kids[0].val]

    def reduce_UnreservedKeyword_DOUBLECOLON_AnyIdentifier(self, *kids):
        self.val = [kids[0].val, kids[2].val]


class TypeName(Nonterm):
    def reduce_NodeName(self, *kids):
        self.val = qlast.TypeNameNode(maintype=kids[0].val)

    def reduce_NodeName_LANGBRACKET_NodeNameList_RANGBRACKET(self, *kids):
        self.val = qlast.TypeNameNode(maintype=kids[0].val,
                                      subtypes=kids[2].val)


class ExtTypeExpr(Nonterm):
    def reduce_TypeName(self, *kids):
        self.val = kids[0].val

    def reduce_TypedShape(self, *kids):
        self.val = kids[0].val


class ParamName(Nonterm):
    def reduce_IDENT(self, *kids):
        self.val = kids[0].val

    def reduce_UnreservedKeyword(self, *kids):
        self.val = kids[0].val


class NodeName(Nonterm):
    def reduce_BaseName(self, *kids):
        # NodeName cannot start with a '@' in any way
        #
        if kids[0].val[0][0] == '@':
            raise EdgeQLSyntaxError("name cannot start with '@'")
        self.val = qlast.PrototypeRefNode(
            module='.'.join(kids[0].val[:-1]) or None,
            name=kids[0].val[-1])


class PathStepName(Nonterm):
    def reduce_Identifier(self, *kids):
        # PathStepName cannot start with a '@' in any way
        #
        self.val = qlast.PrototypeRefNode(
            module=None,
            name=kids[0].val)


class FQPathStepName(Nonterm):
    def reduce_NodeName(self, *kids):
        self.val = kids[0].val

    def reduce_OpName(self, *kids):
        # FQPathStepName cannot start with a '@' in any way
        #
        self.val = qlast.PrototypeRefNode(
            module='.'.join(kids[0].val[:-1]) or None,
            name=kids[0].val[-1])


class NodeNameList(parsing.ListNonterm, element=NodeName, separator=T_COMMA):
    pass


class KeywordMeta(context.ContextNontermMeta):
    def __new__(mcls, name, bases, dct, *, type):
        result = super().__new__(mcls, name, bases, dct)

        assert type in keywords.keyword_types

        for val, token in keywords.by_type[type].items():
            def method(inst, *kids):
                inst.val = kids[0].val
            method.__doc__ = "%%reduce %s" % token
            method.__name__ = 'reduce_%s' % token
            setattr(result, method.__name__, method)

        return result

    def __init__(cls, name, bases, dct, *, type):
        super().__init__(name, bases, dct)


class UnreservedKeyword(Nonterm, metaclass=KeywordMeta,
                        type=keywords.UNRESERVED_KEYWORD):
    pass


class ReservedKeyword(Nonterm, metaclass=KeywordMeta,
                      type=keywords.RESERVED_KEYWORD):
    pass