##
# Copyright (c) 2010 MagicStack Inc.
# All rights reserved.
#
# See LICENSE for details.
##


import sys

from metamagic.utils import ast
from metamagic.utils.ast import match as astmatch
from  . import ast as pgast


for name, cls in pgast.__dict__.items():
    if isinstance(cls, type) and issubclass(cls, ast.AST):
        adapter = astmatch.MatchASTMeta(name, (astmatch.MatchASTNode,), {'__module__': __name__},
                                        adapts=cls)
        setattr(sys.modules[__name__], name, adapter)
