##
# Copyright (c) 2008-2011 MagicStack Inc.
# All rights reserved.
#
# See LICENSE for details.
##


from metamagic.caos import proto, delta


class MetaDeltaRepository:

    def load_delta(self, id, compat_mode=False):
        raise NotImplementedError

    def delta_ref_to_id(self, ref):
        raise NotImplementedError

    def resolve_delta_ref(self, ref):
        ref = delta.DeltaRef.parse(ref)
        if not ref:
            raise delta.DeltaRefError('unknown revision: %s' % ref)
        return self.delta_ref_to_id(ref)

    def update_delta_ref(self, ref, id):
        raise NotImplementedError

    def write_delta(self, delta_obj):
        delta_set = delta.DeltaSet(deltas=[delta_obj])
        return self.write_delta_set(delta_set)

    def write_delta_set(self, delta_set):
        raise NotImplementedError

    def get_delta(self, id='HEAD', compat_mode=False):
        id = self.resolve_delta_ref(id)
        if id:
            return self.load_delta(id, compat_mode=compat_mode)
        else:
            return None

    def get_deltas(self, start_rev, end_rev=None, take_closest_snapshot=False):
        start_rev = start_rev
        end_rev = end_rev or self.resolve_delta_ref('HEAD')

        deltas = self.walk_deltas(end_rev, start_rev, reverse=True,
                                  take_closest_snapshot=take_closest_snapshot)
        return delta.DeltaSet(deltas)

    def walk_deltas(self, end_rev, start_rev, reverse=False,
                                   take_closest_snapshot=False,
                                   compat_mode=False):
        current_rev = end_rev

        if not reverse:
            while current_rev and current_rev != start_rev:
                delta = self.load_delta(current_rev, compat_mode=compat_mode)
                yield delta
                current_rev = delta.parent_id
        else:
            deltas = []

            while current_rev and current_rev != start_rev:
                delta = self.load_delta(current_rev, compat_mode=compat_mode)
                deltas.append(delta)
                if delta.snapshot is not None and take_closest_snapshot:
                    break
                current_rev = delta.parent_id

            for delta in reversed(deltas):
                yield delta

    def upgrade(self, start_rev=None, end_rev=None,
                      new_format_ver=delta.Delta.CURRENT_FORMAT_VERSION):

        if end_rev is None:
            end_rev = self.get_delta(id='HEAD', compat_mode=True).id

        schema = proto.ProtoSchema()

        context = delta.DeltaUpgradeContext(delta.Delta.CURRENT_FORMAT_VERSION)
        for d in self.walk_deltas(end_rev, start_rev, reverse=True,
                                                      compat_mode=True):
            d.upgrade(context, schema)
            d.apply(schema)
            d.checksum = schema.get_checksum()
            self.write_delta(d)

    def get_schema(self, delta_obj):
        deltas = self.get_deltas(None, delta_obj.id, take_closest_snapshot=True)
        schema = proto.ProtoSchema()
        deltas.apply(schema)
        return schema

    def get_schema_at(self, ref):
        if ref is None:
            return proto.ProtoSchema()
        else:
            delta = self.load_delta(ref)
            return self.get_schema(delta)

    def get_snapshot_at(self, ref):
        org_delta = self.get_delta(ref)
        full_delta = self.cumulative_delta(None, org_delta.id)
        snapshot = delta.Delta(parent_id=org_delta.parent_id, checksum=org_delta.checksum,
                               deltas=org_delta.deltas,
                               formatver=delta.Delta.CURRENT_FORMAT_VERSION,
                               comment=org_delta.comment, snapshot=full_delta)
        return snapshot

    def _cumulative_delta(self, ref1, ref2):
        delta = None
        v1 = self.load_delta(ref1) if ref1 else None

        if isinstance(ref2, proto.ProtoSchema):
            v2 = None
            v2_schema = ref2
        else:
            v2 = self.load_delta(ref2)
            v2_schema = self.get_schema(v2)

        if v1 is not None:
            v1_schema = self.get_schema(v1)
        else:
            v1_schema = proto.ProtoSchema()

        if v1 is None or v1.checksum != v2_schema.get_checksum():
            delta = v2_schema.delta(v1_schema)
        else:
            delta = None

        return v1, v1_schema, v2, v2_schema, delta

    def cumulative_delta(self, ref1, ref2):
        return self._cumulative_delta(ref1, ref2)[4]

    def calculate_delta(self, ref1, ref2, *, comment=None, preprocess=None, postprocess=None):
        v1, v1_schema, v2, v2_schema, d = self._cumulative_delta(ref1, ref2)

        if d is None and (preprocess is not None or postprocess is not None):
            d = delta.AlterRealm()

        if d is not None:
            d.preprocess = preprocess
            d.postprocess = postprocess

            parent_id = v1.id if v1 else None
            checksum = v2_schema.get_checksum()

            return delta.Delta(parent_id=parent_id, checksum=checksum,
                               comment=comment, deltas=[d],
                               formatver=delta.Delta.CURRENT_FORMAT_VERSION)
        else:
            return None
