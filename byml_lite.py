import struct
class Byml:
    def __init__(s,d):
        s.d=d; s.e='<' if d[:2]==b'YB' else '>'
        s.ver,ko,so,ro=struct.unpack_from(s.e+'HIII',d,2)
        s.keys=s.strtab(ko) if ko else []
        s.strs=s.strtab(so) if so else []
        s.root=s.node(d[ro],ro) if ro else None
    def u24(s,d,o):
        return int.from_bytes(d[o:o+3],'little' if s.e=='<' else 'big')
    def strtab(s,o):
        d=s.d; assert d[o]==0xC2; n=s.u24(d,o+1)
        offs=struct.unpack_from(s.e+'%dI'%(n+1),d,o+4)
        return [d[o+a:d.index(b'\0',o+a)].decode('utf8','replace') for a in offs[:n]]
    def node(s,t,o):
        d=s.d
        if t==0xC0:
            n=s.u24(d,o+1); types=d[o+4:o+4+n]; vo=(o+4+n+3)&~3
            return [s.val(types[i],vo+4*i) for i in range(n)]
        if t==0xC1:
            n=s.u24(d,o+1); r={}
            for i in range(n):
                e=o+4+8*i; k=s.u24(d,e); tt=d[e+3]; r[s.keys[k]]=s.val(tt,e+4)
            return r
        if t==0x20:  # hash map, 32-bit keys
            n=s.u24(d,o+1); r={}
            for i in range(n):
                e=o+4+8*i; h,v=struct.unpack_from(s.e+'II',d,e)
                tt=d[o+4+8*n+i]; r[h]=s.val(tt,e+4)
            return r
        if t==0x21:  # hash map, 64-bit keys
            n=s.u24(d,o+1); r={}
            for i in range(n):
                e=o+4+12*i; h,=struct.unpack_from(s.e+'Q',d,e)
                tt=d[o+4+12*n+i]; r[h]=s.val(tt,e+8)
            return r
        raise Exception('node %x'%t)
    def val(s,t,o):
        d=s.d; v,=struct.unpack_from(s.e+'I',d,o)
        if t in (0xC0,0xC1,0x20,0x21): return s.node(t,v)
        if t==0xA0: return s.strs[v]
        if t==0xA1: n,=struct.unpack_from(s.e+'I',d,v); return d[v+4:v+4+n]
        if t==0xD0: return bool(v)
        if t==0xD1: return struct.unpack_from(s.e+'i',d,o)[0]
        if t==0xD2: return struct.unpack_from(s.e+'f',d,o)[0]
        if t==0xD3: return v
        if t==0xD4: return struct.unpack_from(s.e+'q',d,v)[0]
        if t==0xD5: return struct.unpack_from(s.e+'Q',d,v)[0]
        if t==0xD6: return struct.unpack_from(s.e+'d',d,v)[0]
        if t==0xFF: return None
        raise Exception('val %x'%t)
