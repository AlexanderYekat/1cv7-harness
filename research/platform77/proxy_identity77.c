/* Client-side, x86 COM proxy inspection. Never calls methods on the target,
 * initializes a database, injects code, or changes system configuration.
 * CoDecodeProxy fails closed if Windows cannot establish the server identity.
 * https://learn.microsoft.com/windows/win32/api/combaseapi/nf-combaseapi-codecodeproxy
 */
typedef long HRESULT;
typedef unsigned long ULONG;
typedef unsigned int UINT;
typedef unsigned short WORD;
typedef unsigned short WCHAR;
typedef struct { ULONG a; WORD b, c; unsigned char d[8]; } GUID;
typedef struct Variant Variant;
struct Variant { WORD vt, r1, r2, r3; union { long number; void *pointer; ULONG words[2]; } value; };
typedef struct { Variant *args; long *names; UINT count, named; } Params;
typedef struct Object { const void *vtable; } Object;
typedef struct { ULONG pid, tid; unsigned long long address; } ServerInformation;
#define API __stdcall
#define EXPORT __declspec(dllexport)
#define INVALID ((HRESULT)0x80070057L)
__declspec(dllimport) HRESULT API CoDecodeProxy(ULONG, unsigned long long, ServerInformation *);
__declspec(dllimport) ULONG API GetCurrentProcessId(void);
static const GUID class_id = {0x7e477c71,0x018e,0x4c27,{0x9e,0x38,0x2d,0x5d,0xda,0x9f,0x6a,0x07}};
static const GUID unknown_id = {0,0,0,{0xc0,0,0,0,0,0,0,0x46}};
static const GUID dispatch_id = {0x20400,0,0,{0xc0,0,0,0,0,0,0,0x46}};
static const GUID factory_id = {1,0,0,{0xc0,0,0,0,0,0,0,0x46}};
static volatile long references, locks;
static ULONG last_tid;
static Object instance, factory;
static int equal(const GUID *a, const GUID *b) {
    const unsigned char *x = (const unsigned char *)a, *y = (const unsigned char *)b;
    for (int i = 0; i < 16; ++i) if (x[i] != y[i]) return 0;
    return 1;
}
static ULONG API add_ref(Object *self) { (void)self; return __sync_add_and_fetch(&references, 1); }
static ULONG API release(Object *self) { (void)self; return __sync_sub_and_fetch(&references, 1); }
static HRESULT API query(Object *self, const GUID *iid, void **out) {
    if (!out || !iid) return INVALID;
    *out = 0;
    if (!equal(iid, &unknown_id) && !equal(iid, self == &factory ? &factory_id : &dispatch_id))
        return (HRESULT)0x80004002L;
    *out = self; add_ref(self); return 0;
}
static HRESULT API type_count(Object *self, UINT *count) {
    (void)self; if (!count) return INVALID; *count = 0; return 0;
}
static HRESULT API type_info(Object *self, UINT index, ULONG locale, void **info) {
    (void)self; (void)index; (void)locale;
    if (info) *info = 0;
    return (HRESULT)0x80004001L;
}
static int name_equal(const WCHAR *a, const char *b) {
    if (!a) return 0;
    while (*a && *b) {
        WCHAR c = *a++;
        if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
        if (c != (unsigned char)*b++) return 0;
    }
    return !*a && !*b;
}
static HRESULT API names(Object *self, const GUID *iid, WCHAR **text, UINT count, ULONG locale, long *ids) {
    (void)self; (void)iid; (void)locale;
    if (!text || !ids || count != 1) return INVALID;
    *ids = name_equal(text[0], "serverpid") ? 1 : name_equal(text[0], "serverthreadid") ? 2 : name_equal(text[0], "challenge") ? 3 : -1;
    return *ids == -1 ? (HRESULT)0x80020006L : 0;
}
static HRESULT API invoke(Object *self, long id, const GUID *iid, ULONG locale,
        WORD flags, Params *params, Variant *result, void *exception, UINT *arg_error) {
    (void)self; (void)iid; (void)locale; (void)exception; (void)arg_error;
    if (!(flags & 3) || !params || !result || params->named) return INVALID;
    ULONG answer = 0;
    if (id == 1) {
        last_tid = 0;
        if (params->count != 1 || !params->args) return (HRESULT)0x8002000eL;
        Variant *arg = &params->args[0];
        if (arg->vt == 0x400c) arg = (Variant *)arg->value.pointer; /* VT_BYREF|VT_VARIANT */
        if (!arg) return INVALID;
        void *proxy = arg->value.pointer;
        if (arg->vt == 0x4009 && proxy) proxy = *(void **)proxy;
        else if (arg->vt != 9) return (HRESULT)0x80020005L;
        if (!proxy) return INVALID;
        ServerInformation server = {0, 0, 0};
        HRESULT hr = CoDecodeProxy(GetCurrentProcessId(), (unsigned long long)(ULONG)proxy, &server);
        if (hr != 0) return hr;
        if (!server.pid) return (HRESULT)0x80004005L;
        answer = server.pid; last_tid = server.tid;
    } else if (id == 3) {
        if (params->count != 2 || !params->args) return (HRESULT)0x8002000eL;
        Variant *object = &params->args[1], *name = &params->args[0];
        if (object->vt == 0x400c) object = (Variant *)object->value.pointer;
        if (name->vt == 0x400c) name = (Variant *)name->value.pointer;
        if (!object || !name || name->vt != 8) return INVALID;
        void *proxy = object->value.pointer;
        if (object->vt == 0x4009 && proxy) proxy = *(void **)proxy;
        else if (object->vt != 9) return INVALID;
        if (!proxy || !name->value.pointer) return INVALID;
        typedef HRESULT (API *GetNames)(void *, const GUID *, WCHAR **, UINT, ULONG, long *);
        GetNames get_names = (GetNames)(*(void ***)proxy)[5];
        WCHAR *text = (WCHAR *)name->value.pointer;
        long dispid = -1;
        static const GUID null_id = {0,0,0,{0,0,0,0,0,0,0,0}};
        /* Name lookup only: never Invoke, including on an unexpected server. */
        answer = (ULONG)get_names(proxy, &null_id, &text, 1, 0, &dispid);
    } else if (id == 2 && params->count == 0) answer = last_tid;
    else return (HRESULT)0x80020003L;
    result->vt = 3;
    result->r1 = result->r2 = result->r3 = 0;
    result->value.words[0] = answer; result->value.words[1] = 0;
    return 0;
}
static HRESULT API create(Object *self, Object *outer, const GUID *iid, void **out) {
    (void)self; if (outer) return (HRESULT)0x80040110L;
    return query(&instance, iid, out);
}
static HRESULT API lock_server(Object *self, int lock) {
    (void)self;
    if (lock) __sync_add_and_fetch(&locks, 1); else __sync_sub_and_fetch(&locks, 1);
    return 0;
}
static const struct {
    HRESULT (API *query)(Object *, const GUID *, void **);
    ULONG (API *add)(Object *), (API *release)(Object *);
    HRESULT (API *type_count)(Object *, UINT *);
    HRESULT (API *type_info)(Object *, UINT, ULONG, void **);
    HRESULT (API *names)(Object *, const GUID *, WCHAR **, UINT, ULONG, long *);
    HRESULT (API *invoke)(Object *, long, const GUID *, ULONG, WORD, Params *, Variant *, void *, UINT *);
} dispatch_vtable = {query, add_ref, release, type_count, type_info, names, invoke};
static const struct {
    HRESULT (API *query)(Object *, const GUID *, void **);
    ULONG (API *add)(Object *), (API *release)(Object *);
    HRESULT (API *create)(Object *, Object *, const GUID *, void **);
    HRESULT (API *lock)(Object *, int);
} factory_vtable = {query, add_ref, release, create, lock_server};
static Object instance = {&dispatch_vtable}, factory = {&factory_vtable};
EXPORT HRESULT API DllCanUnloadNow(void) { return references == 0 && locks == 0 ? 0 : 1; }
EXPORT HRESULT API DllGetClassObject(const GUID *clsid, const GUID *iid, void **out) {
    if (!clsid || !out) return INVALID;
    *out = 0;
    if (!equal(clsid, &class_id)) return (HRESULT)0x80040111L;
    return query(&factory, iid, out);
}
