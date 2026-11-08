# اختبار المستودع من Postman

ابدأ من جذر المشروع بعد إعداد `.env`.

```sh
docker compose -f compose.yaml -f compose.postman.yaml up -d --wait --wait-timeout 120
python3 tests/prepare_demo.py
```

سبق الخطوات ببناء صورتي `api` و`warehouse` كما في دليل التشغيل. على Windows
يمكن استخدام `py -3` بدل `python3`. يطبع التجهيز مسار مجلد جديد تحت `.demo/`.
احتفظ بـ `scenario.json` محليًا لأنه يتضمن بيانات الحسابات التجريبية.

1. في Postman Desktop اختر **New → gRPC** واكتب `127.0.0.1:50051` في عنوان الخادم.
   أبقِ TLS معطّلًا لاتصال العرض المحلي. في نسخة المتصفح استخدم Desktop Agent.
2. في **Service definition** اضغط **Import a .proto file**.
   اختر `contracts/inventory/v1/inventory.proto` ثم **Next**، وسمّه **Shop Inventory** وحدد **v1**، ثم **Import as API**.
3. من قائمة الطرق اختر الطريقة تحت `inventory.v1.InventoryService`، وانسخ
   محتوى ملف JSON المناسب من `.demo/<run>/grpc-rehearsal` إلى **Message**
   ثم اضغط **Invoke**. احفظ الطلبات الأربعة في مجموعة مستقلة.
4. بعد التدريب استبدل محتويات الطلبات بالملفات المناظرة من
   `.demo/<run>/grpc` ثم اضغط **Save**. تستخدم ملفات المقابلة منتجًا ومعرّفات
   مستقلة. يمكنك التحقق من الرصيد بـ `GetStock` وإبقاء الحجز للمقابلة.

تستخدم رسائل gRPC أسماء الحقول من العقد المستورد مباشرة، مثل `product_id`
و`order_id`. إذا استخدمت ملفات تجهيز أقدم، غيّر أسماء المفاتيح
`productId` و`orderId` إلى هذين الاسمين في مجلدي `grpc-rehearsal/`
و`grpc/`. احتفظ بقيم المعرّفات نفسها.

| الترتيب | الطريقة والملف | النتيجة |
|---|---|---|
| 1 | `GetStock` مع `GetStock.json` | `available = 3` |
| 2 | `Reserve` مع `Reserve.json` | `reserved = true` |
| 3 | كرر `Reserve` ثم `GetStock` | يظل الحجز ناجحًا، والمتاح `2` |
| 4 | `Release` مع `Release.json` مرتين | رد فارغ بنجاح، والمتاح بعدها `3` |
| 5 | `Reserve` مع `Insufficient.json` | حالة gRPC ناجحة مع رفض الحجز و`shortages`، والمتاح `3` |

قد يخفي عرض Protobuf القيمة الافتراضية `reserved = false`. اعتمد على
`shortages` وتحقق من الرصيد. استخدم معرّف طلب جديدًا مشتركًا بين `Reserve.json`
و`Release.json` لإعادة العرض بعد الإرجاع. يمكن أيضًا تشغيل سكربت التجهيز مرة
أخرى لبيانات مستقلة. عرض المنفذ يقتصر على الجهاز المحلي.

[مرجع استيراد العقد في Postman](https://learning.postman.com/latest-v-12/docs/use/send-requests/protocols/grpc/using-service-definition)
