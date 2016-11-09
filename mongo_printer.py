import gdb
import gdb.printing

import struct

try:
    import bson
    import bson.json_util
    import collections
    from bson.codec_options import CodecOptions
except ImportError:
    bson = None

class StringMapPrinter:
    def __init__(self, val):
        self.val = val

        # This is kinda gross, but it seems like the only way to get at value_type's type.
        valueTypeName = val.type.unqualified().target().name + "::value_type"
        valueType = gdb.lookup_type(valueTypeName).target()
        self.valueTypeRef = valueType.reference()

    def display_hint (self):
        return 'map'

    def to_string(self):
        return "StringMap<%s> with %s elems "%(self.val.type.template_argument(0),
                                               self.val["_size"])

    def children(self):
        cap = self.val["_area"]["_capacity"]
        it = self.val["_area"]["_entries"]["px"]
        end = it + cap

        while it != end:
            elt = it.dereference()
            it += 1
            if not elt['used']:
                continue

            value = elt['data'].reference().reinterpret_cast(self.valueTypeRef).dereference()
            yield ('k'+str(it), value['first'])
            yield ('v'+str(it), value['second'])

class StatusPrinter:
    OK = 0 # ErrorCodes::OK

    def __init__(self, val):
        self.val = val

    def to_string(self):
        code = self.code()
        if code == StatusPrinter.OK:
            return 'Status::OK()'

        # remove the mongo::ErrorCodes:: prefix. Does nothing if not a real ErrorCode.
        code = str(code).split('::')[-1]

        info = self.val['_error'].dereference()
        location = info['location']
        reason = info['reason']
        if location:
            return 'Status(%s, %s, %s)'%(code, reason, location)
        else:
            return 'Status(%s, %s)'%(code, reason)

    def code(self):
        if not self.val['_error']:
            return StatusPrinter.OK
        return self.val['_error'].dereference()['code']

class StringDataPrinter:
    def __init__(self, val):
        self.val = val

    def display_hint (self):
        return 'string'

    def to_string(self):
        size = self.val["_size"]
        if size == -1:
            return self.val['_data'].lazy_string()
        else:
            return self.val['_data'].lazy_string(length = size)

class BSONObjPrinter:
    def __init__(self, val):
        self.val = val
        self.ptr = self.val['_objdata'].cast(gdb.lookup_type('void').pointer())
        self.size = self.ptr.cast(gdb.lookup_type('int').pointer()).dereference()

    def display_hint(self):
        return 'map'

    def children(self):
        if bson is not None:
            inferior = gdb.selected_inferior()
            buf = bytes(inferior.read_memory(self.ptr, self.size))
            options = CodecOptions(document_class=collections.OrderedDict)
            bsondoc = bson.BSON.decode(buf, codec_options=options)
            index = 0
            for k, v in bsondoc.items():
                yield 'key', k
                yield 'value', bson.json_util.dumps(v)

    def to_string(self):
        ownership = "owned" if self.val['_ownedBuffer']['_buffer']['_holder']['px'] else "unowned"

        size = self.size
        if size < 5 or size > 17*1024*1024:
            #print invalid sizes in hex as they may be sentinel bytes.
            size = hex(size)

        if size == 5:
            return "%s empty BSONObj @ %s"%(ownership, self.ptr)
        else:
            return "%s BSONObj %s bytes @ %s"%(ownership, size, self.ptr)

def register_mongo_printers():
    pp = gdb.printing.RegexpCollectionPrettyPrinter("mongo")
    pp.add_printer('StringMap', '^mongo::StringMap<', StringMapPrinter)
    pp.add_printer('Status', '^mongo::Status$', StatusPrinter)
    pp.add_printer('StringData', '^mongo::StringData$', StringDataPrinter)
    pp.add_printer('BSONObj', '^mongo::BSONObj$', BSONObjPrinter)

    gdb.printing.register_pretty_printer(
        None,
        pp,
        replace=True)
