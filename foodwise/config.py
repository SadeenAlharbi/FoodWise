"""إعدادات FoodWise. كل الافتراضات التقديرية هنا في مكان واحد."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
OUT_DIR = DATA_DIR / "out"
DECISIONS_FILE = DATA_DIR / "decisions_today.csv"
ORDER_APPROVALS_FILE = DATA_DIR / "order_approvals.csv"
PICKUPS_FILE = DATA_DIR / "donation_pickups.csv"
NOTICES_FILE = DATA_DIR / "donation_notices.csv"
RESPONSES_FILE = DATA_DIR / "charity_responses.csv"

SEED = 42
DAYS = 800                       # طول السجل التاريخي (يشمل رمضانين وعيدين لتعلم أثر المواسم)
LAST_DATA_DAY = "2026-10-22"     # آخر يوم مسجل؛ يوم القرار هو اليوم التالي
FOODWISE_WEEKS = 8               # منذ متى يستخدم الفرع FoodWise (لصفحة الأثر)

BRANCH_NAME = "فرع بريدة"
PAYDAY = 27                      # يوم صرف الرواتب في الشهر

HORIZON = 7                      # الأفق الأساسي (قائمة الإنقاذ واختبار حساب الهدر)
FORECAST_DAYS = 30               # أطول فترة يختارها المدير في صفحة توقع الهدر
PERIODS = [3, 7, 14, 21, 30]     # الفترات المتاحة للاختيار (أيام)
TEST_DAYS = 42                   # آخر 6 أسابيع للاختبار الزمني
SCENARIOS = 200                  # سيناريوهات الطلب في حساب الهدر

# سياسة الطلب المعتادة في الفرع: متوسط مبيعات آخر 7 أيام × أيام التغطية × معامل مبالغة، ثم يُخصم المخزون
USUAL_ORDER_FACTOR = {"bakery": 1.3, "produce": 1.25, "dairy": 1.45}
USUAL_SAFETY_DAYS = {"bakery": 0.0, "produce": 0.5, "dairy": 1.5}
SMART_ORDER_BUFFER = 1.05        # هامش بسيط فوق الطلب المتوقع في الطلبية المقترحة

# قواعد قائمة الإنقاذ
DISCOUNT_SHORT = 35              # خصم للمنتج الذي ينتهي غدًا (%)
DISCOUNT_LONG = 25               # خصم للمنتج الذي ينتهي خلال يومين (%)
DISCOUNT_LAST = 50               # آخر خصم حتى الإغلاق للمنتج الذي ينتهي اليوم (%)
DONATE_DAYS = 2                  # يُتبرع بالفائض المتوقع قبل انتهاء الصلاحية بيومين (بيوم للمنتج الذي صلاحيته يومان)
RESCUE_RATE = {"discount": 0.75, "front": 0.5, "eatfresh": 0.8, "donate": 1.0}   # نسبة الكمية المتوقع إنقاذها
EATFRESH_CATEGORIES = ["produce"]
EATFRESH_DAYS = 3                   # يُنقل لقسم Eat Fresh قبل انتهاء صلاحيته بثلاثة أيام   # أصناف تُنقل لقسم Eat Fresh لتحضير الوجبات والسلطات قبل انتهاء صلاحيتها
PRIORITY_HIGH = 150              # ر.س
PRIORITY_MID = 60                # ر.س

CATEGORY_AR = {"bakery": "مخبوزات", "produce": "خضار وفواكه", "dairy": "ألبان"}
ACTION_AR = {"discount": "خصم", "front": "نقل لواجهة العرض", "eatfresh": "نقل لقسم Eat Fresh",
             "donate": "تبرع لجمعية معتمدة"}

# التكامل مع الجمعيات
CHARITY_NAME = "جمعية حفظ النعمة"     # اسم الجمعية المتعاقد معها (يُعدّل هنا)
PICKUP_TIME = "قبل الإغلاق"          # موعد الاستلام لتبرعات اليوم
DONATION_NOTICE_DAYS = 7             # التبرعات المتوقعة تُعرض للأيام السبعة القادمة
DONATION_MIN_KG = 0.5                # أقل كمية للمنتج تُذكر في الإشعار المسبق
DONATION_CATEGORIES = ["bakery", "produce", "dairy"]
PICKUP_STATUS = {"sent": "أُرسل للجمعية", "confirmed": "أكدت الجمعية الاستلام", "delivered": "تم التسليم",
                 "cancelled": "أُلغي الطلب"}
PICKUP_NEXT = {"sent": ("confirmed", "تأكيد الاستلام"), "confirmed": ("delivered", "تم الاستلام")}
# كما تراها الجمعية في بوابتها
CHARITY_STATUS = {"sent": "بانتظار تأكيدكم", "confirmed": "مؤكد", "delivered": "تم الاستلام", "cancelled": "أُلغي من الفرع"}
RESPONSE_AR = {"yes": "ستستلم", "no": "لا تستطيع الاستلام"}
