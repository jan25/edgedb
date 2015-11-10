##
# Copyright (c) 2008-2012 MagicStack Inc.
# All rights reserved.
#
# See LICENSE for details.
##


import json

import postgresql.string

from . import base


class DDLTriggerMeta(type):
    _triggers = {}
    _trigger_cache = {}

    def __new__(mcls, name, bases, dct):
        cls = super().__new__(mcls, name, bases, dct)
        if cls.operations:
            for op in cls.operations:
                try:
                    triggers = mcls._triggers[op]
                except KeyError:
                    triggers = mcls._triggers[op] = []

                triggers.append(cls)
                mcls._trigger_cache.clear()

        return cls

    @classmethod
    def get_triggers(mcls, opcls):
        try:
            triggers = mcls._trigger_cache[opcls]
        except KeyError:
            triggers = set()

            for cls in opcls.__mro__:
                try:
                    trg = mcls._triggers[cls]
                except KeyError:
                    pass
                else:
                    triggers.update(trg)

            mcls._trigger_cache[opcls] = triggers

        return triggers


class DDLTrigger(metaclass=DDLTriggerMeta):
    operations = None

    @classmethod
    def before(cls, context, op):
        pass

    @classmethod
    def after(cls, context, op):
        pass


class DDLOperation(base.Command):
    def execute(self, context):
        triggers = DDLTriggerMeta.get_triggers(self.__class__)

        for trigger in triggers:
            cmd = trigger.before(context, self)
            if cmd:
                cmd.execute(context)

        result = super().execute(context)

        for trigger in triggers:
            cmd = trigger.after(context, self)
            if cmd:
                cmd.execute(context)

        return result


class SchemaObjectOperation(DDLOperation):
    def __init__(self, name, *, conditions=None, neg_conditions=None, priority=0):
        super().__init__(conditions=conditions, neg_conditions=neg_conditions, priority=priority)

        self.name = name
        self.opid = name

    def __repr__(self):
        return '<caos.sync.%s %s>' % (self.__class__.__name__, self.name)


class Comment(DDLOperation):
    def __init__(self, object, text, **kwargs):
        super().__init__(**kwargs)

        self.object = object
        self.text = text

    def code(self, context):
        object_type = self.object.get_type()
        object_id = self.object.get_id()

        code = 'COMMENT ON {type} {id} IS {text}'.format(
                    type=object_type, id=object_id, text=postgresql.string.quote_literal(self.text))

        return code


class GetMetadata(base.Command):
    def __init__(self, object):
        super().__init__()
        self.object = object

    def code(self, context):
        code = '''
            SELECT
                substr(description, 5)::json
             FROM
                pg_description
             WHERE
                objoid = $1 AND classoid = $2 AND objsubid = $3
                AND substr(description, 1, 4) = '$CMR'
        '''

        oid = self.object.get_oid()
        if isinstance(oid, base.Command):
            oid = oid.execute(context)[0]

        return code, oid

    def _execute(self, context, code, vars):
        result = super()._execute(context, code, vars)

        if result:
            result = result[0][0]
        else:
            result = None

        return result


class PutMetadata(DDLOperation):
    def __init__(self, object, metadata, **kwargs):
        super().__init__(**kwargs)
        self.object = object
        self.metadata = metadata

    def _execute(self, context, code, vars):
        db = context.db

        metadata = self.metadata
        desc = '$CMR{}'.format(json.dumps(metadata))

        object_type = self.object.get_type()
        object_id = self.object.get_id()

        code = 'COMMENT ON {type} {id} IS {text}'.format(
                    type=object_type, id=object_id,
                    text=postgresql.string.quote_literal(desc))

        result = base.Query(code).execute(context)

        return result

    def __repr__(self):
        return '<{mod}.{cls} {object!r} {metadata!r}>' \
                .format(mod=self.__class__.__module__,
                        cls=self.__class__.__name__,
                        object=self.object,
                        metadata=self.metadata)


class SetMetadata(PutMetadata):
    def _execute(self, context, code, vars):
        db = context.db

        metadata = self.metadata
        desc = '$CMR{}'.format(json.dumps(metadata))

        object_type = self.object.get_type()
        object_id = self.object.get_id()

        code = 'COMMENT ON {type} {id} IS {text}'.format(
                    type=object_type, id=object_id,
                    text=postgresql.string.quote_literal(desc))

        result = base.Query(code).execute(context)

        return result


class UpdateMetadata(PutMetadata):
    def _execute(self, context, code, vars):
        db = context.db

        metadata = GetMetadata(self.object).execute(context)

        if metadata is None:
            metadata = {}

        metadata.update(self.metadata)

        desc = '$CMR{}'.format(json.dumps(metadata))

        object_type = self.object.get_type()
        object_id = self.object.get_id()

        code = 'COMMENT ON {type} {id} IS {text}'.format(
                    type=object_type, id=object_id,
                    text=postgresql.string.quote_literal(desc))

        result = base.Query(code).execute(context)

        return result


class CreateObject(DDLOperation):
    def extra(self, context):
        ops = super().extra(context)

        if self.object.metadata:
            if ops is None:
                ops = []

            mdata = SetMetadata(self.object, self.object.metadata)
            ops.append(mdata)

        return ops


class RenameObject(DDLOperation):
    def extra(self, context):
        ops = super().extra(context)

        if self.object.metadata:
            if ops is None:
                ops = []

            obj = self.object.copy()
            obj.name = self.new_name
            mdata = UpdateMetadata(obj, obj.metadata)
            ops.append(mdata)

        return ops


class AlterObject(DDLOperation):
    def extra(self, context):
        ops = super().extra(context)

        if self.object.metadata:
            if ops is None:
                ops = []

            mdata = UpdateMetadata(self.object, self.object.metadata)
            ops.append(mdata)

        return ops
