/* TEMPORARY: attempted standalone reproduction of the VS 2026 crash */
typedef unsigned long long ULong;
typedef unsigned char UChar;
typedef unsigned int UInt;
enum { Invalid = 1 };
ULong target = Invalid;
ULong rel_base;
extern void sink(ULong);
extern void decode(const UChar *, UInt);
extern const UChar *buf;

static void cb_a(ULong x) { sink(x + 1); }
static void cb_b(ULong x) { sink(x + 2); }
static void cb_c(ULong x) { sink(x + 3); }

static void ex_ss(UChar r, ULong torun, void (*irgen)(ULong), UInt lensize)
{
   ULong ovl;
   sink(lensize == 64 ? 7 : 6);
   sink(torun != target);
   ovl = target;
   sink(((ovl >> 32) & 0xfff) + (((ovl >> 44) & 0xf) != 0 ? ((ovl >> 44) & 0xf) : 0));
   sink(((ovl >> 16) & 0xfff) + (((ovl >> 28) & 0xf) != 0 ? ((ovl >> 28) & 0xf) : 0));
   sink((lensize == 64 ? 1 : 2) + (r != 0 ? r : 0) + ((ovl >> 48) & 0xff));
   irgen(lensize);
   target = Invalid;
}

static void ex(UChar r1, ULong addr2)
{
   if (target == Invalid) {
      sink(addr2);
      return;
   }
   switch (target & 0xff00000000000000ULL) {
   case 0xd200000000000000ULL: ex_ss(r1, addr2, cb_a, 64); return;
   case 0xd500000000000000ULL: ex_ss(r1, addr2, cb_b, 64); return;
   case 0xd700000000000000ULL: ex_ss(r1, addr2, cb_c, 32); return;
   case 0xd600000000000000ULL: ex_ss(r1, addr2, cb_a, 32); return;
   case 0xd400000000000000ULL: ex_ss(r1, addr2, cb_b, 32); return;
   case 0xdc00000000000000ULL: ex_ss(r1, addr2, cb_c, 64); return;
   case 0xe800000000000000ULL: ex_ss(r1, addr2, cb_a, 64); return;
   default: {
      UChar *bytes;
      sink(addr2 != target);
      bytes = (UChar *)&target;
      decode(bytes, ((((bytes[0] >> 6) + 1) >> 1) + 1) << 1);
      target = Invalid;
   }
   }
}

void exrl(UChar r1, UInt offset)
{
   ULong a;
   if (target == Invalid) {
      const UChar *bytes = buf + offset;
      a = offset;
      if (bytes != 0) {
         target = ((ULong)bytes[0] << 56) | ((ULong)bytes[1] << 48);
         if (bytes[0] >= 0x40)
            target |= ((ULong)bytes[2] << 40) | ((ULong)bytes[3] << 32);
         if (bytes[0] >= 0xc0)
            target |= ((ULong)bytes[4] << 24) | ((ULong)bytes[5] << 16);
         rel_base = a;
      }
   } else
      a = rel_base;
   ex(r1, a);
}

void (*const table[])(UChar, ULong) = { ex };
