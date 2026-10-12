/* Diagnostic-only, 32-bit in-process COM helper. No DllMain, registry writes,
 * hooks or database access. Flush uses the COM lifetime API on
 * the owning apartment's thread; live object references prevent self-unload.
 * HoldIcpp/ReleaseIcpp track one acquired loader reference around the FormEx
 * unload experiment. If third-party cleanup consumes it, ReleaseIcpp reports
 * that fact (0) without freeing a stale handle. This is NOT general COM cleanup.
 * C vtables and static storage avoid CRT initialization/allocation dependencies.
 */
typedef long HRESULT;
typedef unsigned long ULONG;
typedef unsigned int UINT;
typedef unsigned short WORD;
typedef unsigned short WCHAR;
typedef struct { ULONG a; WORD b, c; unsigned char d[8]; } GUID;
typedef struct { WORD vt, r1, r2, r3; union { long number; ULONG words[2]; } value; } Variant;
typedef struct { Variant *args; long *names; UINT count, named; } Params;
typedef struct Object { const void *vtable; } Object;
#define API __stdcall
#define EXPORT __declspec(dllexport)
#define OK ((HRESULT)0)
#define NO_INTERFACE ((HRESULT)0x80004002L)
#define NOT_IMPLEMENTED ((HRESULT)0x80004001L)
#define INVALID_ARGUMENT ((HRESULT)0x80070057L)
__declspec(dllimport) void API CoFreeUnusedLibraries(void);
__declspec(dllimport) void API CoFreeUnusedLibrariesEx(ULONG, ULONG);
__declspec(dllimport) ULONG API GetCurrentProcessId(void);
__declspec(dllimport) int API GetModuleHandleExA(ULONG, const char *, void **);
__declspec(dllimport) void * API GetModuleHandleA(const char *);
__declspec(dllimport) int API FreeLibrary(void *);
static void *held_icpp;
typedef struct { WCHAR *name; void *params; long id; UINT index; int convention;
                 UINT args; WORD flags, return_type; } MethodData;
typedef struct { MethodData *methods; UINT count; } InterfaceData;
__declspec(dllimport) HRESULT API CreateDispTypeInfo(InterfaceData *, ULONG, void **);
static MethodData method_data[] = {
    {(WCHAR *)L"ProcessId", 0, 1, 7, 4, 0, 1, 3},
    {(WCHAR *)L"Flush", 0, 2, 8, 4, 0, 1, 3},
    {(WCHAR *)L"HoldIcpp", 0, 3, 9, 4, 0, 1, 3},
    {(WCHAR *)L"ReleaseIcpp", 0, 4, 10, 4, 0, 1, 3},
    {(WCHAR *)L"IcppLoaded", 0, 5, 11, 4, 0, 1, 3},
    {(WCHAR *)L"FlushNow", 0, 6, 12, 4, 0, 1, 3}
};
static InterfaceData interface_data = {method_data, 6};

/* {16B8A521-07E4-46D1-A8E7-197BD1CE4477} */
static const GUID class_id = {0x16b8a521,0x07e4,0x46d1,{0xa8,0xe7,0x19,0x7b,0xd1,0xce,0x44,0x77}};
static const GUID unknown_id = {0,0,0,{0xc0,0,0,0,0,0,0,0x46}};
static const GUID dispatch_id = {0x20400,0,0,{0xc0,0,0,0,0,0,0,0x46}};
static const GUID factory_id = {1,0,0,{0xc0,0,0,0,0,0,0,0x46}};
static volatile long references, locks;
static Object instance, factory;

static int equal(const GUID *a, const GUID *b) {
    const unsigned char *x = (const unsigned char *)a, *y = (const unsigned char *)b;
    for (int i = 0; i < 16; ++i) if (x[i] != y[i]) return 0;
    return 1;
}
static ULONG API add_ref(Object *self) { (void)self; return __sync_add_and_fetch(&references, 1); }
static ULONG API release(Object *self) { (void)self; return __sync_sub_and_fetch(&references, 1); }
static HRESULT API query(Object *self, const GUID *iid, void **out) {
    if (!out || !iid) return INVALID_ARGUMENT;
    *out = 0;
    if (!equal(iid, &unknown_id) && !equal(iid, self == &factory ? &factory_id : &dispatch_id)) return NO_INTERFACE;
    *out = self; add_ref(self); return OK;
}
static HRESULT API type_count(Object *self, UINT *count) {
    (void)self; if (!count) return INVALID_ARGUMENT; *count = 1; return OK;
}
static HRESULT API type_info(Object *self, UINT index, ULONG locale, void **info) {
    (void)self; (void)locale;
    if (!info) return INVALID_ARGUMENT;
    *info = 0;
    if (index) return (HRESULT)0x8002000bL;
    return CreateDispTypeInfo(&interface_data, 0x409, info);
}
static long API process_id(Object *self) { (void)self; return (long)GetCurrentProcessId(); }
static long API flush(Object *self) { (void)self; CoFreeUnusedLibraries(); return (long)GetCurrentProcessId(); }
static long API hold_icpp(Object *self) {
    (void)self;
    if (held_icpp) return -1; /* Never acquire twice. */
    /* flags=0 increments the reference count of an ALREADY loaded module. */
    if (!GetModuleHandleExA(0, "1cpp.dll", &held_icpp)) return -2;
    return (long)GetCurrentProcessId();
}
static long API release_icpp(Object *self) {
    void *owned = held_icpp;
    (void)self;
    if (!owned) return -3;
    void *loaded = GetModuleHandleA("1cpp.dll");
    /* In the pinned FormEx/1CPP experiment, immediate COM cleanup consumed the
     * extra reference too. Record that separately; never free a stale handle. */
    if (!loaded) { held_icpp = 0; return 0; }
    if (loaded != owned) return -4;
    if (!FreeLibrary(owned)) return -5;
    held_icpp = 0;
    return (long)GetCurrentProcessId();
}
static long API icpp_loaded(Object *self) {
    (void)self; return GetModuleHandleA("1cpp.dll") != 0;
}
static long API flush_now(Object *self) {
    (void)self;
    /* Diagnostic mode only: explicitly finish COM's candidate-unload pass.
     * Keep our owned 1CPP loader reference across BOTH calls. */
    if (!held_icpp) return -6;
    CoFreeUnusedLibrariesEx(0, 0);
    CoFreeUnusedLibrariesEx(0, 0);
    return (long)GetCurrentProcessId();
}
static int name_equal(const WCHAR *wide, const char *name) {
    if (!wide) return 0;
    while (*wide && *name) {
        WCHAR c = *wide++;
        if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
        if (c != (unsigned char)*name++) return 0;
    }
    return !*wide && !*name;
}
static HRESULT API names(Object *self, const GUID *iid, WCHAR **text, UINT count, ULONG locale, long *ids) {
    (void)self; (void)iid; (void)locale;
    if (!text || !ids || count != 1) return INVALID_ARGUMENT;
    *ids = -1;
    if (name_equal(text[0], "processid")) *ids = 1;
    if (name_equal(text[0], "flush")) *ids = 2;
    if (name_equal(text[0], "holdicpp")) *ids = 3;
    if (name_equal(text[0], "releaseicpp")) *ids = 4;
    if (name_equal(text[0], "icpploaded")) *ids = 5;
    if (name_equal(text[0], "flushnow")) *ids = 6;
    return *ids == -1 ? (HRESULT)0x80020006L : OK;
}
static HRESULT API invoke(Object *self, long id, const GUID *iid, ULONG locale,
                          WORD flags, Params *params, Variant *result, void *exception, UINT *arg_error) {
    (void)self; (void)iid; (void)locale; (void)exception; (void)arg_error;
    long answer;
    if (!(flags & 3) || id < 1 || id > 6) return (HRESULT)0x80020003L;
    if (!params || params->count) return (HRESULT)0x8002000eL;
    if (id == 1) answer = process_id(self);
    else if (id == 2) answer = flush(self);
    else if (id == 3) answer = hold_icpp(self);
    else if (id == 4) answer = release_icpp(self);
    else if (id == 5) answer = icpp_loaded(self);
    else answer = flush_now(self);
    if (result) {
        result->vt = 3; /* VT_I4 */
        result->r1 = result->r2 = result->r3 = 0;
        result->value.words[0] = result->value.words[1] = 0;
        result->value.number = answer;
    }
    return OK;
}
static HRESULT API create(Object *self, Object *outer, const GUID *iid, void **out) {
    (void)self;
    if (outer) return (HRESULT)0x80040110L;
    return query(&instance, iid, out);
}
static HRESULT API lock_server(Object *self, int lock) {
    (void)self;
    if (lock) __sync_add_and_fetch(&locks, 1); else __sync_sub_and_fetch(&locks, 1);
    return OK;
}
static const struct {
    HRESULT (API *query)(Object *, const GUID *, void **);
    ULONG (API *add)(Object *), (API *release)(Object *);
    HRESULT (API *type_count)(Object *, UINT *);
    HRESULT (API *type_info)(Object *, UINT, ULONG, void **);
    HRESULT (API *names)(Object *, const GUID *, WCHAR **, UINT, ULONG, long *);
    HRESULT (API *invoke)(Object *, long, const GUID *, ULONG, WORD, Params *, Variant *, void *, UINT *);
    long (API *process_id)(Object *), (API *flush)(Object *),
         (API *hold_icpp)(Object *), (API *release_icpp)(Object *), (API *icpp_loaded)(Object *),
         (API *flush_now)(Object *);
} dispatch_vtable = {query, add_ref, release, type_count, type_info, names, invoke,
                     process_id, flush, hold_icpp, release_icpp, icpp_loaded, flush_now};
static const struct {
    HRESULT (API *query)(Object *, const GUID *, void **);
    ULONG (API *add)(Object *), (API *release)(Object *);
    HRESULT (API *create)(Object *, Object *, const GUID *, void **);
    HRESULT (API *lock)(Object *, int);
} factory_vtable = {query, add_ref, release, create, lock_server};
static Object instance = {&dispatch_vtable}, factory = {&factory_vtable};

EXPORT HRESULT API DllCanUnloadNow(void) { return references == 0 && locks == 0 && !held_icpp ? OK : 1; }
EXPORT HRESULT API DllGetClassObject(const GUID *clsid, const GUID *iid, void **out) {
    if (!clsid || !out) return INVALID_ARGUMENT;
    *out = 0;
    if (!equal(clsid, &class_id)) return (HRESULT)0x80040111L;
    return query(&factory, iid, out);
}
